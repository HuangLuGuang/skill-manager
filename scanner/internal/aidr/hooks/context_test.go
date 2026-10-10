package hooks

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestHostContextKeepsExplicitMetadataAndDistinctWorkspaceRoots(t *testing.T) {
	e := normalize(t, "claude", "SessionStart", `{"hook_event_name":"SessionStart","session_id":"s","model":"claude-test","cwd":"/tmp/project","transcript_path":"/private/omitted"}`, true)
	if e.Context == nil || e.Context.Model != "claude-test" || e.Context.Cwd != "/tmp/project" {
		t.Fatal(e.Context)
	}
	e = normalize(t, "cursor", "beforeSubmitPrompt", `{"hook_event_name":"beforeSubmitPrompt","conversation_id":"s","generation_id":"t","model":"legacy","model_id":"selected-model","workspace_roots":["/tmp/a","/tmp/b"]}`, true)
	if e.Context.Model != "selected-model" || e.Context.Cwd != "" || len(e.Context.WorkspaceRoots) != 2 {
		t.Fatal(e.Context)
	}
	e = normalize(t, "codex", "UserPromptSubmit", `{"hook_event_name":"UserPromptSubmit","session_id":"s"}`, true)
	if e.Context != nil {
		t.Fatal("invented missing context")
	}
	e = normalize(t, "codex", "UserPromptSubmit", `{"hook_event_name":"UserPromptSubmit","session_id":"s","model":{"name":"unverified"},"cwd":"/tmp"}`, true)
	if e.Context.Model != "" || e.Context.Cwd != "/tmp" {
		t.Fatal("guessed model shape")
	}
}

func TestHostContextUsesExistingRedactionAndByteBudgets(t *testing.T) {
	raw, _ := json.Marshal(map[string]any{"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/tmp/api_key=synthetic-secret", "model": strings.Repeat("模", 100)})
	e := normalize(t, "codex", "UserPromptSubmit", string(raw), true)
	if !e.Context.Redacted || !e.Context.Truncated || strings.Contains(e.Context.Cwd, "synthetic-secret") || len(e.Context.Model) > 256 {
		t.Fatal(e.Context)
	}
	e = normalize(t, "codex", "UserPromptSubmit", string(raw), false)
	if !strings.Contains(e.Context.Cwd, "synthetic-secret") {
		t.Fatal("overrode policy")
	}
}
