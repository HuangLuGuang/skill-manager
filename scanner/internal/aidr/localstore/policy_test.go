package localstore

import (
	"encoding/json"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"testing"
)

func TestPolicySwitchFrozenBatchRestartAndRotation(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	src := source(t, lines(1))
	// Upgrade an existing store without replacing records, cursors or a frozen batch.
	collect(t, s, src)
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	if !s.Policy().Enabled {
		t.Fatal("first contact must redact")
	}
	off := agentlog.AuditPolicy{Version: "2", Enabled: false, Receipt: strings.Repeat("a", 32)}
	if err = s.SavePolicy(testContext, off); err != nil {
		t.Fatal(err)
	}
	again, _ := s.Prepare(testContext, 500, 1<<20)
	if frozen.Digest != again.Digest || string(frozen.Payload) != string(again.Payload) {
		t.Fatal("frozen batch changed")
	}
	// Rotation replays the old logical event under a new policy; do not restore it.
	if err = os.Rename(src.Path, src.Path+".old"); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(src.Path, []byte(lines(2)), 0600); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	page, _ := s.Events(testContext, "", 500)
	if status(t, s).Evidence != 3 {
		t.Fatal("new physical evidence lost during policy migration")
	}
	if len(page.Events) != 2 {
		t.Fatalf("unexpected count %d", len(page.Events))
	}
	count := 0
	for _, raw := range page.Events {
		var e agentlog.Event
		if err := json.Unmarshal(raw, &e); err != nil {
			t.Fatal(err)
		}
		if strings.Contains(e.Behavior.Actions[0].Command, "SYNTHETIC_PRIVATE_MARKER") {
			count++
		}
	}
	if count != 1 {
		t.Fatal("only the new OFF record should contain the synthetic value")
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, DefaultLimits())
	if err = s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	if s.Policy().Enabled {
		t.Fatal("offline cache lost")
	}
	on := agentlog.AuditPolicy{Version: "3", Enabled: true, Receipt: strings.Repeat("b", 32)}
	if err = s.SavePolicy(testContext, on); err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(src.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(strings.ReplaceAll(lines(1), "call-0", "call-2"))
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	page, _ = s.Events(testContext, "", 500)
	if len(page.Events) != 3 {
		t.Fatal("missing event")
	}
	// Original frozen bytes and synthetic OFF value survive intentionally; new ON data is redacted.
	for _, raw := range page.Events {
		var e agentlog.Event
		if err := json.Unmarshal(raw, &e); err != nil {
			t.Fatal(err)
		}
		if e.CallID == "call-2" && strings.Contains(e.Behavior.Actions[0].Command, "SYNTHETIC_PRIVATE_MARKER") {
			t.Fatal("ON leak")
		}
	}
	if err = s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	if status(t, s).LogicalEvents != 3 {
		t.Fatal("replay duplicated")
	}
}
func TestDefaultPolicyNeverPersistsSecret(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	if err := s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	collect(t, s, source(t, lines(1)))
	s.Close()
	for _, name := range []string{"state.db", "state.db-wal"} {
		raw, _ := os.ReadFile(filepath.Join(dir, name))
		if strings.Contains(string(raw), "SYNTHETIC_PRIVATE_MARKER") {
			t.Fatal("raw secret reached disk")
		}
	}
}

func TestScopedPolicyUpgradeKeepsLogIdentityCursorAndFrozenBytes(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	if err := s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	legacy := agentlog.AuditPolicy{Version: "1", Enabled: true, Receipt: strings.Repeat("a", 32)}
	if err := s.SavePolicy(testContext, legacy); err != nil {
		t.Fatal(err)
	}
	src := source(t, lines(1))
	collect(t, s, src)
	first, _ := s.Events(testContext, "", 500)
	var original agentlog.Event
	if err := json.Unmarshal(first.Events[0], &original); err != nil {
		t.Fatal(err)
	}
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	scoped := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("b", 32), Capture: &agentlog.CaptureScope{FileBody: true}}
	if err = s.SavePolicy(testContext, scoped); err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(src.Path, src.Path+".old"); err != nil {
		t.Fatal(err)
	}
	newLine := `{"type":"assistant","timestamp":"2026-09-23T10:00:00Z","sessionId":"session-a","version":"2.1.220","message":{"content":[{"type":"tool_use","id":"new-file","name":"Write","input":{"file_path":"/tmp/synthetic-only","content":"TOKEN=SYNTHETIC-LOG-CONTENT"}}]}}` + "\n"
	if err = os.WriteFile(src.Path, []byte(lines(1)+newLine), 0600); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	page, _ := s.Events(testContext, "", 500)
	if len(page.Events) != 2 {
		t.Fatal("logical replay duplicated", len(page.Events))
	}
	oldFound, newFound := false, false
	for _, raw := range page.Events {
		var e agentlog.Event
		if err = json.Unmarshal(raw, &e); err != nil {
			t.Fatal(err)
		}
		if e.CallID == original.CallID {
			oldFound = e.LogicalEventID == original.LogicalEventID && e.Behavior.Version == 3 && len(e.Behavior.Contents) == 0
		}
		if e.CallID == "new-file" {
			newFound = e.Behavior.Version == 4 && len(e.Behavior.Contents) == 1 && e.Behavior.Contents[0].Text == "TOKEN=[REDACTED]"
		}
	}
	if !oldFound || !newFound {
		t.Fatal("old projection or new bounded content lost")
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"state.db", "state.db-wal"} {
		data, _ := os.ReadFile(filepath.Join(dir, name))
		if strings.Contains(string(data), "SYNTHETIC-LOG-CONTENT") {
			t.Fatal("raw body secret persisted")
		}
	}
	s = openStore(t, dir, DefaultLimits())
	if err = s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	again, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || frozen.Digest != again.Digest || string(frozen.Payload) != string(again.Payload) {
		t.Fatal("frozen log batch changed", err)
	}
	if !s.Policy().Equal(scoped) {
		t.Fatal("scope cache lost")
	}
	if err = s.Acknowledge(testContext, frozen.ID, strings.Repeat("0", 64)); err == nil {
		t.Fatal("incorrect ACK accepted")
	}
	if err = s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	if status(t, s).LogicalEvents != 2 {
		t.Fatal("restart duplicated logical operations")
	}
}
