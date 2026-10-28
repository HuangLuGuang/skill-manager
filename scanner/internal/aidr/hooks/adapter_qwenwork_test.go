package hooks

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestQwenWorkGrantScopeReplayAndRestart(t *testing.T) { testGrantExactScope(t, "qwenwork") }
func TestQwenWorkIndependentApprovalAttempts(t *testing.T) {
	testApprovalAttemptLifecycle(t, "qwenwork")
}

func TestQwenWorkCommandRuleUsesNativeExecutionDirectory(t *testing.T) {
	tool := "mcp__qw-builtin__mcp_workspace_bash"
	p := ToolPolicy{Revision: "1", Rules: []ToolRule{{ID: "guard", Agent: "qwenwork", Tool: tool, Decision: "deny", Command: &CommandCondition{Executable: "touch", PathPrefix: "/tmp/actual"}}}}
	e := Event{Agent: "qwenwork", Hook: "PreToolUse", Kind: "tool.pre", Tool: tool}
	o := p.observeCommand(e, []byte(`{"hook_event_name":"PreToolUse","session_id":"s","tool_use_id":"c","cwd":"/tmp/session","tool_name":"mcp__qw-builtin__mcp_workspace_bash","tool_input":{"command":"touch marker","dir_path":"/tmp/actual"}}`))
	if len(o.Matched) != 1 || o.Matched[0] != "guard" {
		t.Fatal("execution directory ignored", o)
	}
}

func TestQwenWorkNativeHookIdentity(t *testing.T) {
	raw, err := os.ReadFile("../agentlog/testdata/qwenwork-cn-1.4.0/hooks.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range bytes.Split(bytes.TrimSpace(raw), []byte("\n")) {
		var event struct {
			Event string `json:"hook_event_name"`
		}
		if err := json.Unmarshal(line, &event); err != nil {
			t.Fatal(err)
		}
		in, err := qwenWorkHookAdapter().Decode(event.Event, line)
		if err != nil {
			t.Fatal(err)
		}
		if IsPreTool("qwenwork", event.Event) && (in.Call == "" || in.Turn != "") {
			t.Fatal("native tool identity changed")
		}
		if event.Event == "UserPromptSubmit" && in.Turn == "" {
			t.Fatal("native request set lost")
		}
	}
}

func TestQwenWorkSettingsPreserveUserConfiguration(t *testing.T) {
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(home, ".qwenworkcn")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "settings.json")
	before := `{"custom":7,"hooks":{"PreToolUse":[{"matcher":"Read","hooks":[{"type":"command","command":"user-hook","timeout":9}]}]}}`
	if err := os.WriteFile(path, []byte(before), 0600); err != nil {
		t.Fatal(err)
	}
	for _, remove := range []bool{false, false, true, true} {
		if _, err := MergeSettingsHooks("qwenwork", home, "/tmp/client", "/tmp/connection", remove); err != nil {
			t.Fatal(err)
		}
	}
	var want, got any
	json.Unmarshal([]byte(before), &want)
	after, _ := os.ReadFile(path)
	json.Unmarshal(after, &got)
	w, _ := json.Marshal(want)
	g, _ := json.Marshal(got)
	if !bytes.Equal(w, g) {
		t.Fatalf("user settings changed: %s", after)
	}
}
