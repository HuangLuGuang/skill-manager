package hooks

import "testing"

func TestQoderRequestSetIdentityAndModel(t *testing.T) {
	for _, tc := range []struct{ hook, fields string }{
		{"UserPromptSubmit", `"request_set_id":"round-1","prompt_id":"different","prompt":"hello"`},
		{"Stop", `"parent_request_set_id":"round-1"`},
		{"PreToolUse", `"request_set_id":"round-1","tool_name":"Bash","tool_use_id":"call","tool_input":{"command":"true"}`},
	} {
		e := normalize(t, "qoder-hooks", tc.hook, `{"hook_event_name":"`+tc.hook+`","session_id":"session","model":"Auto",`+tc.fields+`}`, true)
		if e.Turn != "round-1" || e.Context == nil || e.Context.Model != "Auto" {
			t.Fatal(e)
		}
	}
	e := normalize(t, "qoder-hooks", "PreToolUse", `{"hook_event_name":"PreToolUse","session_id":"s","tool_name":"Bash","tool_input":{}}`, true)
	if e.Turn != "" {
		t.Fatal("invented native turn")
	}
}
