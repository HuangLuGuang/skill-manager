//go:build darwin || linux

package main

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
)

func TestTraeBridgeWaitsForPlatformApproval(t *testing.T) {
	for _, agent := range []string{"trae", "trae-cn"} {
		for _, action := range []string{"allow", "deny", "timeout", "cancel"} {
			t.Run(agent+"/"+action, func(t *testing.T) {
				root, err := os.MkdirTemp("", "tr-approval-")
				if err != nil {
					t.Fatal(err)
				}
				defer os.RemoveAll(root)
				root, err = filepath.EvalSymlinks(root)
				if err != nil {
					t.Fatal(err)
				}
				s, err := hooks.OpenStore(filepath.Join(root, "state"), "https://platform.example", "test-device", 20)
				if err != nil {
					t.Fatal(err)
				}
				defer s.Close()
				ctx := context.Background()
				key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
				if err != nil {
					t.Fatal(err)
				}
				pub := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
				sign := func(value any) []byte {
					payload, err := json.Marshal(value)
					if err != nil {
						t.Fatal(err)
					}
					digest := sha256.Sum256(payload)
					sig, err := ecdsa.SignASN1(rand.Reader, key, digest[:])
					if err != nil {
						t.Fatal(err)
					}
					wire, err := json.Marshal(map[string]string{"payload": base64.StdEncoding.EncodeToString(payload), "signature": base64.StdEncoding.EncodeToString(sig)})
					if err != nil {
						t.Fatal(err)
					}
					return wire
				}
				if err = s.ConfigureControl(ctx, pub); err != nil {
					t.Fatal(err)
				}
				policy := hooks.ToolPolicy{Schema: 4, Domain: "aidr.tool-policy/4", ApprovalWaitSeconds: 180, Device: "test-device", Revision: "1", Issued: fmt.Sprint(time.Now().Unix()), Default: "ask", Rules: []hooks.ToolRule{}}
				if err = s.ApplyToolPolicy(ctx, sign(policy), time.Now()); err != nil {
					t.Fatal(err)
				}
				socket := filepath.Join(root, "r.sock")
				receiver, err := hooks.Listen(socket, s)
				if err != nil {
					t.Fatal(err)
				}
				serve, stop := context.WithCancel(ctx)
				stopped := make(chan error, 1)
				go func() { stopped <- receiver.Serve(serve) }()
				defer func() { stop(); <-stopped }()
				var out, diagnostics bytes.Buffer
				done := make(chan error, 1)
				go func() {
					done <- aidrHookWithDiagnostics([]string{"--agent", agent, "--event", "PreToolUse", "--socket", socket}, strings.NewReader(`{"hook_event_name":"PreToolUse","session_id":"session","agent_id":"solo_agent","tool_use_id":"call","tool_name":"RunCommand","tool_input":{"command":"printf approved"}}`), &out, &diagnostics)
				}()
				var pending *hooks.ApprovalSubmission
				for deadline := time.Now().Add(3 * time.Second); time.Now().Before(deadline); {
					pending, err = s.PendingApproval(ctx, time.Now())
					if err != nil {
						t.Fatal(err)
					}
					if pending != nil {
						break
					}
					time.Sleep(10 * time.Millisecond)
				}
				if pending == nil {
					t.Fatal("approval not queued")
				}
				select {
				case err := <-done:
					t.Fatal("bridge returned before platform decision", err)
				case <-time.After(300 * time.Millisecond):
				}
				batch, err := s.Prepare(ctx)
				if err != nil || batch == nil {
					t.Fatal("missing evidence", err)
				}
				var evidence struct {
					Records []hooks.Record `json:"records"`
				}
				if err = json.Unmarshal(batch.Payload, &evidence); err != nil || len(evidence.Records) != 1 {
					t.Fatal(err)
				}
				record := evidence.Records[0]
				scope, err := s.ScopeFor(record, pending.Rule, pending.Revision)
				if err != nil || scope.Turn != "" || scope.Call != "call" {
					t.Fatal(scope, err)
				}
				if action == "timeout" || action == "cancel" {
					at := time.Now()
					if action == "timeout" {
						at = time.Unix(pending.Expires, 0)
					}
					if _, err = s.PollApproval(ctx, pending.Event, record.User, action == "cancel", at); err != nil {
						t.Fatal(err)
					}
				} else {
					id := strings.Repeat("a", 32)
					if err = s.BindApproval(ctx, pending.Event, id, scope); err != nil {
						t.Fatal(err)
					}
					grant := hooks.ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: id, Nonce: strings.Repeat("b", 32), Revision: "1", Decision: action, Issued: fmt.Sprint(time.Now().Unix()), Expires: fmt.Sprint(pending.Expires), Scope: scope}
					if err = s.ApplyGrant(ctx, sign(grant), pub, time.Now()); err != nil {
						t.Fatal(err)
					}
				}
				select {
				case err = <-done:
					if err != nil {
						t.Fatal(err)
					}
				case <-time.After(3 * time.Second):
					t.Fatal("bridge did not consume decision")
				}
				if action == "allow" {
					if strings.TrimSpace(out.String()) != "{}" {
						t.Fatal(out.String())
					}
				} else if !strings.Contains(out.String(), `"permissionDecision":"deny"`) {
					t.Fatal(out.String())
				}
				if d, err := s.PollApproval(ctx, pending.Event, record.User, false, time.Now()); err != nil || d.Decision != "deny" {
					t.Fatal("decision reusable", d, err)
				}
				report, err := s.PrepareAttemptReport(ctx)
				if err != nil || report == nil {
					t.Fatal("terminal receipt missing", err)
				}
			})
		}
	}
}
