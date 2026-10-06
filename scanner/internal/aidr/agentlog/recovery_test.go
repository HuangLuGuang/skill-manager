package agentlog

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestOptionalUnknownRecordResumeAndPersistentEvidence(t *testing.T) {
	prefix := parallelLog(1, true)
	unknown := codexRecord("event_msg", `{"type":"future_optional_telemetry","counter":1}`)
	suffix := codexRecord("response_item", `{"type":"function_call","call_id":"after","name":"exec_command","arguments":{"cmd":"true"}}`)
	suffix += codexRecord("response_item", `{"type":"function_call_output","call_id":"after","output":"ok"}`)
	content := prefix + unknown + suffix
	s := source(t, "codex", content)
	// Read budget ends after quarantine, then restart and consume valid events.
	budget := DefaultBudget()
	budget.Bytes = int64(len(prefix) + len(unknown))
	first, err := ReadIncremental(context.Background(), s, Cursor{}, budget, time.Unix(0, 0))
	if err != nil || first.Cursor.Offset != int64(len(prefix)+len(unknown)) || !has(first, "aidr_log_optional_record_skipped") {
		t.Fatal(first, err)
	}
	if len(first.Coverage.Gaps) != 1 || first.Coverage.Gaps[0].Start != int64(len(prefix)) || first.Coverage.Gaps[0].EvidenceDigest != digest(unknown) {
		t.Fatal(first.Coverage)
	}
	encoded, _ := json.Marshal(first.Cursor)
	var restored Cursor
	json.Unmarshal(encoded, &restored)
	next := read(t, s, restored)
	if len(next.Events) != 2 || next.Cursor.Offset != int64(len(content)) || next.Coverage.Status != "partial" {
		t.Fatal(next)
	}
	if next.Events[0].SessionID != "parallel" || next.Events[0].TurnID != "second" || next.Events[0].LogicalCallID != next.Events[1].LogicalCallID {
		t.Fatal("lost known context")
	}
	for i := 0; i < 3; i++ {
		next = read(t, s, next.Cursor)
		if len(next.Events) != 0 || len(next.Cursor.RecoveryGaps) != 1 || len(next.Coverage.Gaps) != 1 || !has(next, "aidr_log_optional_record_skipped") {
			t.Fatal("repeated quarantine grew evidence", next)
		}
	}
}

func TestUnknownIdentityInvalidatesUntilExplicitRecovery(t *testing.T) {
	cases := []string{
		codexRecord("event_msg", `{"type":"future_context","nested":{"session_id":"unrecognized"}}`),
		codexRecord("response_item", `{"type":"future_tool_shape","call_id":"c0"}`),
		codexRecord("future_session", `{"session_id":"unrecognized"}`),
	}
	for _, unknown := range cases {
		t.Run(fmt.Sprint(len(unknown)), func(t *testing.T) {
			prefix := parallelLog(1, false)
			result := codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`)
			content := prefix + unknown + result + parallelLog(1, true)
			s := source(t, "codex", content)
			b := read(t, s, Cursor{})
			if b.Cursor.Offset != int64(len(content)) || !has(b, "aidr_log_context_invalidated") || !has(b, "aidr_log_call_unresolved") {
				t.Fatal(b)
			}
			if len(b.Events) != 4 || b.Events[1].SessionID != "" || b.Events[1].TurnID != "" || b.Events[1].LogicalCallID == b.Events[0].LogicalCallID {
				t.Fatal("invented context across gap", b.Events)
			}
			if b.Events[2].SessionID != "parallel" || b.Events[2].LogicalCallID != b.Events[3].LogicalCallID {
				t.Fatal("explicit context did not recover")
			}
		})
	}
}

func TestRecoveryRangesBoundedAcrossRestart(t *testing.T) {
	unknown := codexRecord("event_msg", `{"type":"future_optional_telemetry"}`)
	s := source(t, "codex", parallelLog(1, false)+strings.Repeat(unknown, 40))
	b := read(t, s, Cursor{})
	if len(b.Cursor.RecoveryGaps) != 32 || !b.Cursor.RecoveryDetailsTruncated || !b.Coverage.GapDetailsTruncated {
		t.Fatal(b.Coverage)
	}
	if err := ValidateCursor(b.Cursor, s); err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(b.Cursor)
	var restored Cursor
	json.Unmarshal(encoded, &restored)
	b = read(t, s, restored)
	if len(b.Coverage.Gaps) != 32 || !b.Coverage.GapDetailsTruncated || b.Coverage.Status != "partial" {
		t.Fatal(b.Coverage)
	}
}

func TestKnownMalformedCriticalRecordsRemainAtCheckpoint(t *testing.T) {
	for _, bad := range []string{
		"not json\n",
		codexRecord("session_meta", `{"id":{}}`),
		codexRecord("turn_context", `{"turn_id":{}}`),
		codexRecord("response_item", `{"type":"function_call","call_id":"broken","name":"exec_command"}`),
		codexRecord("event_msg", `{"type":{}}`),
	} {
		prefix := parallelLog(1, false)
		s := source(t, "codex", prefix+bad+parallelLog(1, true))
		b := read(t, s, Cursor{})
		if b.Cursor.Offset != int64(len(prefix)) || len(b.Events) != 1 || b.Coverage.Status != "partial" {
			t.Fatal("critical corruption skipped", b)
		}
		next := read(t, s, b.Cursor)
		if next.Cursor.Offset != b.Cursor.Offset || len(next.Events) != 0 {
			t.Fatal("critical corruption resumed")
		}
	}
}

func TestOversizedUnknownCannotCarryContextAcrossSkip(t *testing.T) {
	prefix := parallelLog(1, false)
	oversized := codexRecord("future_session", fmt.Sprintf(`{"session_id":"new","padding":%q}`, strings.Repeat("x", 2000)))
	result := codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`)
	content := prefix + oversized + result + parallelLog(1, true)
	s := source(t, "codex", content)
	budget := DefaultBudget()
	budget.LineBytes = 512
	budget.Bytes = 700
	var cursor Cursor
	var events []Event
	for i := 0; i < 20 && cursor.Offset < int64(len(content)); i++ {
		batch, err := ReadIncremental(context.Background(), s, cursor, budget, time.Unix(0, 0))
		if err != nil {
			t.Fatal(err)
		}
		encoded, _ := json.Marshal(batch.Cursor)
		json.Unmarshal(encoded, &cursor)
		events = append(events, batch.Events...)
	}
	if cursor.Offset != int64(len(content)) || len(events) != 4 {
		t.Fatal(cursor.Offset, len(events))
	}
	if events[1].SessionID != "" || events[1].LogicalCallID == events[0].LogicalCallID {
		t.Fatal("oversized context leaked")
	}
	if events[2].LogicalCallID != events[3].LogicalCallID {
		t.Fatal("explicit context recovery failed")
	}
}
