package agentlog

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestPromptRequestHasIndependentFragmentBudget(t *testing.T) {
	p := AuditPolicy{MessageSchema: 1, Version: "4", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true}}
	question := "请检查日志，结果是否正常？"
	context := "# Files mentioned by the user:\n" + strings.Repeat("/synthetic/context ", 100) + "\n## My request:\n"
	for _, field := range []string{"hook.prompt", "message.input"} {
		c := contentBuilder{policy: p}
		c.addPrompt(field, context+question)
		values, status := c.result(true)
		if status != "partial" || len(values) != 2 || values[0].Text != question || values[0].Truncated || !values[1].Truncated {
			t.Fatalf("request lost its budget: %#v", values)
		}
		if values[0].Field != field+".request" || values[1].Field != field+".context" || c.bytes > 2048 {
			t.Fatal("invalid field or total budget")
		}
		if err := validateContents(values, status, p); err != nil {
			t.Fatal(err)
		}
	}
	plain := "Please explain\n## My request:\nthis marker"
	values, _ := ProjectPrompt(plain, p)
	if len(values) != 1 || values[0].Text != plain {
		t.Fatal("ordinary input was split")
	}
	p.Capture.MaxFragmentBytes, p.Capture.MaxEventBytes = 256, 256
	values, status := ProjectPrompt(context+strings.Repeat("中", 200), p)
	if len(values) != 2 || !values[0].Truncated || !values[1].Truncated || status != "partial" {
		t.Fatal("missing truncation metadata")
	}
	if err := validateContents(values, status, p); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(context + question)
	m := projectMessage(draft{MessageRole: "user", MessagePhase: "unspecified", Content: raw}, p)
	if err := validateMessage(m, "user_message"); err != nil {
		t.Fatal(err)
	}
	values, _ = ProjectPrompt(context+"TOKEN=synthetic-secret-value", p)
	if strings.Contains(values[0].Text, "synthetic-secret-value") {
		t.Fatal("request bypassed redaction")
	}
	p.Capture.Prompt = false
	values, status = ProjectPrompt(context+question, p)
	if len(values) != 0 || status != "not_requested" {
		t.Fatal("disabled prompt captured")
	}
}
