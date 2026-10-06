//go:build darwin || linux

package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestAuditPausePreservesIndependentControlOverRealIPC(t *testing.T) {
	root, err := os.MkdirTemp("", "aidr-pause-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(root) })
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	s := openTestStore(t, filepath.Join(root, "state"), 10)
	p := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{}, Lifecycle: &agentlog.AuditLifecycle{Enabled: false, RetentionDays: 7}}
	if err = s.SetPolicy(context.Background(), p); err != nil {
		t.Fatal(err)
	}
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err = s.ConfigureControl(context.Background(), elliptic.Marshal(elliptic.P256(), key.X, key.Y)); err != nil {
		t.Fatal(err)
	}
	r, err := Listen(filepath.Join(root, "h.sock"), s)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(3 * time.Second):
			t.Error("receiver not reclaimed")
		}
	})
	for i, expected := range []string{"allow", "deny", "ask"} {
		now := time.Now()
		policy := ToolPolicy{Schema: 1, Domain: "aidr.tool-policy/1", Device: "device-a", Revision: fmt.Sprint(i + 1), Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Hour).Unix()), Default: expected, Rules: []ToolRule{}}
		if err = s.ApplyToolPolicy(ctx, signGrant(t, key, policy), now); err != nil {
			t.Fatal(err)
		}
		req := IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(i + 1), Agent: "codex", Hook: "PreToolUse", Raw: json.RawMessage(storeInput)}
		reply, err := Exchange(ctx, r.path, req)
		if err != nil || reply.Code != "aidr_hook_audit_paused" || reply.Sequence != "" || reply.Decision == nil {
			t.Fatal(reply, err)
		}
		decision := expected
		if expected == "ask" {
			decision = "deny"
			if reply.Decision.Code != "aidr_hook_audit_disabled_requires_evidence" {
				t.Fatal(reply)
			}
		}
		if reply.Decision.Decision != decision {
			t.Fatal("control changed by collection pause", reply)
		}
	}
	state, err := s.Status(ctx)
	if err != nil || state.Queued != 0 || state.LastSequence != "0" || state.Suppressed != 3 {
		t.Fatal(state, err)
	}
	// Nothing that would authorize an approval can be formed without audit evidence.
	if frozen, err := s.Prepare(ctx); err != nil || frozen != nil {
		t.Fatal("paused audit created a batch", err)
	}
}
