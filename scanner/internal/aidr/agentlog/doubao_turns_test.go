package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDoubaoNativeTurnIDs(t *testing.T) {
	index := newDoubaoTurnIndex()
	legacy := `[1:2:1021/100000:INFO:FRONTEND(0)] [neotix] [office-api-logger] "[webview][unknown][flow-web][logifier-report]: {"eventName":"on_message_receiving_start","meta":{"chat_session_id":"agent-a","send_message_id":"message-a"}}", source: (0)`
	modern := `[1:2:1021/100000:INFO:FRONTEND(0)] [neotix] [desktop.office.local-slides] "[local-office:slide-tea] {"eventName":"flow_doc_slide_tools_bug_trace_dev","params":{"action":"local_office_canvas_lifecycle_emit_finished","stage":"start","success":true,"session_id":"agent-b","message_id":"message-b"}}", source: (0)`
	runtime := `[1:2:1021/100000:INFO:aha/saman_sandbox_shell_api_metrics.cc(113)] [sandbox] shell api call, api_name=sandbox.bash.run, status=enter, sandbox_log_id={"conversation_id":"session","agent_id":"agent-a","tcid":"call-a"}, result=<none>`
	for _, line := range []string{legacy, modern, runtime} {
		index.consume(line)
	}
	if index.requests["agent-a"] != "message-a" || index.requests["agent-b"] != "message-b" || index.calls["session:call-a"] != "agent-a" {
		t.Fatal(index)
	}
	index.consume(strings.ReplaceAll(modern, `"stage":"start"`, `"stage":"end"`))
	index.consume(strings.ReplaceAll(legacy, "message-a", "message-conflict"))
	if index.requests["agent-a"] != "" {
		t.Fatal("conflicting message selected")
	}
	index.consume(legacy)
	if index.requests["agent-a"] != "" {
		t.Fatal("conflict forgotten")
	}
	index.consume(strings.ReplaceAll(runtime, "agent-a", "agent-b"))
	if index.calls["session:call-a"] != "" {
		t.Fatal("conflicting tool selected")
	}
	spoof := newDoubaoTurnIndex()
	spoof.consume("tool stdout: " + runtime)
	spoof.consume("tool stdout: " + modern)
	spoof.consume(`tool stdout: sandbox_log_id={"conversation_id":"session","agent_id":"agent-a","tcid":"call-a"}`)
	if len(spoof.calls) != 0 || len(spoof.requests) != 0 {
		t.Fatal("tool output used as identity")
	}
}

// Opt-in read-only check against a dedicated, non-sensitive test conversation.
func TestDoubaoLiveTurnLinks(t *testing.T) {
	root, session := os.Getenv("DOUBAO_TEST_ROOT"), os.Getenv("DOUBAO_TEST_SESSION")
	if root == "" || session == "" {
		t.Skip("dedicated local test conversation not specified")
	}
	turns, _ := doubaoTurns(context.Background(), root, session)
	paths, err := filepath.Glob(filepath.Join(root, session, "agents", "*", "system", "trajectory.jsonl"))
	if err != nil || len(paths) != 1 {
		t.Fatal("test trajectory missing")
	}
	s, err := NewSource("doubaowork", root, paths[0])
	if err != nil {
		t.Fatal(err)
	}
	p := AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{}}
	b, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, l := range b.TurnLinks {
		seen[l.TurnID] = true
	}
	if len(turns) != 2 || len(seen) != 2 || len(b.TurnLinks) != 4 {
		t.Fatalf("calls=%d turns=%d links=%d", len(turns), len(seen), len(b.TurnLinks))
	}
	metadata, _ := json.Marshal(turns)
	t.Log("verified native call-to-message mapping:", string(metadata))
}
