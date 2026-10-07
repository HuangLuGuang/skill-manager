package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestCodex1601NativeConversationResume(t *testing.T) {
	data, err := os.ReadFile("testdata/codex-0.160.1.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	s := source(t, "codex", string(data))
	policy := AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true,
		Capture: &CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
	budget := DefaultBudget()
	budget.Events = 2
	var cursor Cursor
	var events []Event
	for n := 0; n < 5; n++ {
		batch, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &policy)
		if err != nil {
			t.Fatal(err)
		}
		events = append(events, batch.Events...)
		raw, err := json.Marshal(batch.Cursor)
		if err != nil || json.Unmarshal(raw, &cursor) != nil {
			t.Fatal("cursor persistence failed", err)
		}
		if cursor.Offset == int64(len(data)) {
			if batch.Coverage.Status != "complete" {
				t.Fatal("observed native format marked incomplete", batch.Coverage)
			}
			break
		}
	}
	want := []string{"user_message", "assistant_message", "tool_call", "tool_result", "assistant_message"}
	if len(events) != len(want) || cursor.Offset != int64(len(data)) {
		t.Fatal("native messages or tool records missing", len(events), cursor.Offset)
	}
	seen := map[string]bool{}
	for i, ev := range events {
		if ev.Kind != want[i] || ev.SessionID != "anonymous-session-1601" || ev.TurnID != "turn-1601" || seen[ev.LogicalEventID] || ValidateEvent(ev) != nil {
			t.Fatalf("invalid native event %d: %+v", i, ev)
		}
		seen[ev.LogicalEventID] = true
	}
	if events[1].Message.Phase != "commentary" || events[4].Message.Phase != "final" {
		t.Fatal("reply phases lost")
	}
	if events[2].LogicalCallID != events[3].LogicalCallID || events[2].Tool != "exec" || len(events[2].Behavior.Actions) != 1 || events[2].Behavior.Actions[0].Command != "printf AIDR1601_TOOL_OK" {
		t.Fatal("native custom tool binding lost")
	}
	// Native custom_tool_call_output supplies text without a shell exit code.
	if events[3].Behavior.ExitCode != nil || events[3].Behavior.Status != "unknown" {
		t.Fatal("invented exit evidence")
	}
	again, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &policy)
	if err != nil || len(again.Events) != 0 {
		t.Fatal("confirmed cursor replayed events", err)
	}
}

func TestConversationFormatIndependentOfReleaseAndLegacyVersionGap(t *testing.T) {
	data, err := os.ReadFile("testdata/codex-0.160.1.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	policy := AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true,
		Capture: &CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
	for _, version := range []string{"0.160.2", "0.161.99", "1.0.0-beta.1", "vendor-build"} {
		t.Run(version, func(t *testing.T) {
			s := source(t, "codex", strings.ReplaceAll(string(data), "0.160.1", version))
			batch, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &policy)
			if err != nil || len(batch.Events) != 5 || batch.Coverage.Status != "complete" || batch.Cursor.AgentVersion != version {
				t.Fatalf("recognized format lost: %v %+v", err, batch.Coverage)
			}
			if batch.Events[1].Message.Phase != "commentary" || batch.Events[4].Message.Phase != "final" || batch.Events[2].LogicalCallID != batch.Events[3].LogicalCallID {
				t.Fatal("message/tool semantics changed")
			}
			cursor := batch.Cursor
			cursor.Gaps = []string{"aidr_log_version_unverified"}
			again, err := ReadWithPolicy(context.Background(), s, cursor, DefaultBudget(), time.Unix(0, 0), &policy)
			if err != nil || again.Coverage.Status != "complete" || again.Cursor.Offset != cursor.Offset || len(again.Events) != 0 || len(again.Cursor.Gaps) != 1 {
				t.Fatal("legacy version label caused false gap or changed cursor history")
			}
			cursor.Gaps = append(cursor.Gaps, "aidr_log_invalid_json")
			again, err = ReadWithPolicy(context.Background(), s, cursor, DefaultBudget(), time.Unix(0, 0), &policy)
			if err != nil || again.Coverage.Status != "partial" {
				t.Fatal("real historical format gap lost")
			}
		})
	}
}
