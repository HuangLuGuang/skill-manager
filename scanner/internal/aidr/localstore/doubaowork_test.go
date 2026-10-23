package localstore

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestDoubaoHistoricalMessages(t *testing.T) {
	store := openStore(t, tempDir(t), DefaultLimits())
	defer store.Close()
	root := tempDir(t)
	path := filepath.Join(root, "session-1", "agents", "agent-1", "system", "trajectory.jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	lines := []string{
		`{"role":"user","content":"password=SYNTHETIC_SECRET"}`,
		`{"role":"assistant","content":"Checking now","tool_calls":[{"id":"call-1","function":{"name":"Read","arguments":{"file_path":"/tmp/public.txt"}}}]}`,
		`{"role":"tool","tool_call_id":"call-1","content":"public"}`,
		`{"role":"assistant","content":"Finished"}`,
		`{"role":"assistant","content":"Finished"}`,
	}
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	src, err := agentlog.NewSource("doubaowork", root, path)
	if err != nil {
		t.Fatal(err)
	}
	p := agentlog.AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &agentlog.CaptureScope{Prompt: true, ModelResponse: true}}
	if err := store.SavePolicy(testContext, p); err != nil {
		t.Fatal(err)
	}
	collect(t, store, src)
	before, err := store.Events(testContext, "", 500)
	if err != nil || len(before.Events) != 2 {
		t.Fatalf("legacy tools: %d %v", len(before.Events), err)
	}
	p.MessageSchema = 1
	p.Version, p.Receipt = "3", strings.Repeat("b", 32)
	if err := store.SavePolicy(testContext, p); err != nil {
		t.Fatal(err)
	}
	budget := agentlog.DefaultBudget()
	budget.Events = 2
	for i := 0; i < 12; i++ {
		if _, err := store.Collect(testContext, src, budget, time.Unix(0, 0)); err != nil {
			t.Fatal(err)
		}
	}
	page, err := store.Events(testContext, "", 500)
	if err != nil || len(page.Events) != 6 {
		t.Fatalf("backfill: %d %v", len(page.Events), err)
	}
	kinds := map[string]int{}
	for _, raw := range page.Events {
		var e agentlog.Event
		if err := json.Unmarshal(raw, &e); err != nil {
			t.Fatal(err)
		}
		if err := agentlog.ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
		kinds[e.Kind]++
		if e.SessionID != "session-1" || e.ObservedAtSource != "collection" {
			t.Fatal("missing session/time provenance")
		}
		if strings.Contains(string(raw), "SYNTHETIC_SECRET") {
			t.Fatal("unredacted prompt")
		}
	}
	if kinds["user_message"] != 1 || kinds["assistant_message"] != 3 {
		t.Fatal(kinds)
	}
	batch, err := store.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(batch.Payload), "doubao_messages") {
		t.Fatal("local marker on wire")
	}
	for _, scope := range []agentlog.CaptureScope{{Prompt: true}, {ModelResponse: true}, {}} {
		limited := p
		limited.Capture = &scope
		projection, err := agentlog.ReadWithPolicy(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0), &limited)
		if err != nil {
			t.Fatal(err)
		}
		for _, e := range projection.Events {
			if e.Message == nil {
				continue
			}
			enabled := scope.Prompt && e.Message.Role == "user" || scope.ModelResponse && e.Message.Role == "assistant"
			if enabled != (e.Message.ContentStatus == "captured") {
				t.Fatal("capture scope ignored")
			}
			if !enabled && len(e.Message.Contents) != 0 {
				t.Fatal("disabled content retained")
			}
		}
	}
	checkpoint, err := store.Checkpoint(testContext, src.ID)
	if err != nil {
		t.Fatal(err)
	}
	checkpoint.Cursor.DoubaoMessages = false
	if err := os.WriteFile(path, []byte(lines[0]+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	truncated, err := agentlog.ReadWithPolicy(testContext, src, checkpoint.Cursor, agentlog.DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || truncated.Cursor.Generation <= checkpoint.Cursor.Generation {
		t.Fatal("truncated backfill did not restart", err)
	}
}
