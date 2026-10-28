package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestApprovalAttemptIdentitySingleDeliveryAndLifecycle(t *testing.T) {
	for _, agent := range []string{"codex", "workbuddy", "codebuddy", "trae", "trae-cn"} {
		t.Run(agent, func(t *testing.T) { testApprovalAttemptLifecycle(t, agent) })
	}
}

func testApprovalAttemptLifecycle(t *testing.T, agent string) {
	ctx := context.Background()
	now := time.Now()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 100)
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	pub := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	if err := s.ConfigureControl(ctx, pub); err != nil {
		t.Fatal(err)
	}
	p := ToolPolicy{Schema: 2, Domain: "aidr.tool-policy/2", Device: "device-a", Revision: "1", Issued: fmt.Sprint(now.Unix()), Default: "ask", Rules: []ToolRule{}}
	if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err != nil {
		t.Fatal(err)
	}
	var records []Record
	for i := 1; i <= 5; i++ {
		raw := []byte(storeInput)
		if agent == "qwenwork" {
			raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"session","tool_use_id":"native-call","tool_name":"mcp__qw-builtin__mcp_workspace_bash","tool_input":{"command":"printf approved","dir_path":"/tmp"}}`)
		}
		if agent == "trae" || agent == "trae-cn" {
			raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"session","agent_id":"solo_agent","tool_use_id":"native-call","tool_name":"RunCommand","tool_input":{"command":"printf approved"}}`)
		}
		if agent == "codebuddy" {
			raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"session","generation_id":"turn","cwd":"/","tool_name":"Bash","tool_input":{"command":"printf approved"}}`)
		}
		r, err := s.Receive(ctx, testID(i), "501", agent, "PreToolUse", raw)
		if err != nil {
			t.Fatal(err)
		}
		d, err := s.BeginApproval(ctx, r, now)
		if err != nil || d.Decision != "ask" {
			t.Fatal(d, err)
		}
		records = append(records, r)
	}
	first, err := s.PendingApproval(ctx, now)
	if err != nil || first.Event != records[0].EventID {
		t.Fatal(first, err)
	}
	second, err := s.PendingApproval(ctx, now)
	if err != nil || second.Event == first.Event {
		t.Fatal("retry starved next attempt", err)
	}
	r := records[0]
	scope, _ := s.ScopeFor(r, "default", "1")
	id := strings.Repeat("a", 32)
	wrong := scope
	wrong.InputDigest = strings.Repeat("b", 64)
	if s.BindApproval(ctx, r.EventID, id, wrong) == nil {
		t.Fatal("response changed scope")
	}
	if err = s.BindApproval(ctx, r.EventID, id, scope); err != nil {
		t.Fatal(err)
	}
	grant := ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: id, Nonce: strings.Repeat("b", 32), Revision: "1", Decision: "allow", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Minute).Unix()), Scope: scope}
	if err = s.ApplyGrant(ctx, signGrant(t, key, grant), pub, now); err != nil {
		t.Fatal(err)
	}
	if d, err := s.PollApproval(ctx, r.EventID, "502", false, now); err != nil || d.Decision != "deny" {
		t.Fatal("wrong user permitted", d, err)
	}
	var wins atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			d, e := s.PollApproval(ctx, r.EventID, "501", false, now)
			if e != nil {
				t.Error(e)
			}
			if d.Decision == "allow" {
				wins.Add(1)
			}
		}()
	}
	wg.Wait()
	if wins.Load() != 1 {
		t.Fatal("permission delivered more than once", wins.Load())
	}
	report, err := s.PrepareAttemptReport(ctx)
	if err != nil || report == nil || report.Event != r.EventID {
		t.Fatal("terminal report missing", err)
	}
	if s.AcknowledgeAttemptReport(ctx, "other", scope.Stream, report.Event, report.Digest, true) == nil {
		t.Fatal("cross-device report ACK accepted")
	}
	if s.AcknowledgeAttemptReport(ctx, "device-a", scope.Stream, report.Event, strings.Repeat("0", 64), true) == nil {
		t.Fatal("wrong digest ACK accepted")
	}
	if d, err := s.BeginApproval(ctx, r, now); err != nil || d.Decision != "deny" {
		t.Fatal("retry recreated attempt")
	}
	if d, err := s.PollApproval(ctx, records[1].EventID, "501", true, now); err != nil || d.Code != "aidr_hook_approval_cancelled" {
		t.Fatal(d, err)
	}
	if d, err := s.PollApproval(ctx, records[2].EventID, "501", false, now.Add(time.Minute)); err != nil || d.Code != "aidr_hook_approval_timeout" {
		t.Fatal(d, err)
	}
	p.Revision = "2"
	p.Default = "deny"
	if err = s.ApplyToolPolicy(ctx, signGrant(t, key, p), now); err != nil {
		t.Fatal(err)
	}
	if d, err := s.PollApproval(ctx, records[3].EventID, "501", false, now); err != nil || d.Code != "aidr_hook_policy_changed" {
		t.Fatal(d, err)
	}
	s.Close()
	s = openTestStore(t, dir, 100)
	restored, err := s.PrepareAttemptReport(ctx)
	if err != nil || restored == nil || string(restored.Payload) != string(report.Payload) || restored.Digest != report.Digest {
		t.Fatal("restart changed frozen report", err)
	}
	if err = s.AcknowledgeAttemptReport(ctx, "device-a", scope.Stream, restored.Event, restored.Digest, true); err != nil {
		t.Fatal(err)
	}
	next, err := s.PrepareAttemptReport(ctx)
	if err != nil || next == nil || next.Event == restored.Event {
		t.Fatal("acknowledged report replayed", err)
	}
	if d, err := s.PollApproval(ctx, records[4].EventID, "501", false, now); err != nil || d.Code != "aidr_hook_receiver_restarted" {
		t.Fatal(d, err)
	}
}
