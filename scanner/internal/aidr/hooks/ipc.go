package hooks

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	products "skill-manager/scanner/internal/aidr/catalog"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const maxFrame = MaxRecordBytes + 4096

// IPCError carries bounded diagnostics without echoing frame contents.
type IPCError struct{ Code, Stage, Cause string }

func (e *IPCError) Error() string { return e.Code }

func frameFailure(err error, stage string) *IPCError {
	result := &IPCError{Code: "aidr_hook_protocol_invalid", Stage: stage, Cause: "invalid_json"}
	var network net.Error
	switch {
	case errors.Is(err, context.Canceled):
		result.Code, result.Cause = "aidr_hook_transport_failed", "canceled"
	case errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &network) && network.Timeout()):
		result.Code, result.Cause = "aidr_hook_response_timeout", "timeout"
	case errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF):
		result.Code, result.Cause = "aidr_hook_transport_failed", "truncated_frame"
	case err.Error() == "aidr_hook_record_oversized":
		result.Code, result.Cause = "aidr_hook_record_oversized", "frame_size"
	case errors.As(err, &network):
		result.Code, result.Cause = "aidr_hook_transport_failed", "connection_error"
	}
	return result
}

func storageFailure(err error) IPCResponse {
	var sqliteError interface{ Code() int }
	busy := errors.As(err, &sqliteError) && (sqliteError.Code()&0xff == 5 || sqliteError.Code()&0xff == 6)
	if busy || errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		return IPCResponse{Code: "aidr_hook_receiver_busy"}
	}
	return IPCResponse{Code: "aidr_hook_storage_failed"}
}

// IPCRequest contains host evidence only. Device, user and process ownership
// are deliberately not accepted from the plugin's payload.
type IPCRequest struct {
	Version int             `json:"version"`
	Method  string          `json:"method"`
	EventID string          `json:"event_id,omitempty"`
	Agent   string          `json:"agent,omitempty"`
	Hook    string          `json:"hook,omitempty"`
	Raw     json.RawMessage `json:"event,omitempty"`
}
type IPCResponse struct {
	Version  int               `json:"version"`
	Code     string            `json:"code"`
	Sequence string            `json:"source_seq,omitempty"`
	Accepted uint64            `json:"accepted"`
	Rejected uint64            `json:"rejected"`
	State    *StoreStatus      `json:"state,omitempty"`
	Decision *ToolDecision     `json:"decision,omitempty"`
	Receiver *ReceiverIdentity `json:"receiver,omitempty"`
}

type Receiver struct {
	store     *Store
	listener  net.Listener
	path      string
	file      os.FileInfo
	accepted  atomic.Uint64
	rejected  atomic.Uint64
	startedAt string
}

// Close releases the listener and only the socket instance created by Listen.
func (r *Receiver) Close() {
	r.listener.Close()
	if info, err := os.Lstat(r.path); err == nil && os.SameFile(info, r.file) {
		os.Remove(r.path)
	}
}

// Serve limits both active requests and raw in-memory data. Closing the context
// stops accepting and drains already accepted requests under their two-second
// connection deadline before returning, preserving decisions during upgrades.
func (r *Receiver) Serve(ctx context.Context) error {
	var workers sync.WaitGroup
	slots := make(chan struct{}, 16)
	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			r.listener.Close()
		case <-done:
		}
	}()
	defer func() {
		close(done)
		r.listener.Close()
		workers.Wait()
		if info, e := os.Lstat(r.path); e == nil && os.SameFile(info, r.file) {
			os.Remove(r.path)
		}
	}()
	for {
		c, err := r.listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return code("aidr_hook_listener_failed")
		}
		select {
		case slots <- struct{}{}:
		default:
			r.rejected.Add(1)
			c.SetDeadline(time.Now().Add(50 * time.Millisecond))
			writeFrame(c, IPCResponse{Version: 1, Code: "aidr_hook_receiver_busy", State: &StoreStatus{ControlMode: r.store.BridgeControlMode()}})
			c.Close()
			continue
		}
		workers.Add(1)
		go func() {
			defer workers.Done()
			defer func() { c.Close(); <-slots }()
			c.SetDeadline(time.Now().Add(2 * time.Second))
			response := r.handle(context.WithoutCancel(ctx), c)
			if response.Code != "aidr_hook_recorded" && response.Code != "aidr_hook_audit_paused" && response.Code != "aidr_hook_healthy" && response.Code != "aidr_hook_decision" {
				r.rejected.Add(1)
			}
			response.Version = 1
			if response.State == nil {
				response.State = &StoreStatus{ControlMode: r.store.BridgeControlMode()}
			}
			response.Accepted = r.accepted.Load()
			response.Rejected = r.rejected.Load()
			writeFrame(c, response)
		}()
	}
}

func (r *Receiver) handle(ctx context.Context, c net.Conn) IPCResponse {
	user, err := authenticatedPeer(c)
	if err != nil {
		return IPCResponse{Code: "aidr_hook_peer_rejected"}
	}
	var req IPCRequest
	if err := readFrame(c, &req); err != nil {
		return IPCResponse{Code: frameFailure(err, "request_read").Code}
	}
	if req.Version != 1 {
		return IPCResponse{Code: "aidr_hook_protocol_invalid"}
	}
	ctx, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	if req.Method == "GetHealth" {
		state, err := r.store.Status(ctx)
		if err != nil {
			return storageFailure(err)
		}
		return IPCResponse{Code: "aidr_hook_healthy", State: &state, Receiver: &ReceiverIdentity{PID: os.Getpid(), StartedAt: r.startedAt, Server: diagnosticServer(r.store.platform), Socket: r.path, Queue: r.store.directory}}
	}
	mode, err := r.store.bridgeControlModeContext(ctx)
	if err != nil {
		return storageFailure(err)
	}
	if req.Method == "PollApproval" || req.Method == "CancelApproval" {
		if mode == "audit" {
			return IPCResponse{Code: "aidr_hook_decision", Decision: &ToolDecision{Decision: "allow", Code: "aidr_hook_audit_only"}}
		}
		d, err := r.store.PollApproval(ctx, req.EventID, user, req.Method == "CancelApproval", time.Now())
		if err != nil {
			return storageFailure(err)
		}
		return IPCResponse{Code: "aidr_hook_decision", Decision: &d}
	}
	if req.Method != "SubmitEvent" {
		return IPCResponse{Code: "aidr_hook_method_unsupported"}
	}
	record, err := r.store.receiveWithBridge(ctx, req.EventID, user, req.Agent, req.Hook, req.Raw, bridgeProcessForConn(c))
	if err != nil {
		if ctx.Err() != nil {
			return storageFailure(ctx.Err())
		}
		if failure := storageFailure(err); failure.Code == "aidr_hook_receiver_busy" {
			return failure
		}
		// SQLite/path errors can contain input data. Return only stable public codes.
		value := err.Error()
		if !strings.HasPrefix(value, "aidr_hook_") || len(value) > 80 || strings.ContainsAny(value, " \n\r\t") {
			value = "aidr_hook_storage_failed"
		}
		return IPCResponse{Code: value}
	}
	r.accepted.Add(1)
	mode, err = r.store.bridgeControlModeContext(ctx)
	if err != nil {
		return storageFailure(err)
	}
	response := IPCResponse{Code: "aidr_hook_recorded", Sequence: record.Sequence, State: &StoreStatus{ControlMode: mode}}
	if record.Sequence == "" {
		response.Code = "aidr_hook_audit_paused"
	}
	if IsPreTool(req.Agent, req.Hook) && mode == "plugin_pre_tool" {
		if record.Event.Schema == 0 {
			return IPCResponse{Code: "aidr_hook_attempt_already_recorded"}
		}
		if err := r.store.lockContext(ctx); err != nil {
			return storageFailure(err)
		}
		d := r.store.evaluateToolLocked(record.Event, time.Now())
		r.store.mu.Unlock()
		if record.Event.ControlDecision != nil {
			d = *record.Event.ControlDecision
		}
		product, _ := products.Get(req.Agent)
		if d.Decision == "ask" && !product.Approval {
			d.Decision = "deny"
			d.Code = "aidr_hook_approval_unsupported"
		}
		if d.Decision == "ask" {
			if record.Sequence == "" {
				d.Decision, d.Code = "deny", "aidr_hook_audit_disabled_requires_evidence"
				response.Decision = &d
				return response
			}
			d, err = r.store.BeginApproval(ctx, record, time.Now())
			if err != nil {
				return storageFailure(err)
			}
		}
		response.Decision = &d
	}
	return response
}

func readFrame(r io.Reader, value any) error {
	var header [4]byte
	if _, err := io.ReadFull(r, header[:]); err != nil {
		return err
	}
	n := binary.BigEndian.Uint32(header[:])
	if n == 0 || n > maxFrame {
		return code("aidr_hook_record_oversized")
	}
	b := make([]byte, n)
	if _, err := io.ReadFull(r, b); err != nil {
		return err
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.DisallowUnknownFields()
	if err := d.Decode(value); err != nil {
		return code("aidr_hook_protocol_invalid")
	}
	if d.Decode(new(any)) != io.EOF {
		return code("aidr_hook_protocol_invalid")
	}
	return nil
}
func writeFrame(w io.Writer, value any) error {
	b, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if len(b) > maxFrame {
		return code("aidr_hook_record_oversized")
	}
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], uint32(len(b)))
	buffers := net.Buffers{header[:], b}
	written, err := buffers.WriteTo(w)
	if err == nil && written != int64(len(header)+len(b)) {
		return io.ErrShortWrite
	}
	return err
}

func Exchange(ctx context.Context, path string, req IPCRequest) (IPCResponse, error) {
	var response IPCResponse
	c, err := dialHookEndpoint(ctx, path)
	if err != nil {
		return response, code("aidr_hook_receiver_unavailable")
	}
	defer c.Close()
	stop := context.AfterFunc(ctx, func() { _ = c.SetDeadline(time.Now()) })
	defer stop()
	if _, err := authenticatedPeer(c); err != nil {
		return response, code("aidr_hook_peer_rejected")
	}
	deadline := time.Now().Add(2 * time.Second)
	if earlier, ok := ctx.Deadline(); ok && earlier.Before(deadline) {
		deadline = earlier
	}
	c.SetDeadline(deadline)
	if err = writeFrame(c, req); err != nil {
		return response, frameFailure(err, "request_write")
	}
	if err = readFrame(c, &response); err != nil {
		if ctx.Err() != nil {
			err = ctx.Err()
		}
		return IPCResponse{}, frameFailure(err, "response_read")
	}
	if response.Version != 1 {
		return IPCResponse{}, &IPCError{Code: "aidr_hook_protocol_invalid", Stage: "response_read", Cause: "version_mismatch"}
	}
	return response, nil
}
