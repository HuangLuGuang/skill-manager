package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestOversizedEnvelopeDoesNotGuessIdentityFromBody(t *testing.T) {
	for _, tc := range []struct {
		prefix string
		keep   bool
	}{
		{`{"type":"response_item","payload":{"type":"custom_tool_call_output","output":"`, true},
		{`{"type":"response_item","payload":{"type":"message","content":[`, true},
		{`{"type":"response_item","payload":{"type":"future_session","id":"`, false},
		{`{"type":"session_meta","payload":{"id":"`, false},
		{`{"payload":{"type":"compacted"},"type":"future_session","extra":"`, false},
		{`{"type":"event_msg","payload":{"type":"task_started","extra":"`, false},
	} {
		if got := oversizedPreservesContext("codex", []byte(tc.prefix)); got != tc.keep {
			t.Fatalf("prefix=%s keep=%v", tc.prefix, got)
		}
		if oversizedPreservesContext("claude", []byte(tc.prefix)) {
			t.Fatal("cross-product assumption")
		}
	}
}

func TestOversizedCompactionRetainsSessionMessagesAndCalls(t *testing.T) {
	prefix := parallelLog(1, false)
	large := codexRecord("compacted", `{"message":"`+strings.Repeat("x", 5<<20)+`"}`)
	large += codexRecord("response_item", `{"type":"custom_tool_call_output","call_id":"large-output","output":"`+strings.Repeat("x", 3<<20)+`"}`)
	suffix := codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`) +
		codexRecord("response_item", `{"type":"message","role":"user","content":[{"type":"input_text","text":"check"}]}`) +
		codexRecord("response_item", `{"type":"message","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"done"}]}`)
	s := source(t, "codex", prefix+large+suffix)
	p := &AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	var c Cursor
	var events []Event
	for i := 0; i < 8; i++ {
		b, err := ReadWithPolicy(context.Background(), s, c, DefaultBudget(), time.Unix(0, 0), p)
		if err != nil {
			t.Fatal(err)
		}
		c = b.Cursor
		events = append(events, b.Events...)
		if c.Offset == int64(len(prefix+large+suffix)) {
			break
		}
	}
	if len(events) != 4 || c.Session != "parallel" || c.Discarding {
		t.Fatalf("events=%d session=%q offset=%d", len(events), c.Session, c.Offset)
	}
	if events[1].TurnID != "first" || events[1].LogicalCallID != events[0].LogicalCallID || events[2].Kind != "user_message" || events[3].Kind != "assistant_message" {
		t.Fatal("lost binding/message after compaction")
	}
	for _, event := range events {
		if err := ValidateEvent(event); err != nil {
			t.Fatal(err)
		}
	}
}

func TestLegacyContextRepairIsBoundedResumableAndDoesNotReuploadHistory(t *testing.T) {
	prefix := parallelLog(1, false)
	large := codexRecord("compacted", `{"message":"`+strings.Repeat("x", 5<<20)+`"}`)
	for _, unknown := range []bool{false, true} {
		content := prefix + large
		if unknown {
			content += codexRecord("future_session", `{"id":"different"}`)
		}
		s := source(t, "codex", content)
		var c Cursor
		for c.Offset < int64(len(content)) {
			c = read(t, s, c).Cursor
		}
		// Reproduce the old committed cursor; keep its offset, generation and anchor.
		c.ContextRepairVersion = 0
		invalidateContext(&c)
		original := c
		for i := 0; i < 8 && c.ContextRepairVersion < contextRepairVersion; i++ {
			b := read(t, s, c)
			if len(b.Events) != 0 || b.Cursor.Offset != original.Offset || b.Cursor.Anchor != original.Anchor || b.Coverage.Bytes > DefaultBudget().Bytes {
				t.Fatal("repair changed committed history or exceeded budget")
			}
			encoded, _ := json.Marshal(b.Cursor)
			c = Cursor{}
			if err := json.Unmarshal(encoded, &c); err != nil {
				t.Fatal(err)
			}
			if err := ValidateCursor(c, s); err != nil {
				t.Fatal(err)
			}
		}
		if c.ContextRepairVersion != contextRepairVersion || c.ContextRepair != nil || (c.Session == "parallel") == unknown {
			t.Fatalf("wrong recovered session %q unknown=%v", c.Session, unknown)
		}
		if !unknown {
			f, err := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
			if err != nil {
				t.Fatal(err)
			}
			_, err = f.WriteString(codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`))
			f.Close()
			if err != nil {
				t.Fatal(err)
			}
			b := read(t, s, c)
			if len(b.Events) != 1 || b.Events[0].SessionID != "parallel" || b.Events[0].TurnID != "first" {
				t.Fatal("new event was not recovered")
			}
		}
	}
}
