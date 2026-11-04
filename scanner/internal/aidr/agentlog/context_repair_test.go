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

func TestLegacyContextRepairIsBoundedResumable(t *testing.T) {
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
		for i := 0; i < 8 && c.ContextRepairVersion < codexContextRepairVersion; i++ {
			b := read(t, s, c)
			if b.Cursor.Offset != original.Offset || b.Cursor.Anchor != original.Anchor || b.Coverage.Bytes > DefaultBudget().Bytes {
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
		if c.ContextRepairVersion != codexContextRepairVersion || c.ContextRepair != nil || (c.Session == "parallel") == unknown {
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

func TestCodexAdditionalToolsReprojectsDamagedHistory(t *testing.T) {
	prefix := strings.ReplaceAll(parallelLog(1, false), "0.160.0", "0.163.0-alpha.10.2")
	metadata := codexRecord("response_item", `{"type":"additional_tools","id":"tools-1","role":"assistant","tools":[{"name":"exec","description":"tool metadata"}]}`)
	suffix := codexRecord("response_item", `{"type":"message","role":"user","content":[{"type":"input_text","text":"check"}]}`) + codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`)
	s := source(t, "codex", prefix+metadata+suffix)
	p := &AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ToolOutput: true}}
	original, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), p)
	if err != nil || len(original.Events) != 3 || original.Cursor.Session != "parallel" {
		t.Fatalf("new format failed: %v events=%d", err, len(original.Events))
	}
	c := original.Cursor
	c.Generation = 7
	c.ContextRepairVersion = 3
	invalidateContext(&c)
	rememberRecovery(&c, int64(len(prefix)), int64(len(prefix+metadata)), "aidr_log_context_invalidated", []byte(metadata))
	budget := DefaultBudget()
	budget.Events = 1
	var events []Event
	for i := 0; i < 8 && c.ContextRepairVersion < codexContextRepairVersion; i++ {
		got, err := ReadWithPolicy(context.Background(), s, c, budget, time.Unix(0, 0), p)
		if err != nil {
			t.Fatal(err)
		}
		if got.Cursor.Offset != original.Cursor.Offset || got.Cursor.Anchor != original.Cursor.Anchor {
			t.Fatal("changed durable checkpoint")
		}
		events = append(events, got.Events...)
		encoded, _ := json.Marshal(got.Cursor)
		c = Cursor{}
		if err := json.Unmarshal(encoded, &c); err != nil {
			t.Fatal(err)
		}
		if err := ValidateCursor(c, s); err != nil {
			t.Fatal(err)
		}
	}
	if len(events) != 3 || c.ContextRepair != nil || c.Session != "parallel" || len(c.RecoveryGaps) != 0 {
		t.Fatalf("repair incomplete events=%d cursor=%+v", len(events), c)
	}
	for i, e := range events {
		if e.SessionID != "parallel" || e.LogicalEventID != original.Events[i].LogicalEventID || e.SourceInstanceID != digest(s.ID, c.FileIdentity, "7") {
			t.Fatal("unstable replay identity")
		}
	}
	if got := read(t, s, c); len(got.Events) != 0 {
		t.Fatal("replayed twice")
	}
}

func TestOversizedItemCompletedRepairsOlderCursors(t *testing.T) {
	prefix := parallelLog(1, false)
	body := prefix + codexRecord("event_msg", `{"type":"item_completed","thread_id":"parallel","turn_id":"first","item":{"output":"`+strings.Repeat("x", 3<<20)+`"}}`) + codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`) + codexRecord("response_item", `{"type":"message","role":"user","content":[{"type":"input_text","text":"after large event"}]}`)
	s := source(t, "codex", body)
	policy := &AuditPolicy{MessageSchema: 1, Enabled: true, Version: "2", Receipt: strings.Repeat("a", 32), Capture: &CaptureScope{Prompt: true}}
	var c Cursor
	var events []Event
	for i := 0; i < 8; i++ {
		b, err := ReadWithPolicy(context.Background(), s, c, DefaultBudget(), time.Unix(0, 0), policy)
		if err != nil {
			t.Fatal(err)
		}
		c = b.Cursor
		events = append(events, b.Events...)
		if c.Offset == int64(len(body)) {
			break
		}
	}
	if len(events) != 3 || events[1].SessionID != "parallel" || events[2].Kind != "user_message" {
		t.Fatal("lost identity after large metadata")
	}
	for _, version := range []int{0, 3, 4} {
		damaged := c
		damaged.ContextRepairVersion = version
		invalidateContext(&damaged)
		budget := DefaultBudget()
		budget.Events = 1
		recovered := []Event{}
		for i := 0; i < 12 && damaged.ContextRepairVersion < codexContextRepairVersion; i++ {
			b, err := ReadWithPolicy(context.Background(), s, damaged, budget, time.Unix(0, 0), policy)
			if err != nil {
				t.Fatal(err)
			}
			if b.Cursor.Offset != c.Offset {
				t.Fatal("moved committed cursor")
			}
			recovered = append(recovered, b.Events...)
			raw, _ := json.Marshal(b.Cursor)
			damaged = Cursor{}
			if err := json.Unmarshal(raw, &damaged); err != nil {
				t.Fatal(err)
			}
		}
		if len(recovered) != 3 || damaged.Session != "parallel" || damaged.ContextRepair != nil {
			t.Fatalf("version %d repair incomplete", version)
		}
	}
	if oversizedPreservesContext("codex", []byte(`{"type":"event_msg","payload":{"type":"task_started","extra":"`)) {
		t.Fatal("treated turn boundary as metadata")
	}
}

func TestCodexConfigurationUpdatePreservesAndRestoresSession(t *testing.T) {
	prefix := parallelLog(1, false)
	update := codexRecord("response_item", `{"type":"configuration_update","reasoning":{"effort":"high"} }`)
	s := source(t, "codex", prefix+update)
	b := read(t, s, Cursor{})
	if len(b.Events) != 1 || b.Cursor.Session != "parallel" || b.Cursor.Turn != "first" {
		t.Fatalf("configuration update broke active call: session=%q turn=%q", b.Cursor.Session, b.Cursor.Turn)
	}
	old := b.Cursor
	invalidateContext(&old)
	old.ContextRepairVersion = 5
	repaired := read(t, s, old)
	if len(repaired.Events) != 0 || repaired.Cursor.Offset != old.Offset || repaired.Cursor.Anchor != old.Anchor || repaired.Cursor.Session != "parallel" || repaired.Cursor.ContextRepairVersion != codexContextRepairVersion {
		t.Fatal("upgrade did not recover context at the committed checkpoint")
	}
	f, err := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(codexRecord("response_item", `{"type":"function_call_output","call_id":"c0","output":"ok"}`))
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	got := read(t, s, repaired.Cursor)
	if len(got.Events) != 1 || got.Events[0].SessionID != "parallel" || got.Events[0].TurnID != "first" || got.Events[0].LogicalCallID != b.Events[0].LogicalCallID {
		t.Fatal("tool result did not rejoin the original session, turn and call")
	}
}
