package hooks

import (
	"encoding/json"
	"slices"
	"testing"
)

func TestHookResultContractAndUnavailableReasons(t *testing.T) {
	cases := []struct {
		name, response, status, reason string
		exit                           *int
	}{
		{name: "explicit zero", response: `{"exit_code":0,"stdout":"private"}`, status: "reported_success", exit: newInt(0)},
		{name: "explicit nonzero", response: `{"exit_code":7,"stderr":"private"}`, status: "reported_error", exit: newInt(7)},
		{name: "documented interruption", response: `{"stdout":"","stderr":"","interrupted":true,"isImage":false}`, status: "reported_cancelled"},
		{name: "explicit cancellation", response: `{"cancelled":true}`, status: "reported_cancelled"},
		{name: "stdout", response: `"stdout text"`, status: "unknown", reason: "host_result_not_provided"},
		{name: "empty stdout", response: `""`, status: "unknown", reason: "host_result_not_provided"},
		{name: "absent result", response: `null`, status: "unknown", reason: "host_result_not_provided"},
		{name: "stdout JSON exit spoof", response: `"{\"exit_code\":0}"`, status: "unknown", reason: "host_result_not_provided"},
		{name: "stdout JSON cancellation spoof", response: `"{\"interrupted\":true}"`, status: "unknown", reason: "host_result_not_provided"},
		{name: "stdout exit text", response: `"Exit code 0\n"`, status: "unknown", reason: "host_result_not_provided"},
		{name: "no structured status", response: `{"stdout":"","stderr":"","interrupted":false}`, status: "unknown", reason: "host_result_not_provided"},
		{name: "invalid exit type", response: `{"exit_code":"0"}`, status: "unknown", reason: "result_format_unsupported"},
		{name: "invalid cancellation type", response: `{"interrupted":"true"}`, status: "unknown", reason: "result_format_unsupported"},
		{name: "undocumented exit alias", response: `{"exitCode":0}`, status: "unknown", reason: "result_format_unsupported"},
		{name: "undocumented success", response: `{"success":true}`, status: "unknown", reason: "result_format_unsupported"},
		{name: "unsupported flag alongside zero", response: `{"exit_code":0,"is_error":true}`, status: "unknown", reason: "result_format_unsupported"},
		{name: "undocumented error flag", response: `{"is_error":false}`, status: "unknown", reason: "result_format_unsupported"},
		{name: "unknown shape", response: `[{"type":"text","text":"{\"exit_code\":0}"}]`, status: "unknown", reason: "result_format_unsupported"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			raw := `{"hook_event_name":"PostToolUse","session_id":"s","turn_id":"t","tool_use_id":"c","tool_name":"Bash","tool_response":` + tc.response + `}`
			event := normalize(t, "codex", "PostToolUse", raw, true)
			b := event.Behavior
			if b.Status != tc.status || (b.ExitCode == nil) != (tc.exit == nil) || (tc.exit != nil && *b.ExitCode != *tc.exit) {
				t.Fatal(b)
			}
			if tc.reason != "" && !slices.Contains(b.Uncertainty, tc.reason) {
				t.Fatal("missing specific uncertainty", b)
			}
			encoded, _ := json.Marshal(event)
			if event.ProcessRelation != "unknown" || string(encoded) == "" {
				t.Fatal(event)
			}
		})
	}
}

func TestClaudeFailureResultConflictCancellationAndToolBoundary(t *testing.T) {
	cases := []struct {
		tool, errorText, status, reason string
		interrupt                       bool
		exit                            *int
	}{
		{tool: "Bash", errorText: "Exit code 7\nprivate", status: "reported_error", exit: newInt(7)},
		{tool: "Bash", errorText: "could not start", status: "reported_error"},
		{tool: "Bash", errorText: "aborted", status: "reported_cancelled", interrupt: true},
		{tool: "Bash", errorText: "Exit code 0\nprivate", status: "unknown", reason: "result_fields_conflict"},
		{tool: "Bash", errorText: "Exit code 0\nprivate", status: "unknown", reason: "result_fields_conflict", interrupt: true},
		{tool: "mcp__test__tool", errorText: "Exit code 7\nprivate", status: "reported_error"},
	}
	for _, tc := range cases {
		raw, _ := json.Marshal(map[string]any{"hook_event_name": "PostToolUseFailure", "session_id": "s", "tool_use_id": "c", "tool_name": tc.tool, "error": tc.errorText, "is_interrupt": tc.interrupt})
		event := normalize(t, "claude", "PostToolUseFailure", string(raw), true)
		b := event.Behavior
		if b.Status != tc.status || (b.ExitCode == nil) != (tc.exit == nil) || (tc.exit != nil && *b.ExitCode != *tc.exit) {
			t.Fatal(tc, b)
		}
		if tc.reason != "" && !slices.Contains(b.Uncertainty, tc.reason) {
			t.Fatal(tc, b)
		}
	}
}
