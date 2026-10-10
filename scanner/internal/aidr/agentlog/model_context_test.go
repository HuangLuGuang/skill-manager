package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestLogModelContextTurnIsolationAndNegotiation(t *testing.T) {
	lines := codexRecord("session_meta", `{"id":"session-a","cli_version":"0.160.1","model_provider":"openai"}`) +
		codexRecord("turn_context", `{"turn_id":"turn-a","model":"model-a","effort":"high","summary":"detailed","api_key":"not-collected"}`) +
		codexRecord("response_item", `{"type":"function_call","call_id":"call-a","name":"exec","arguments":"{}"}`) +
		codexRecord("turn_context", `{"turn_id":"turn-b","model":"model-b"}`) +
		codexRecord("response_item", `{"type":"function_call_output","call_id":"call-a","output":"done"}`) +
		codexRecord("response_item", `{"type":"message","id":"reply-b","role":"assistant","content":[{"type":"output_text","text":"done"}]}`) +
		codexRecord("event_msg", `{"type":"task_started","turn_id":"turn-c"}`) +
		codexRecord("response_item", `{"type":"function_call","call_id":"call-c","name":"exec","arguments":"{}"}`)
	s := source(t, "codex", lines)
	p := AuditPolicy{ModelContextSchema: 1, MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{}}
	b, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(b.Events) != 4 {
		t.Fatalf("events %d err %v", len(b.Events), err)
	}
	if m := b.Events[0].ModelContext; m == nil || m.Model != "model-a" || m.Provider != "openai" || m.ReasoningEffort != "high" {
		t.Fatalf("model %+v", m)
	}
	if b.Events[1].ModelContext != nil || b.Events[3].ModelContext != nil {
		t.Fatal("inherited another turn's model")
	}
	if m := b.Events[2].ModelContext; m == nil || m.Model != "model-b" || m.ReasoningEffort != "" {
		t.Fatalf("model %+v", m)
	}
	for _, e := range b.Events {
		if err := ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
	}
	encoded, _ := json.Marshal(b.Events)
	if strings.Contains(string(encoded), "not-collected") {
		t.Fatal("collected unknown configuration")
	}
	p.ModelContextSchema = 0
	legacy, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range legacy.Events {
		if e.ModelContext != nil {
			t.Fatal("old server received model metadata")
		}
	}
}

func TestModelContextPersistedCursorAndProviderUpgrade(t *testing.T) {
	s := source(t, "codex", codexRecord("session_meta", `{"id":"s","cli_version":"0.160.1","model_provider":"local-provider"}`))
	f, err := os.Open(s.Path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	c := Cursor{Session: "s", Offset: 1}
	restoreModelProvider(f, &c)
	if c.ModelProvider != "local-provider" || c.Offset != 1 {
		t.Fatalf("cursor %+v", c)
	}
	attachModelContext("codex", []byte(codexRecord("turn_context", `{"turn_id":"t","model":"model-a","effort":"medium"}`)), &c, nil)
	raw, _ := json.Marshal(c)
	var restored Cursor
	json.Unmarshal(raw, &restored)
	d := []draft{{Turn: "t"}}
	attachModelContext("codex", []byte(`{"type":"response_item"}`), &restored, d)
	if d[0].ModelContext == nil || d[0].ModelContext.Provider != "local-provider" {
		t.Fatal("lost persisted model")
	}
	wrong := Cursor{Session: "other", Offset: 1}
	restoreModelProvider(f, &wrong)
	if wrong.ModelProvider != "" {
		t.Fatal("provider crossed session identity")
	}
	attachModelContext("codex", []byte(`{"type":"turn_context","payload":{"turn_id":"t","model":123}}`), &restored, nil)
	if restored.ModelContext != nil {
		t.Fatal("malformed model retained previous settings")
	}
	invalidateContext(&restored)
	if restored.ModelContext != nil || restored.ModelProvider != "" {
		t.Fatal("stale context after invalidation")
	}
}

func TestProductLogModelFields(t *testing.T) {
	for _, tc := range []struct{ agent, raw, model string }{
		{"claude", `{"type":"assistant","message":{"model":"claude-example"}}`, "claude-example"},
		{"qoder-cli", `{"type":"assistant","message":{"model":"custom/model-a"}}`, "custom/model-a"},
		{"workbuddy", `{"type":"function_call","providerData":{"model":"model-w","requestModelId":"not-collected"}}`, "model-w"},
		{"claude", `{"type":"user","message":{"model":"model-a"}}`, ""},
		{"claude", `{"type":"assistant","message":{"model":"<synthetic>"}}`, ""},
	} {
		d := []draft{{}}
		c := Cursor{Session: "s"}
		attachModelContext(tc.agent, []byte(tc.raw), &c, d)
		if tc.model == "" {
			if d[0].ModelContext != nil {
				t.Fatal("unexpected model")
			}
			continue
		}
		if d[0].ModelContext == nil || d[0].ModelContext.Model != tc.model || d[0].ModelContext.Provider != "" {
			t.Fatalf("%s %+v", tc.agent, d)
		}
	}
}
