//go:build darwin || linux

package hooks

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

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
	if err != nil || out.Code != "aidr_hook_protocol_invalid" {
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
