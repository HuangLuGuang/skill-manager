package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"fmt"
	"reflect"
	"testing"
	"time"
)

func TestSignedToolPolicyCacheConflictAndExplanation(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 10)
	now := time.Now()
	event := Event{Agent: "codex", Tool: "Bash"}
	if d := s.EvaluateTool(event, now); d.Code != "aidr_hook_audit_only" {
		t.Fatal("audit-only state not explicit")
	}
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	pub := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	if err := s.ConfigureControl(ctx, pub); err != nil {
		t.Fatal(err)
	}
	if d := s.EvaluateTool(event, now); d.Decision != "deny" || d.Code != "aidr_hook_policy_missing" {
		t.Fatal("missing configured policy allowed")
	}
	p := ToolPolicy{Schema: 1, Domain: "aidr.tool-policy/1", Device: "device-a", Revision: "1", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Hour).Unix()), Default: "deny", Rules: []ToolRule{{ID: "review", Agent: "codex", Tool: "Bash", Decision: "ask"}, {ID: "allow", Agent: "*", Tool: "*", Decision: "allow"}}}
	one := signGrant(t, key, p)
	if err := s.ApplyToolPolicy(ctx, one, now); err != nil {
		t.Fatal(err)
	}
	d := s.EvaluateTool(event, now)
	if d.Decision != "ask" || d.Rule != "review" || !reflect.DeepEqual(d.Matched, []string{"allow", "review"}) {
		t.Fatalf("wrong explanation %+v", d)
	}
	p.Default = "allow"
	if s.ApplyToolPolicy(ctx, signGrant(t, key, p), now) == nil {
		t.Fatal("equal-version rewrite accepted")
	}
	p.Revision = "2"
	p.Rules = append(p.Rules, ToolRule{ID: "deny", Agent: "codex", Tool: "Bash", Decision: "deny"})
	if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err != nil {
		t.Fatal(err)
	}
	if s.ApplyToolPolicy(ctx, one, now) == nil {
		t.Fatal("policy rollback accepted")
	}
	s.Close()
	s = openTestStore(t, dir, 10)
	if err := s.ConfigureControl(ctx, pub); err != nil {
		t.Fatal(err)
	}
	d = s.EvaluateTool(event, now)
	if d.Decision != "deny" || d.Rule != "deny" || d.Revision != "2" {
		t.Fatal("cached policy lost")
	}
	if d = s.EvaluateTool(event, now.Add(2*time.Hour)); d.Decision != "deny" || d.Code != "aidr_hook_policy_expired" {
		t.Fatal("expired policy allowed")
	}
	if err := s.SetControlMode("audit"); err != nil {
		t.Fatal(err)
	}
	if d = s.EvaluateTool(event, now.Add(2*time.Hour)); d.Decision != "allow" || s.BridgeControlMode() != "audit" {
		t.Fatal("audit mode enforced an expired deny policy", d)
	}
	if len(s.ControlKey()) != 65 {
		t.Fatal("audit mode removed signature trust")
	}
	if err := s.SetControlMode("intercept"); err != nil {
		t.Fatal(err)
	}
	if d = s.EvaluateTool(event, now); d.Decision != "deny" || d.Revision != "2" {
		t.Fatal("switch lost signed policy", d)
	}
	p.Revision = "3"
	p.Domain = "aidr.tool-grant/1"
	if s.ApplyToolPolicy(ctx, signGrant(t, key, p), now) == nil {
		t.Fatal("cross-domain policy accepted")
	}
}
