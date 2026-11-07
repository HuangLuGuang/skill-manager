package hooks

import (
	"context"
	"encoding/json"
	"testing"
	"time"
)

func TestUnresolvedCommandUsesDefaultAndPreservesNativeMatches(t *testing.T) {
	for _, fallback := range []string{"allow", "deny", "ask"} {
		p := ToolPolicy{Revision: "7", Default: fallback, Rules: []ToolRule{{ID: "delete", Agent: "*", Tool: "*", Decision: "deny", Command: &CommandCondition{Executable: "rm"}}}}
		for _, command := range []string{"rg word src/*.go 2>/dev/null", "rm \"$TARGET\"", "echo ok"} {
			e := Event{Agent: "codex", Tool: "Bash", Kind: "tool.pre"}
			raw, _ := json.Marshal(map[string]any{"tool_input": map[string]string{"command": command}})
			e.CommandMatch = p.observeCommand(e, raw)
			d := p.Evaluate(e, time.Now())
			if d.Decision != fallback || d.Rule != "default" || len(d.Matched) != 0 {
				t.Fatalf("%s: %+v", command, d)
			}
		}
		e := Event{Agent: "codex", Tool: "Bash", CommandMatch: &CommandObservation{Revision: "7", Unresolved: []string{"delete"}}}
		p.Rules = append(p.Rules, ToolRule{ID: "shell", Agent: "*", Tool: "Bash", Decision: "deny"})
		if d := p.Evaluate(e, time.Now()); d.Decision != "deny" || d.Rule != "shell" {
			t.Fatal(d)
		}
	}
}

func TestControlDecisionPersistedWithEvent(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 100)
	s.controlMode = "intercept"
	s.bridgeIntercept.Store(true)
	s.controlPolicy = &ToolPolicy{Revision: "7", Default: "allow", Rules: []ToolRule{{ID: "delete", Agent: "*", Tool: "*", Decision: "deny", Command: &CommandCondition{Executable: "rm"}}}}
	for i, tc := range []struct{ command, decision, rule string }{
		{"rm ./fixture", "deny", "delete"},
		{"rg word src/*.go 2>/dev/null", "allow", "default"},
	} {
		var input map[string]any
		_ = json.Unmarshal([]byte(storeInput), &input)
		input["tool_name"] = "Bash"
		input["tool_input"] = map[string]string{"command": tc.command}
		// Host-supplied control fields must never become receiver evidence.
		input["control_decision"] = map[string]string{"decision": "allow"}
		input["control_mode"] = "audit"
		raw, _ := json.Marshal(input)
		r, err := s.Receive(ctx, testID(i+1), "501", "codex", "PreToolUse", raw)
		if err != nil {
			t.Fatal(err)
		}
		d := r.Event.ControlDecision
		if d == nil || d.Decision != tc.decision || d.Rule != tc.rule || d.Revision != "7" || r.Event.ControlMode != "plugin_pre_tool" {
			t.Fatalf("%+v", d)
		}
		var saved []byte
		if err := s.db.QueryRow("SELECT payload FROM hook_events WHERE event_id=?", r.EventID).Scan(&saved); err != nil {
			t.Fatal(err)
		}
		var stored Record
		if err := json.Unmarshal(saved, &stored); err != nil {
			t.Fatal(err)
		}
		if stored.Event.ControlDecision == nil || stored.Event.ControlDecision.Decision != tc.decision {
			t.Fatal(string(saved))
		}
		// Retransmission retains the historical decision after a policy change.
		s.controlPolicy.Default = "deny"
		replay, err := s.Receive(ctx, r.EventID, "501", "codex", "PreToolUse", raw)
		if err != nil || replay.Event.ControlDecision.Decision != tc.decision {
			t.Fatal(replay, err)
		}
		s.controlPolicy.Default = "allow"
	}
	_ = s.SetControlMode("audit")
	r, err := s.Receive(ctx, testID(3), "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || r.Event.ControlDecision != nil || r.Event.ControlMode != "audit" {
		t.Fatal("audit must not report an interception", r, err)
	}
	_ = s.SetControlMode("intercept")
	replay, err := s.Receive(ctx, r.EventID, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || replay.Event.ControlMode != "audit" || replay.Event.ControlDecision != nil {
		t.Fatal("replay must preserve historical audit mode", replay, err)
	}
}

func TestWindowsWorkBuddyPowerShellCommandRules(t *testing.T) {
	policy := ToolPolicy{Revision: "5", Default: "allow", Rules: []ToolRule{
		{ID: "delete", Agent: "*", Tool: "*", Decision: "deny", Command: &CommandCondition{Executable: "rm"}},
		{ID: "review", Agent: "workbuddy", Tool: "*", Decision: "ask", Command: &CommandCondition{Executable: "Write-Output"}},
	}}
	for _, tc := range []struct{ command, decision, rule string }{
		{"rm -WhatIf -LiteralPath am-acceptance.txt", "deny", "delete"},
		{"Write-Output AM_WB_APPROVAL", "ask", "review"},
		{"Get-Date", "allow", "default"},
	} {
		event := Event{Agent: "workbuddy", Hook: "PreToolUse", Kind: "tool.pre", Tool: "PowerShell"}
		raw, err := json.Marshal(map[string]any{
			"hook_event_name": event.Hook, "session_id": "session", "tool_name": event.Tool,
			"tool_input": map[string]string{"command": tc.command},
		})
		if err != nil {
			t.Fatal(err)
		}
		event.CommandMatch = policy.observeCommand(event, raw)
		if result := policy.Evaluate(event, time.Now()); result.Decision != tc.decision || result.Rule != tc.rule {
			t.Fatalf("%s: %+v", tc.command, result)
		}
	}
}
