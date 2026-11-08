package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/json"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/privatefs"
	"testing"
	"time"
)

func upgradeSocket(t *testing.T) string {
	t.Helper()
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := privatefs.PrepareDirectory(dir); err != nil {
		t.Fatal(err)
	}
	return filepath.Join(dir, "hook.sock")
}

func TestWindowsHookPipeAllowsDelayedReply(t *testing.T) {
	path := upgradeSocket(t)
	s := openTestStore(t, filepath.Join(filepath.Dir(path), "state"), 10)
	r, err := Listen(path, s)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() {
		c, err := r.listener.Accept()
		if err != nil {
			done <- err
			return
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(4 * time.Second))
		var req IPCRequest
		if err := readFrame(c, &req); err != nil {
			done <- err
			return
		}
		time.Sleep(2250 * time.Millisecond)
		done <- writeFrame(c, IPCResponse{Version: 1, Code: "aidr_hook_healthy"})
	}()
	reply, err := Exchange(ctx, path, IPCRequest{Version: 1, Method: "GetHealth"})
	if err != nil || reply.Code != "aidr_hook_healthy" {
		t.Fatalf("reply within the Windows connection budget was lost: %+v %v", reply, err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestWindowsReceiverIdentityDecisionsAndRecovery(t *testing.T) {
	path := upgradeSocket(t)
	s := openTestStore(t, filepath.Join(filepath.Dir(path), "state"), 10)
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err := s.ConfigureControl(context.Background(), elliptic.Marshal(elliptic.P256(), key.X, key.Y)); err != nil {
		t.Fatal(err)
	}
	s.controlMode = "intercept"
	s.bridgeIntercept.Store(true)
	s.controlPolicy = &ToolPolicy{Revision: "7", Default: "deny"}
	r, err := Listen(path, s)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	if other, e := Listen(path, s); e == nil {
		other.Close()
		t.Fatal("replaced live named pipe")
	}
	self, _ := os.Executable()
	d := DiagnoseReceiver(ctx, path, s.directory, s.platform, s.device, self)
	if d.Ownership != "external_verified" || d.PID != os.Getpid() {
		t.Fatalf("identity: %+v", d)
	}
	req := IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(1), Agent: "qoder-hooks", Hook: "PreToolUse", Raw: json.RawMessage(storeInput)}
	reply, err := Exchange(ctx, path, req)
	if err != nil || reply.Decision == nil || reply.Decision.Decision != "deny" {
		t.Fatalf("deny: %+v %v", reply, err)
	}
	sid, _ := privatefs.UserSID()
	b, err := s.Prepare(ctx)
	var batch struct {
		Records []Record `json:"records"`
	}
	if err != nil || b == nil || json.Unmarshal(b.Payload, &batch) != nil || len(batch.Records) != 1 || batch.Records[0].User != sid {
		t.Fatalf("SID evidence: %v", err)
	}
	// Only an ask policy creates a pending attempt; restart must revoke it.
	s.mu.Lock()
	s.controlPolicy.Default = "ask"
	s.mu.Unlock()
	req.EventID = testID(2)
	reply, err = Exchange(ctx, path, req)
	if err != nil || reply.Decision == nil || reply.Decision.Decision != "ask" {
		t.Fatalf("ask: %+v %v", reply, err)
	}
	cancel()
	select {
	case err = <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("receiver failed to drain")
	}
	s.Close()
	// A crash may leave this marker; kernel ownership, not its contents, decides.
	if err = os.WriteFile(path, []byte("stale"), 0600); err != nil {
		t.Fatal(err)
	}
	s = openTestStore(t, s.directory, 10)
	r, err = Listen(path, s)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	decision, err := s.PollApproval(context.Background(), req.EventID, sid, false, time.Now())
	if err != nil || decision.Decision != "deny" || decision.Code != "aidr_hook_receiver_restarted" {
		t.Fatalf("restart: %+v %v", decision, err)
	}
	if count, err := PendingUploads(context.Background(), s.directory); err != nil || count < 2 {
		t.Fatalf("queue lost: %d %v", count, err)
	}
}
