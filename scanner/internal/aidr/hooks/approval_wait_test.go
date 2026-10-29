package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestConfiguredApprovalDeadlineAndWaitOnlyPolicyChange(t *testing.T) {
	ctx := context.Background()
	now := time.Now().Truncate(time.Second)
	s := openTestStore(t, storeDirectory(t), 100)
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	pub := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	if err := s.ConfigureControl(ctx, pub); err != nil {
		t.Fatal(err)
	}
	p := ToolPolicy{Schema: 4, Domain: "aidr.tool-policy/4", Device: "device-a", Revision: "1", Issued: fmt.Sprint(now.Unix()), Default: "ask", Rules: []ToolRule{}, ApprovalWaitSeconds: 180}
	if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err != nil {
		t.Fatal(err)
	}
	r, err := s.Receive(ctx, testID(1), "501", "trae-cn", "PreToolUse", []byte(`{"hook_event_name":"PreToolUse","session_id":"session","tool_use_id":"native-call","tool_name":"RunCommand","tool_input":{"command":"touch test"}}`))
	if err != nil {
		t.Fatal(err)
	}
	d, err := s.BeginApproval(ctx, r, now)
	if err != nil || d.Expires != now.Unix()+180 {
		t.Fatal(d, err)
	}
	pending, err := s.PendingApproval(ctx, now)
	if err != nil || pending.Expires != d.Expires {
		t.Fatal(pending, err)
	}
	again, err := s.BeginApproval(ctx, r, now.Add(65*time.Second))
	if err != nil || again.Expires != d.Expires {
		t.Fatal("retry extended deadline", again, err)
	}
	p.Revision = "2"
	p.ApprovalWaitSeconds = 300
	if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err != nil {
		t.Fatal(err)
	}
	if d, err := s.PollApproval(ctx, r.EventID, "501", false, now.Add(70*time.Second)); err != nil || d.Decision != "ask" {
		t.Fatal(d, err)
	}
	scope, _ := s.ScopeFor(r, "default", "1")
	id := strings.Repeat("a", 32)
	if err := s.BindApproval(ctx, r.EventID, id, scope); err != nil {
		t.Fatal(err)
	}
	g := ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: id, Nonce: strings.Repeat("b", 32), Revision: "1", Decision: "allow", Issued: fmt.Sprint(now.Add(70 * time.Second).Unix()), Expires: fmt.Sprint(d.Expires), Scope: scope}
	if err := s.ApplyGrant(ctx, signGrant(t, key, g), pub, now.Add(70*time.Second)); err != nil {
		t.Fatal(err)
	}
	if d, err := s.PollApproval(ctx, r.EventID, "501", false, now.Add(71*time.Second)); err != nil || d.Decision != "allow" {
		t.Fatal(d, err)
	}
	r.EventID = testID(2)
	if d, err := s.BeginApproval(ctx, r, now); err != nil || d.Expires != now.Unix()+300 {
		t.Fatal(d, err)
	}
	if d, err := s.PollApproval(ctx, r.EventID, "501", false, now.Add(300*time.Second)); err != nil || d.Code != "aidr_hook_approval_timeout" {
		t.Fatal(d, err)
	}
	for _, seconds := range []int{0, 29, 301} {
		p.ApprovalWaitSeconds = seconds
		p.Revision = "3"
		if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err == nil {
			t.Fatal("accepted invalid wait", seconds)
		}
	}
}
