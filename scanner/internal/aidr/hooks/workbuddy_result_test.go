package hooks

import (
	"encoding/json"
	"strings"
	"testing"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestWorkBuddyNativeHookResultAndPolicy(t *testing.T) {
	p := agentlog.AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &agentlog.CaptureScope{ToolOutput: true}}
	for _, tc := range []struct {
		response, status string
		exit             *int
	}{
		{`{"exitCode":0,"interrupted":false,"sandboxDenied":false}`, "reported_success", newInt(0)},
		{`{"exitCode":7,"is_error":true,"error":"api_key=sk-anonymized123"}`, "reported_error", newInt(7)},
		{`{"exitCode":null,"interrupted":true}`, "reported_cancelled", nil},
		{`[{"type":"text","text":"{\"exitCode\":0}"}]`, "unknown", nil},
	} {
		raw := []byte(`{"hook_event_name":"PostToolUse","session_id":"s","tool_use_id":"c","tool_name":"Bash","tool_response":` + tc.response + `}`)
		e, err := Normalize("workbuddy", "PostToolUse", raw, p, []byte(strings.Repeat("k", 32)))
		if err != nil {
			t.Fatal(err)
		}
		b := e.Behavior
		if b.Status != tc.status || (b.ExitCode == nil) != (tc.exit == nil) || tc.exit != nil && *b.ExitCode != *tc.exit {
			t.Fatalf("%+v", b)
		}
		encoded, _ := json.Marshal(e)
		if strings.Contains(string(encoded), "sk-anonymized123") {
			t.Fatal("unredacted output")
		}
		if strings.Contains(tc.response, "error\"") && len(b.Contents) != 1 {
			t.Fatal("missing error body", b)
		}
		p.Capture.ToolOutput = false
		e, err = Normalize("workbuddy", "PostToolUse", raw, p, []byte(strings.Repeat("k", 32)))
		if err != nil || len(e.Behavior.Contents) != 0 || e.Behavior.Status != tc.status {
			t.Fatal(err, e)
		}
		p.Capture.ToolOutput = true
	}
}
