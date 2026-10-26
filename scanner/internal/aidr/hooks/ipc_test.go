//go:build darwin || linux

package hooks

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

func TestReceiverDatabaseWriterContentionStaysWithinResponseBudget(t *testing.T) {
	root, err := os.MkdirTemp("", "aidr-writer-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	root, _ = filepath.EvalSymlinks(root)
	s := openTestStore(t, filepath.Join(root, "state"), 10)
	r, err := Listen(filepath.Join(root, "h.sock"), s)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go r.Serve(ctx)
	db, err := sql.Open("sqlite", filepath.Join(s.directory, "hooks.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err = db.Exec("BEGIN IMMEDIATE"); err != nil {
		t.Fatal(err)
	}
	req := IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(99), Agent: "codex", Hook: "PreToolUse", Raw: json.RawMessage(storeInput)}
	response, err := Exchange(context.Background(), r.path, req)
	db.Exec("ROLLBACK")
	if err != nil || (response.Code != "aidr_hook_receiver_busy" && response.Code != "aidr_hook_storage_failed") {
		t.Fatal("writer wait escaped response budget", response.Code, err)
	}
	response, err = Exchange(context.Background(), r.path, req)
	if err != nil || response.Code != "aidr_hook_recorded" {
		t.Fatal("writer release did not recover", response.Code, err)
	}
}

func TestExchangeClassifiesResponseFailures(t *testing.T) {
	for _, tc := range []struct {
		name, body, code, cause string
		truncate, timeout       bool
	}{
		{name: "eof", truncate: true, code: "aidr_hook_transport_failed", cause: "truncated_frame"},
		{name: "timeout", timeout: true, code: "aidr_hook_response_timeout", cause: "timeout"},
		{name: "invalid_json", body: `{"secret":`, code: "aidr_hook_protocol_invalid", cause: "invalid_json"},
		{name: "unknown_field", body: `{"version":1,"private_payload":"DO_NOT_LOG"}`, code: "aidr_hook_protocol_invalid", cause: "invalid_json"},
		{name: "version", body: `{"version":2}`, code: "aidr_hook_protocol_invalid", cause: "version_mismatch"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root, err := os.MkdirTemp("", "aidr-frame-")
			if err != nil {
				t.Fatal(err)
			}
			defer os.RemoveAll(root)
			path := filepath.Join(root, "h.sock")
			listener, err := net.Listen("unix", path)
			if err != nil {
				t.Fatal(err)
			}
			defer listener.Close()
			done := make(chan struct{})
			go func() {
				defer close(done)
				c, e := listener.Accept()
				if e != nil {
					return
				}
				defer c.Close()
				var req IPCRequest
				if readFrame(c, &req) != nil {
					return
				}
				if tc.timeout {
					time.Sleep(750 * time.Millisecond)
					return
				}
				if tc.truncate {
					c.Write([]byte{0, 0})
					return
				}
				var header [4]byte
				binary.BigEndian.PutUint32(header[:], uint32(len(tc.body)))
				c.Write(header[:])
				c.Write([]byte(tc.body))
			}()
			budget := 3 * time.Second
			if tc.timeout {
				budget = 500 * time.Millisecond
			}
			ctx, cancel := context.WithTimeout(context.Background(), budget)
			defer cancel()
			_, err = Exchange(ctx, path, IPCRequest{Version: 1, Method: "GetHealth"})
			var failure *IPCError
			if !errors.As(err, &failure) || failure.Code != tc.code || failure.Cause != tc.cause || failure.Stage != "response_read" {
				t.Fatalf("unexpected classification: %#v %v", failure, err)
			}
			<-done
		})
	}
}

func TestReceiverStorageContentionReturnsBusyAndRecovers(t *testing.T) {
	root, err := os.MkdirTemp("", "aidr-busy-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	root, _ = filepath.EvalSymlinks(root)
	s := openTestStore(t, filepath.Join(root, "state"), 10)
	r, err := Listen(filepath.Join(root, "h.sock"), s)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	s.mu.Lock()
	s.controlMode = "intercept"
	s.bridgeIntercept.Store(true)
	started := time.Now()
	response, failure := Exchange(context.Background(), r.path, IPCRequest{Version: 1, Method: "GetHealth"})
	s.mu.Unlock()
	if failure != nil || response.Code != "aidr_hook_receiver_busy" {
		t.Fatalf("storage contention mislabeled after %v: response=%s error=%v", time.Since(started), response.Code, failure)
	}
	if response.State == nil || response.State.ControlMode != "plugin_pre_tool" {
		t.Fatal("busy response lost interception mode")
	}
	response, failure = Exchange(context.Background(), r.path, IPCRequest{Version: 1, Method: "GetHealth"})
	if failure != nil || response.Code != "aidr_hook_healthy" {
		t.Fatal("receiver did not recover without restart", response.Code, failure)
	}
	cancel()
	<-done
}

func TestReceiverClosePreservesReplacementSocket(t *testing.T) {
	root, err := os.MkdirTemp("", "aidr-replace-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(root) })
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	s := openTestStore(t, filepath.Join(root, "state"), 10)
	path := filepath.Join(root, "r.sock")
	r, err := Listen(path, s)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(path, filepath.Join(root, "original.sock")); err != nil {
		t.Fatal(err)
	}
	replacement, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer replacement.Close()
	r.Close()
	if _, err = os.Lstat(path); err != nil {
		t.Fatal("closing the owned receiver removed a different socket", err)
	}
}

func TestReceiverRealSocketIdentityFramingAndShutdown(t *testing.T) {
	root, err := os.MkdirTemp("", "aidr-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(root) })
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	s := openTestStore(t, filepath.Join(root, "state"), 10)
	path := filepath.Join(root, "h.sock")
	r, err := Listen(path, s)
	if err != nil {
		t.Fatal(err)
	}
	identity, err := r.SocketIdentity()
	if err != nil || identity["kind"] != "aidr_receiver_socket" || identity["inode"] == "" || len(identity) != 3 {
		t.Fatalf("socket startup identity: %v %v", identity, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	if second, e := Listen(path, s); e == nil {
		second.listener.Close()
		t.Fatal("existing socket replaced")
	}
	reply, err := Exchange(ctx, path, IPCRequest{Version: 1, Method: "GetHealth"})
	if err != nil || reply.Code != "aidr_hook_healthy" {
		t.Fatalf("health: %+v %v", reply, err)
	}
	req := IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(1), Agent: "codex", Hook: "PreToolUse", Raw: json.RawMessage(storeInput)}
	reply, err = Exchange(ctx, path, req)
	if err != nil || reply.Code != "aidr_hook_recorded" || reply.Sequence != "1" {
		t.Fatalf("receive: %+v %v", reply, err)
	}
	retry, err := Exchange(ctx, path, req)
	if err != nil || retry.Sequence != reply.Sequence {
		t.Fatal("retry duplicated event")
	}
	b, err := s.Prepare(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var batch struct {
		Records []Record `json:"records"`
	}
	if json.Unmarshal(b.Payload, &batch) != nil || len(batch.Records) != 1 || batch.Records[0].User != strconv.Itoa(os.Geteuid()) {
		t.Fatal("peer identity not persisted")
	}
	for _, attack := range []any{
		map[string]any{"version": 1, "method": "SubmitEvent", "user_scope": "0"},
		map[string]any{"version": 1, "method": "SubmitEvent", "bridge_process": map[string]string{"pid": "1"}},
		map[string]any{"version": 2, "method": "GetHealth"},
	} {
		c, e := net.Dial("unix", path)
		if e != nil {
			t.Fatal(e)
		}
		c.SetDeadline(time.Now().Add(3 * time.Second))
		if e = writeFrame(c, attack); e != nil {
			t.Fatal(e)
		}
		var out IPCResponse
		e = readFrame(c, &out)
		c.Close()
		if e != nil || out.Code != "aidr_hook_protocol_invalid" {
			t.Fatalf("untrusted frame accepted: %+v %v", out, e)
		}
	}
	c, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	c.SetDeadline(time.Now().Add(3 * time.Second))
	var oversized [4]byte
	binary.BigEndian.PutUint32(oversized[:], maxFrame+1)
	c.Write(oversized[:])
	var out IPCResponse
	err = readFrame(c, &out)
	c.Close()
	if err != nil || out.Code != "aidr_hook_record_oversized" {
		t.Fatal("oversized frame not rejected")
	}
	// Leave an incomplete frame outstanding while stopping the receiver.
	c, err = net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.Write([]byte{0})
	cancel()
	select {
	case err = <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("receiver did not recycle workers")
	}
	if _, err = os.Lstat(path); !os.IsNotExist(err) {
		t.Fatal("owned socket not removed")
	}
}

type shortFrameWriter struct{}

func (shortFrameWriter) Write(p []byte) (int, error) { return len(p) - 1, nil }
func TestFrameWritePreservesBytesAndShortWriteFailure(t *testing.T) {
	req := IPCRequest{Version: 1, Method: "GetHealth"}
	var frame bytes.Buffer
	if err := writeFrame(&frame, req); err != nil {
		t.Fatal(err)
	}
	var got IPCRequest
	if err := readFrame(&frame, &got); err != nil || got.Version != 1 || got.Method != req.Method {
		t.Fatal(got, err)
	}
	if err := writeFrame(shortFrameWriter{}, req); !errors.Is(err, io.ErrShortWrite) {
		t.Fatal(err)
	}
}
