package agentlog

import (
	"encoding/json"
	"os"
	"testing"
)

func TestQoderNativeAncestrySurvivesCheckpointAndBranches(t *testing.T) {
	c := Cursor{}
	records := []struct{ raw, turn string }{
		{`{"type":"user","entrypoint":"cli","sessionId":"s","uuid":"u1","requestSetId":"r1","timestamp":"2026-10-09T00:00:00Z","message":{"content":"first"}}`, "r1"},
		{`{"type":"attachment","uuid":"context","parentUuid":"u1"}`, ""},
		{`{"type":"assistant","entrypoint":"cli","sessionId":"s","uuid":"a1","parentUuid":"context","timestamp":"2026-10-09T00:00:01Z","message":{"model":"auto","content":[{"type":"tool_use","id":"c1","name":"Bash","input":{"command":"true"}}]}}`, "r1"},
		{`{"type":"user","entrypoint":"cli","sessionId":"s","uuid":"u2","parentUuid":"a1","requestSetId":"r2","timestamp":"2026-10-09T00:00:02Z","message":{"content":"second"}}`, "r2"},
		{`{"type":"assistant","entrypoint":"cli","sessionId":"s","uuid":"a2","parentUuid":"u2","timestamp":"2026-10-09T00:00:03Z","message":{"model":"test-model","content":"reply"}}`, "r2"},
		{`{"type":"user","entrypoint":"cli","sessionId":"s","uuid":"result","parentUuid":"a1","timestamp":"2026-10-09T00:00:04Z","message":{"content":[{"type":"tool_result","tool_use_id":"c1","is_error":false,"content":"ok"}]}}`, "r1"},
		{`{"type":"assistant","entrypoint":"cli","sessionId":"s","uuid":"orphan","parentUuid":"missing","timestamp":"2026-10-09T00:00:05Z","message":{"content":"unassigned"}}`, ""},
		{`{"type":"file-history-snapshot"}`, ""},
	}
	for _, record := range records {
		ds, err := normalize("qoder-cli", []byte(record.raw), &c)
		if err != nil {
			t.Fatal(err)
		}
		for _, d := range ds {
			if d.Turn != record.turn {
				t.Fatalf("kind=%s turn=%q expected=%q", d.Kind, d.Turn, record.turn)
			}
		}
		// A new reader after each line has only the persisted native bindings.
		b, _ := json.Marshal(c)
		c = Cursor{}
		if err := json.Unmarshal(b, &c); err != nil {
			t.Fatal(err)
		}
	}
	if len(c.QoderLinks) == 0 {
		t.Fatal("missing persisted ancestry")
	}
}

func TestQoderUpgradeRepairsAncestryWithoutReupload(t *testing.T) {
	prefix := `{"type":"user","entrypoint":"cli","sessionId":"s","uuid":"u","requestSetId":"r","timestamp":"2026-10-09T00:00:00Z","message":{"content":"hello"}}` + "\n"
	s := source(t, "qoder-cli", prefix)
	c := read(t, s, Cursor{}).Cursor
	c.ContextRepairVersion, c.QoderLinks = 2, nil
	before := c
	repaired := read(t, s, c)
	if len(repaired.Events) != 0 || repaired.Cursor.Offset != before.Offset || repaired.Cursor.Anchor != before.Anchor || len(repaired.Cursor.QoderLinks) != 1 {
		t.Fatal("upgrade changed history or lost native ancestry")
	}
	f, err := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(`{"type":"assistant","entrypoint":"cli","sessionId":"s","uuid":"a","parentUuid":"u","timestamp":"2026-10-09T00:00:01Z","message":{"content":[{"type":"tool_use","id":"c","name":"Bash","input":{"command":"true"}}]}}` + "\n")
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	b := read(t, s, repaired.Cursor)
	if len(b.Events) != 1 || b.Events[0].TurnID != "r" {
		t.Fatalf("new call lost recovered turn: events=%+v coverage=%+v cursor=%+v", b.Events, b.Coverage, b.Cursor)
	}
	// Repeated native calls must not conflict with the same known turn.
	_, err = normalizeQoder([]byte(`{"type":"assistant","entrypoint":"cli","sessionId":"s","uuid":"a","parentUuid":"u","timestamp":"2026-10-09T00:00:01Z","message":{"content":[{"type":"tool_use","id":"c","name":"Bash","input":{"command":"true"}}]}}`), &b.Cursor)
	if err != nil || len(b.Cursor.CallTurns) != 1 || b.Cursor.CallTurns[0].Ambiguous {
		t.Fatal("duplicate call changed native binding", err)
	}
}

func TestQoderSessionChangeDoesNotReuseAncestry(t *testing.T) {
	c := Cursor{Session: "old", QoderLinks: []QoderLink{{ID: "u", Turn: "old-turn"}}}
	ds, err := normalizeQoder([]byte(`{"type":"assistant","entrypoint":"cli","sessionId":"new","uuid":"a","parentUuid":"u","timestamp":"2026-10-09T00:00:00Z","message":{"content":"hello"}}`), &c)
	if err != nil || len(ds) != 1 || ds[0].Turn != "" || len(c.QoderLinks) != 0 {
		t.Fatal("cross-session association", err)
	}
}
