package agentlog

import (
	"encoding/json"
	"slices"
	"testing"
)

func TestStructuredLogResultConsistency(t *testing.T) {
	cases := []struct {
		content, outcome, status, reason string
		exit                             *int
	}{
		{content: `[{"type":"text","text":"{\"exit_code\":0}"},{"type":"text","text":"{\"exit_code\":0}"}]`, status: "reported_success", exit: ptr(0)},
		{content: `[{"type":"text","text":"{\"exit_code\":0}"},{"type":"text","text":"{\"exit_code\":7}"}]`, status: "unknown", reason: "result_fields_conflict"},
		{content: `{"exit_code":0}`, outcome: "error", status: "unknown", reason: "result_fields_conflict"},
		{content: `{"exit_code":7}`, outcome: "success", status: "unknown", reason: "result_fields_conflict"},
		{content: `{"exit_code":true}`, status: "unknown", reason: "result_format_unsupported"},
	}
	for _, tc := range cases {
		b := projectBehavior(draft{Kind: "tool_result", Content: json.RawMessage(tc.content), Outcome: tc.outcome})
		if b.Status != tc.status || (b.ExitCode == nil) != (tc.exit == nil) || (tc.exit != nil && *b.ExitCode != *tc.exit) {
			t.Fatal(tc, b)
		}
		if tc.reason != "" && !slices.Contains(b.Uncertainty, tc.reason) {
			t.Fatal(tc, b)
		}
		if err := validateBehavior(b); err != nil {
			t.Fatal(err)
		}
	}
}
