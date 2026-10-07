package hooks

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"os"
	"path/filepath"
	products "skill-manager/scanner/internal/aidr/catalog"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const maxFrame = MaxRecordBytes + 4096

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
	listener  *net.UnixListener
	path      string
	file      os.FileInfo
	uid       uint32
	accepted  atomic.Uint64
	rejected  atomic.Uint64
	startedAt string
}

// Listen requires an existing private, caller-owned directory. Existing sockets
// are never removed: an active or stale listener is a visible startup failure.
func Listen(path string, store *Store) (*Receiver, error) {
	if store == nil || !filepath.IsAbs(path) {
		return nil, code("aidr_hook_socket_invalid")
	}
	dir := filepath.Dir(path)
	real, err := filepath.EvalSymlinks(dir)
	if err != nil || real != dir {
		return nil, code("aidr_hook_socket_invalid")
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 || !ownedBy(info, uint32(os.Geteuid())) {
		return nil, code("aidr_hook_socket_invalid")
	}
	if _, err = os.Lstat(path); !os.IsNotExist(err) {
		return nil, code("aidr_hook_socket_exists")
	}
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, code("aidr_hook_socket_unavailable")
	}
	l.SetUnlinkOnClose(false)
	if err = os.Chmod(path, 0600); err != nil {
		l.Close()
		os.Remove(path)
		return nil, code("aidr_hook_socket_invalid")
	}
	info, err = os.Lstat(path)
	if err != nil {
		l.Close()
		return nil, code("aidr_hook_socket_invalid")
	}
	return &Receiver{store: store, listener: l, path: path, file: info, uid: uint32(os.Geteuid()), startedAt: time.Now().UTC().Format(time.RFC3339Nano)}, nil
}

// Close releases the listener and only the socket instance created by Listen.
func (r *Receiver) Close() {
	r.listener.Close()
	if info, err := os.Lstat(r.path); err == nil && os.SameFile(info, r.file) {
		os.Remove(r.path)
	}
}

// Serve limits both active requests and raw in-memory data. Closing the context
// closes this listener and all active connections before returning.
func (r *Receiver) Serve(ctx context.Context) error {
	var workers sync.WaitGroup
	var mu sync.Mutex
	active := map[*net.UnixConn]bool{}
	slots := make(chan struct{}, 16)
	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			r.listener.Close()
			mu.Lock()
			for c := range active {
				c.Close()
			}
			mu.Unlock()
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
		c, err := r.listener.AcceptUnix()
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
		mu.Lock()
		active[c] = true
		mu.Unlock()
		workers.Add(1)
		go func() {
			defer workers.Done()
			defer func() { c.Close(); mu.Lock(); delete(active, c); mu.Unlock(); <-slots }()
			c.SetDeadline(time.Now().Add(2 * time.Second))
			response := r.handle(ctx, c)
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

func (r *Receiver) handle(ctx context.Context, c *net.UnixConn) IPCResponse {
	uid, err := peerUID(c)
	if err != nil || uid != r.uid {
		return IPCResponse{Code: "aidr_hook_peer_rejected"}
	}
	var req IPCRequest
	if readFrame(c, &req) != nil || req.Version != 1 {
		return IPCResponse{Code: "aidr_hook_protocol_invalid"}
	}
	if req.Method == "GetHealth" {
		state, err := r.store.Status(ctx)
		if err != nil {
			return IPCResponse{Code: "aidr_hook_storage_failed"}
		}
		return IPCResponse{Code: "aidr_hook_healthy", State: &state, Receiver: &ReceiverIdentity{PID: os.Getpid(), StartedAt: r.startedAt, Server: diagnosticServer(r.store.platform), Socket: r.path, Queue: r.store.directory}}
	}
	if req.Method == "PollApproval" || req.Method == "CancelApproval" {
		if r.store.BridgeControlMode() == "audit" {
			return IPCResponse{Code: "aidr_hook_decision", Decision: &ToolDecision{Decision: "allow", Code: "aidr_hook_audit_only"}}
		}
		d, err := r.store.PollApproval(ctx, req.EventID, strconv.FormatUint(uint64(uid), 10), req.Method == "CancelApproval", time.Now())
		if err != nil {
			return IPCResponse{Code: "aidr_hook_storage_failed"}
		}
		return IPCResponse{Code: "aidr_hook_decision", Decision: &d}
	}
	if req.Method != "SubmitEvent" {
		return IPCResponse{Code: "aidr_hook_method_unsupported"}
	}
	work, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	record, err := r.store.receiveWithBridge(work, req.EventID, strconv.FormatUint(uint64(uid), 10), req.Agent, req.Hook, req.Raw, bridgeProcess(c))
	if err != nil {
		// SQLite/path errors can contain input data. Return only stable public codes.
		value := err.Error()
		if !strings.HasPrefix(value, "aidr_hook_") || len(value) > 80 || strings.ContainsAny(value, " \n\r\t") {
			value = "aidr_hook_storage_failed"
		}
		return IPCResponse{Code: value}
	}
	r.accepted.Add(1)
	response := IPCResponse{Code: "aidr_hook_recorded", Sequence: record.Sequence, State: &StoreStatus{ControlMode: r.store.BridgeControlMode()}}
	if record.Sequence == "" {
		response.Code = "aidr_hook_audit_paused"
	}
	if IsPreTool(req.Agent, req.Hook) && r.store.BridgeControlMode() == "plugin_pre_tool" {
		if record.Event.Schema == 0 {
			return IPCResponse{Code: "aidr_hook_attempt_already_recorded"}
		}
		d := r.store.EvaluateTool(record.Event, time.Now())
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
				return IPCResponse{Code: "aidr_hook_storage_failed"}
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
		return err
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
	_, err = io.Copy(w, io.MultiReader(bytes.NewReader(header[:]), bytes.NewReader(b)))
	return err
}

func Exchange(ctx context.Context, path string, req IPCRequest) (IPCResponse, error) {
	var response IPCResponse
	d := net.Dialer{Timeout: time.Second}
	c, err := d.DialContext(ctx, "unix", path)
	if err != nil {
		return response, code("aidr_hook_receiver_unavailable")
	}
	defer c.Close()
	uid, err := peerUID(c.(*net.UnixConn))
	if err != nil || uid != uint32(os.Geteuid()) {
		return response, code("aidr_hook_peer_rejected")
	}
	deadline := time.Now().Add(2 * time.Second)
	if earlier, ok := ctx.Deadline(); ok && earlier.Before(deadline) {
		deadline = earlier
	}
	c.SetDeadline(deadline)
	if err = writeFrame(c, req); err != nil {
		return response, code("aidr_hook_transport_failed")
	}
	if err = readFrame(c, &response); err != nil || response.Version != 1 {
		return IPCResponse{}, code("aidr_hook_protocol_invalid")
	}
	return response, nil
}
