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

func TestDoubaoTrajectoryCollection(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "conversation-1", "agents", "agent-1", "system", "trajectory.jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	lines := []string{
		`{"role":"assistant","tool_calls":[{"id":"read-1","function":{"name":"Read","arguments":{"file_path":"/tmp/public.txt"}}}]}`,
		`{"role":"tool","tool_call_id":"read-1","content":"password=SYNTHETIC_SECRET"}`,
		`{"role":"assistant","tool_calls":[{"id":"write-1","function":{"name":"Write","arguments":{"file_path":"/tmp/out.txt","content":"public text"}}},{"id":"shell-1","function":{"name":"Bash","arguments":"{\"command\":\"printf public\"}"}}]}`,
		`{"role":"tool","tool_call_id":"write-1","content":"File created successfully at: /tmp/out.txt"}`,
		`{"role":"tool","tool_call_id":"shell-1","content":"Command 'printf public' exited with code 0. stdout: public"}`,
		`{"role":"assistant","tool_calls":[{"id":"mcp-1","function":{"name":"execute_defer_tool","arguments":{"toolName":"mcp__local__probe","params":{}}}}]}`,
		`{"role":"tool","tool_call_id":"mcp-1","content":"{\"exit_code\":0}"}`,
	}
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := NewSource("doubaowork", root, path)
	if err != nil {
		t.Fatal(err)
	}
	p := AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{FileBody: true, CommandBody: true, ToolOutput: true}}
	budget := DefaultBudget()
	budget.Events = 2
	var cursor Cursor
	var events []Event
	for i := 0; i < 10; i++ {
		batch, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &p)
		if err != nil {
			t.Fatal(err)
		}
		encoded, _ := json.Marshal(batch.Cursor)
		if err := json.Unmarshal(encoded, &cursor); err != nil {
			t.Fatal(err)
		}
		events = append(events, batch.Events...)
		if len(batch.Events) == 0 {
			break
		}
	}
	if len(events) != 8 {
		t.Fatalf("events: %d", len(events))
	}
	calls := map[string]Event{}
	for _, e := range events {
		if err := ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
		if e.SessionID != "conversation-1" || e.ObservedAtSource != "collection" {
			t.Fatalf("identity/time: %+v", e)
		}
		if e.Kind == "tool_call" {
			calls[e.CallID] = e
		} else {
			if calls[e.CallID].LogicalCallID != e.LogicalCallID || calls[e.CallID].Tool != e.Tool {
				t.Fatalf("unpaired: %+v", e)
			}
			if e.Behavior.Status != "unknown" {
				t.Fatal("untrusted result declared success")
			}
		}
	}
	if calls["mcp-1"].Tool != "mcp__local__probe" || calls["read-1"].Behavior.Category != "file_read" || calls["write-1"].Behavior.Category != "file_write" || calls["shell-1"].Behavior.Category != "command" {
		t.Fatal("classification")
	}
	encoded, _ := json.Marshal(events)
	if strings.Contains(string(encoded), "SYNTHETIC_SECRET") {
		t.Fatal("secret leaked")
	}
	replay, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(replay.Events) != len(events) {
		t.Fatal("replay", err)
	}
	for i, e := range replay.Events {
		if e.LogicalEventID != events[i].LogicalEventID {
			t.Fatal("unstable replay")
		}
	}
	if SourceFile("doubaowork", root, filepath.Join(root, "other.jsonl")) {
		t.Fatal("unrelated source accepted")
	}
}
