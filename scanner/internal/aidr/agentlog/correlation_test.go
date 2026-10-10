package agentlog

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
)

func codexRecord(kind, payload string) string {
	return fmt.Sprintf(`{"timestamp":%q,"type":%q,"payload":%s}`+"\n", stamp, kind, payload)
}
func parallelLog(n int, results bool) string {
	var s strings.Builder
	s.WriteString(codexRecord("session_meta", `{"id":"parallel","cli_version":"0.160.0"}`))
	s.WriteString(codexRecord("turn_context", `{"turn_id":"first"}`))
	for i := 0; i < n; i++ {
		s.WriteString(codexRecord("response_item", fmt.Sprintf(`{"type":"function_call","call_id":"c%d","name":"exec_command","arguments":{"cmd":"true"}}`, i)))
	}
	if results {
		s.WriteString(codexRecord("turn_context", `{"turn_id":"second"}`))
		for i := n - 1; i >= 0; i-- {
			s.WriteString(codexRecord("response_item", fmt.Sprintf(`{"type":"function_call_output","call_id":"c%d","output":"ok"}`, i)))
		}
	}
	return s.String()
}
func TestParallelCallsResumeAcrossTurnAndRestart(t *testing.T) {
	for _, n := range []int{16, 17, 100} {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			content := parallelLog(n, true)
			prefix := parallelLog(n, false)
			s := source(t, "codex", prefix)
			calls := read(t, s, Cursor{})
			if len(calls.Events) != n || calls.Coverage.Status != "complete" {
				t.Fatal(calls.Coverage, len(calls.Events))
			}
			encoded, _ := json.Marshal(calls.Cursor)
			var restored Cursor
			if err := json.Unmarshal(encoded, &restored); err != nil {
				t.Fatal(err)
			}
			if err := ValidateCursor(restored, s); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(s.Path, []byte(content), 0600); err != nil {
				t.Fatal(err)
			}
			results := read(t, s, restored)
			if len(results.Events) != n || results.Coverage.Status != "complete" {
				t.Fatal(results.Coverage, len(results.Events))
			}
			byCall := map[string]Event{}
			for _, e := range calls.Events {
				byCall[e.CallID] = e
			}
			for _, e := range results.Events {
				if e.TurnID != "first" || e.LogicalCallID != byCall[e.CallID].LogicalCallID || e.Behavior == nil {
					t.Fatalf("lost correlation: %+v", e)
				}
			}
			if len(results.Cursor.CallTurns) > completedToolBindings {
				t.Fatal("completed cache not reclaimed")
			}
		})
	}
}
func TestPendingCapacityAndCompletedReclamation(t *testing.T) {
	var c Cursor
	for i := 0; i < maxToolBindings; i++ {
		rememberTool(&c, fmt.Sprint(i), "t", "Bash", json.RawMessage(`{}`))
	}
	rememberTool(&c, "overflow", "t", "Bash", json.RawMessage(`{}`))
	if len(c.CallTurns) != maxToolBindings || len(c.Gaps) != 1 || c.Gaps[0] != "aidr_log_call_capacity" {
		t.Fatal(c)
	}
	turn, tool := completeTool(&c, "0", "")
	if turn != "t" || tool != "Bash" {
		t.Fatal("old pending evicted")
	}
	rememberTool(&c, "new", "t", "Bash", json.RawMessage(`{}`))
	if boundTool(&c, "new") != "Bash" || len(c.CallTurns) != maxToolBindings {
		t.Fatal("completed entry not reclaimed")
	}
	s := source(t, "codex", parallelLog(maxToolBindings+1, false))
	// The event budget deliberately splits the capacity boundary across reads.
	b := read(t, s, Cursor{})
	b = read(t, s, b.Cursor)
	if b.Coverage.Status != "partial" || !has(b, "aidr_log_call_capacity") {
		t.Fatal(b.Coverage)
	}
	encoded, _ := json.Marshal(b.Cursor)
	var restored Cursor
	json.Unmarshal(encoded, &restored)
	next := read(t, s, restored)
	if !has(next, "aidr_log_call_capacity") {
		t.Fatal("capacity gap vanished on restart")
	}
}
func TestDuplicateConflictAndOutOfOrderCorrelation(t *testing.T) {
	var c Cursor
	rememberTool(&c, "same", "one", "Bash", json.RawMessage(`{"cmd":"true"}`))
	rememberTool(&c, "same", "one", "Bash", json.RawMessage(`{"cmd":"true"}`))
	if len(c.CallTurns) != 1 || len(c.Gaps) != 0 {
		t.Fatal(c)
	}
	completeTool(&c, "same", "")
	rememberTool(&c, "same", "one", "Bash", json.RawMessage(`{"cmd":"false"}`))
	if _, tool := completeTool(&c, "same", ""); tool != "" || len(c.Gaps) == 0 {
		t.Fatal("conflict silently linked")
	}
	var unknown Cursor
	if turn, tool := completeTool(&unknown, "early", "explicit"); turn != "explicit" || tool != "" || unknown.Gaps[0] != "aidr_log_call_unresolved" {
		t.Fatal(unknown)
	}
	rememberTool(&unknown, "early", "explicit", "Bash", json.RawMessage(`{}`))
	if turn, tool := completeTool(&unknown, "early", ""); turn != "explicit" || tool != "Bash" {
		t.Fatal("later known call cannot link")
	}
	var crossed Cursor
	rememberTool(&crossed, "reuse", "one", "Bash", nil)
	rememberTool(&crossed, "reuse", "two", "Bash", nil)
	if _, tool := completeTool(&crossed, "reuse", ""); tool != "" {
		t.Fatal("cross-turn conflict linked")
	}
}

func TestCompletedResultReplayKeepsLogicalIdentity(t *testing.T) {
	content := parallelLog(17, true)
	s := source(t, "codex", content)
	first := read(t, s, Cursor{})
	replay := codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`)
	f, err := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(replay)
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(first.Cursor)
	var restored Cursor
	json.Unmarshal(encoded, &restored)
	next := read(t, s, restored)
	if len(next.Events) != 1 || next.Coverage.Status != "complete" {
		t.Fatal(next.Coverage)
	}
	original := first.Events[len(first.Events)-1]
	repeated := next.Events[0]
	if original.LogicalEventID != repeated.LogicalEventID || original.LogicalCallID != repeated.LogicalCallID || original.EventID == repeated.EventID {
		t.Fatal("completion/restart changed logical replay identity")
	}
}
