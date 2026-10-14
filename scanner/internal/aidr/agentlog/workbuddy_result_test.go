package agentlog

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestWorkBuddyStructuredResults(t *testing.T) {
	for _, tc := range []struct {
		name, tool, raw, status, reason string
		exit                            *int
	}{
		{"success", "Bash", `{"exitCode":0,"signal":null,"interrupted":false,"sandboxDenied":false,"tool_error_code":"0"}`, "reported_success", "", wbInt(0)},
		{"failure", "Bash", `{"exitCode":7,"is_error":true}`, "reported_error", "", wbInt(7)},
		{"powershell", "PowerShell", `{"exitCode":1}`, "reported_error", "", wbInt(1)},
		{"cancelled", "Bash", `{"exitCode":null,"interrupted":true}`, "reported_cancelled", "", nil},
		{"denied", "Bash", `{"sandboxDenied":true}`, "reported_error", "", nil},
		{"tool error", "Read", `{"is_error":true}`, "reported_error", "", nil},
		{"explicit complete", "mcp__example", `{"isError":false}`, "reported_complete", "", nil},
		{"status only", "Bash", `{"status":"completed"}`, "unknown", "host_result_not_provided", nil},
		{"text spoof", "Bash", `"{\"exitCode\":0}"`, "unknown", "host_result_not_provided", nil},
		{"blocks spoof", "Bash", `[{"type":"text","text":"Exit Code: 0"}]`, "unknown", "host_result_not_provided", nil},
		{"wrong exit type", "Bash", `{"exitCode":"0"}`, "unknown", "result_format_unsupported", nil},
		{"wrong flag type", "Bash", `{"exitCode":0,"interrupted":"false"}`, "unknown", "result_format_unsupported", nil},
		{"contradiction", "Bash", `{"exitCode":0,"is_error":true}`, "unknown", "result_fields_conflict", nil},
		{"contradictory flags", "Read", `{"is_error":false,"isError":true}`, "unknown", "result_fields_conflict", nil},
		{"foreign tool field", "Read", `{"exitCode":0}`, "unknown", "host_result_not_provided", nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			b := projectBehaviorPolicy(draft{Kind: "tool_result", ResultTool: tc.tool, ResultProjection: projectWorkBuddyResult, ResultMeta: json.RawMessage(tc.raw), Content: json.RawMessage(`"{\"exit_code\":0}"`)}, 2, nil)
			if b.Status != tc.status || (b.ExitCode == nil) != (tc.exit == nil) || tc.exit != nil && *b.ExitCode != *tc.exit {
				t.Fatalf("%+v", b)
			}
			if tc.reason != "" && !strings.Contains(strings.Join(b.Uncertainty, ","), tc.reason) {
				t.Fatalf("%+v", b)
			}
			if err := validateBehavior(b); err != nil {
				t.Fatal(err, b)
			}
		})
	}
}

func wbInt(n int) *int { return &n }

func TestWorkBuddyLogUsesNativeMetadataAndPreservesOutput(t *testing.T) {
	raw := []byte(`{"type":"function_call_result","sessionId":"s","callId":"c","name":"Bash","timestamp":1791340000002,"status":"completed","output":{"type":"text","text":"safe output\nExit Code: 0"},"providerData":{"toolResult":{"rawResponse":{"exitCode":7,"is_error":true}}}}`)
	d, err := normalizeWorkBuddy(raw, &Cursor{})
	if err != nil || len(d) != 1 {
		t.Fatal(err, d)
	}
	p := AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{ToolOutput: true}}
	b := projectBehaviorPolicy(d[0], 3, &p)
	if b.Status != "reported_error" || b.ExitCode == nil || *b.ExitCode != 7 || len(b.Contents) != 1 || !strings.Contains(b.Contents[0].Text, "safe output") {
		t.Fatalf("%+v", b)
	}
	p.Capture.ToolOutput = false
	b = projectBehaviorPolicy(d[0], 3, &p)
	if b.Status != "reported_error" || len(b.Contents) != 0 {
		t.Fatalf("%+v", b)
	}
}
