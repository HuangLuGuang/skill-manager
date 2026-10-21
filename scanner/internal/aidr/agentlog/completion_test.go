package agentlog

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestCodexCommandCompletionUpgradeAndReplay(t *testing.T) {
	data := codexRecord("session_meta", `{"id":"s","cli_version":"0.163.0"}`) +
		codexRecord("event_msg", `{"type":"item_completed","thread_id":"s","turn_id":"t","item":{"type":"ImageView","id":"image"}}`)
	cases := []struct{ status, code string }{{"completed", "0"}, {"failed", "143"}, {"failed", "null"}, {"completed", "null"}, {"failed", "0"}}
	for i, tc := range cases {
		data += codexRecord("event_msg", fmt.Sprintf(`{"type":"item_completed","thread_id":"s","turn_id":"t","item":{"type":"CommandExecution","id":"cmd%d","status":%q,"exit_code":%s,"command":"DO_NOT_CAPTURE","aggregated_output":"DO_NOT_CAPTURE"}}`, i, tc.status, tc.code))
	}
	data += codexRecord("event_msg", `{"type":"item_completed","thread_id":"s","turn_id":"t","item":{"type":"CommandExecution","id":"running","status":"inProgress","exit_code":null}}`)
	s := source(t, "codex", data)
	p := AuditPolicy{CompletionSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{ToolOutput: true}}
	first, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(first.Events) != 1 || first.Events[0].Tool != "view_image" {
		t.Fatal("v1 server received command metadata", err, first.Events)
	}
	p.CompletionSchema = 2
	cursor := first.Cursor
	oldRepair := first.Cursor
	cursor.ContextRepair = &oldRepair // A v1 replay checkpoint cannot skip the v2 history prefix.
	budget := DefaultBudget()
	budget.Events = 1
	seen := map[string]Event{}
	for n := 0; n < 20; n++ {
		b, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &p)
		if err != nil {
			t.Fatal(err)
		}
		for _, e := range b.Events {
			if err := ValidateEvent(e); err != nil {
				t.Fatal(err, e)
			}
			raw, _ := json.Marshal(e)
			if strings.Contains(string(raw), "DO_NOT_CAPTURE") {
				t.Fatal("completion leaked command/output")
			}
			seen[e.CallID] = e
		}
		cursor = b.Cursor
		if cursor.CompletionSchema == 2 && cursor.ContextRepair == nil {
			break
		}
	}
	if len(seen) != 6 || seen["image"].LogicalEventID != first.Events[0].LogicalEventID {
		t.Fatal("upgrade lost evidence or changed old identities", len(seen))
	}
	for i, tc := range cases {
		e := seen[fmt.Sprintf("cmd%d", i)]
		if e.Tool != "Bash" || e.Completion == nil || e.Completion.Status != tc.status {
			t.Fatal("native status lost", e)
		}
		if tc.code == "null" {
			if e.Completion.ExitCode != nil {
				t.Fatal("missing exit code became zero")
			}
		} else if e.Completion.ExitCode == nil || fmt.Sprint(*e.Completion.ExitCode) != tc.code {
			t.Fatal("exit code changed", e)
		}
	}
	last, err := ReadWithPolicy(context.Background(), s, cursor, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(last.Events) != 0 {
		t.Fatal("v2 replay repeated", err)
	}
}

func TestCodexCompletionNegotiationAndHistoricalReplay(t *testing.T) {
	data := codexRecord("session_meta", `{"id":"s","cli_version":"0.163.0"}`) +
		codexRecord("turn_context", `{"turn_id":"t"}`) +
		codexRecord("response_item", `{"type":"function_call","call_id":"c","name":"mcp__cua_repl__js","arguments":"{}"}`) +
		codexRecord("response_item", `{"type":"function_call_output","call_id":"c","output":"timeout"}`) +
		codexRecord("event_msg", `{"type":"item_completed","thread_id":"s","turn_id":"t","item":{"type":"McpToolCall","id":"c","server":"cua_repl","tool":"js","status":"failed","arguments":{"secret":"DO_NOT_CAPTURE"}}}`) +
		codexRecord("event_msg", `{"type":"item_completed","thread_id":"s","turn_id":"t","item":{"type":"ImageView","id":"image","path":"DO_NOT_CAPTURE"}}`)
	s := source(t, "codex", data)
	p := AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{}}
	first, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(first.Events) != 2 {
		t.Fatal("legacy collection changed", err, len(first.Events))
	}
	p.CompletionSchema = 1
	cursor := first.Cursor
	seen := map[string]Event{}
	budget := DefaultBudget()
	budget.Events = 1
	for n := 0; n < 10; n++ {
		b, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &p)
		if err != nil {
			t.Fatal(err)
		}
		for _, e := range b.Events {
			if err := ValidateEvent(e); err != nil {
				t.Fatal(err, e)
			}
			seen[e.LogicalEventID] = e
		}
		cursor = b.Cursor
		if cursor.CompletionSchema == 1 && cursor.ContextRepair == nil {
			break
		}
	}
	if len(seen) != 4 {
		t.Fatal("replay missing or duplicated evidence", len(seen))
	}
	count := 0
	for _, e := range seen {
		if e.Completion != nil {
			count++
			if e.Completion.Source != "codex.item_completed" || e.Outcome != "unknown" || len(e.Behavior.Contents) != 0 {
				t.Fatal("completion fabricated output", e)
			}
			if e.CallID == "c" && e.Completion.Status != "failed" {
				t.Fatal("failure lost", e)
			}
		}
	}
	if count != 2 {
		t.Fatal(count)
	}
	last, err := ReadWithPolicy(context.Background(), s, cursor, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(last.Events) != 0 {
		t.Fatal("replay repeated", err, len(last.Events))
	}
}

func TestCodexCompletionRejectsForeignOrUnfinishedItems(t *testing.T) {
	for _, body := range []string{
		`{"type":"item_completed","thread_id":"other","turn_id":"t","item":{"type":"ImageView","id":"i"}}`,
		`{"type":"item_completed","thread_id":"s","turn_id":"","item":{"type":"ImageView","id":"i"}}`,
		`{"type":"item_completed","thread_id":"s","turn_id":"t","item":{"type":"McpToolCall","id":"i","server":"s","tool":"t","status":"inProgress"}}`,
	} {
		drafts, err := parseCodex([]byte(codexRecord("event_msg", body)), &Cursor{Session: "s"})
		if err != nil || len(drafts) != 0 {
			t.Fatal(err, drafts)
		}
	}
}
