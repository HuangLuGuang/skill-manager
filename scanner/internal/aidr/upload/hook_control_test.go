package upload

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
)

func TestHookControlPagingRevocationOfflineAndBadSignature(t *testing.T) {
	ctx := context.Background()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	sign := func(v any) json.RawMessage {
		raw, _ := json.Marshal(v)
		sum := sha256.Sum256(raw)
		sig, err := ecdsa.SignASN1(rand.Reader, key, sum[:])
		if err != nil {
			t.Fatal(err)
		}
		b, _ := json.Marshal(map[string]string{"payload": base64.StdEncoding.EncodeToString(raw), "signature": base64.StdEncoding.EncodeToString(sig)})
		return b
	}
	now := time.Now()
	policy := sign(hooks.ToolPolicy{Schema: 1, Domain: "aidr.tool-policy/1", Device: "device", Revision: "1", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Hour).Unix()), Default: "ask", Rules: []hooks.ToolRule{}})
	var phase atomic.Int32
	var calls atomic.Int32
	var grants []hooks.ToolGrant
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/api/v1/clients/device/aidr/hook-control/snapshot" || r.Header.Get("Authorization") != "Bearer synthetic-device-token" {
			t.Error("wrong authenticated route")
		}
		var request map[string]string
		if json.NewDecoder(r.Body).Decode(&request) != nil {
			t.Error("invalid request")
		}
		if phase.Load() == 2 {
			w.WriteHeader(503)
			return
		}
		page := []json.RawMessage{}
		after := request["after"]
		for _, g := range grants {
			if g.ID <= request["after"] {
				continue
			}
			if g.Scope.Stream != request["stream_id"] || g.Scope.Receiver != request["receiver_instance"] {
				t.Error("wrong receiver binding")
			}
			if phase.Load() == 1 && g.ID == grants[0].ID {
				g.Revision = "2"
				g.Decision = "revoke"
			}
			page = append(page, sign(g))
			after = g.ID
			if len(page) == 20 {
				break
			}
		}
		p := policy
		if phase.Load() == 3 {
			p = json.RawMessage(`{"payload":"invalid","signature":"invalid"}`)
		}
		if phase.Load() == 4 {
			after = request["after"]
		}
		json.NewEncoder(w).Encode(map[string]any{"policy": p, "grants": page, "more_grants": after < grants[len(grants)-1].ID, "next_after": after})
	}))
	defer server.Close()
	c, err := New(Options{Server: server.URL, ClientID: "device", Token: "synthetic-device-token"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	root, _ := filepath.EvalSymlinks(t.TempDir())
	s, err := hooks.OpenStore(filepath.Join(root, "hooks"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	syncer := HookControlSync{}
	if code, err := syncer.Refresh(ctx, c, s); err != nil || code != "aidr_hook_audit_only" || calls.Load() != 0 {
		t.Fatal("audit receiver made control request")
	}
	if err = s.ConfigureControl(ctx, elliptic.Marshal(elliptic.P256(), key.X, key.Y)); err != nil {
		t.Fatal(err)
	}
	state, _ := s.Status(ctx)
	for i := 1; i <= 151; i++ {
		id := fmt.Sprintf("%032x", i)
		grants = append(grants, hooks.ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: id, Nonce: id, Revision: "1", Decision: "allow", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(4 * time.Minute).Unix()), Scope: hooks.ToolScope{Device: "device", Stream: state.Stream, Receiver: state.ReceiverInstance, User: "501", Agent: "codex", Session: "session", Turn: "turn", Call: id, Tool: "Bash", InputDigest: strings.Repeat("a", 64), Attempt: id, Rule: "default", PolicyRevision: "1", ExecutionPoint: "plugin_pre_tool"}})
	}
	for i := 0; i < 8; i++ {
		code, err := syncer.Refresh(ctx, c, s)
		want := "aidr_hook_control_scanning"
		if i == 7 {
			want = "aidr_hook_control_synced"
		}
		if err != nil || code != want {
			t.Fatalf("page %d: %s %v", i, code, err)
		}
	}
	last := grants[150]
	if err = s.ConsumeGrant(ctx, last.ID, last.Scope, "1", now); err != nil {
		t.Fatal("last page missing", err)
	}
	phase.Store(1)
	if code, err := syncer.Refresh(ctx, c, s); err != nil || code != "aidr_hook_control_scanning" {
		t.Fatal(code, err)
	}
	if s.ConsumeGrant(ctx, grants[0].ID, grants[0].Scope, "1", now) == nil {
		t.Fatal("revocation not refreshed")
	}
	before := syncer.after
	for _, tc := range []struct {
		phase int32
		code  string
	}{{2, "aidr_hook_control_cached"}, {3, "aidr_hook_control_policy_rejected"}, {4, "aidr_hook_control_cursor_invalid"}} {
		phase.Store(tc.phase)
		if code, err := syncer.Refresh(ctx, c, s); err != nil || code != tc.code || syncer.after != before {
			t.Fatal("failed page advanced", code, err)
		}
	}
	if d := s.EvaluateTool(hooks.Event{Agent: "codex", Tool: "Bash"}, now); d.Decision != "ask" || d.Revision != "1" {
		t.Fatal("offline cache corrupted")
	}
	if d := s.EvaluateTool(hooks.Event{}, now.Add(2*time.Hour)); d.Decision != "deny" {
		t.Fatal("expired cache allowed")
	}
}
