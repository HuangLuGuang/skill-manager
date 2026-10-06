package localstore

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestCollectionPauseAdvancesCursorAndRetentionLeavesPendingFrozen(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	src := source(t, lines(1))
	collect(t, s, src)
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	off := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{}, Lifecycle: &agentlog.AuditLifecycle{Enabled: false, RetentionDays: 1}}
	if err = s.SavePolicy(testContext, off); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(src.Path, []byte(lines(2)), 0600); err != nil {
		t.Fatal(err)
	}
	paused := collect(t, s, src)
	if paused.Cursor.Offset != int64(len(lines(2))) || paused.Coverage.Status != "partial" || !strings.Contains(strings.Join(paused.Cursor.Gaps, ","), "aidr_audit_collection_disabled") {
		t.Fatal(paused)
	}
	if status(t, s).LogicalEvents != 1 {
		t.Fatal("disabled event persisted")
	}
	if n, err := s.Prune(testContext, time.Now().Add(2*24*time.Hour)); err != nil || n != 0 {
		t.Fatal("pending body expired", n, err)
	}
	same, _ := s.Prepare(testContext, 500, 1<<20)
	if !bytes.Equal(same.Payload, frozen.Payload) {
		t.Fatal("frozen body changed")
	}
	if err = s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil {
		t.Fatal(err)
	}
	if n, err := s.Prune(testContext, time.Now().Add(2*24*time.Hour)); err != nil || n != 1 {
		t.Fatal("platform TTL not applied", n, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, DefaultLimits())
	if err = s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	if s.Policy().CollectionEnabled() {
		t.Fatal("cached pause lost")
	}
	on := off
	on.Version = "3"
	on.Receipt = strings.Repeat("b", 32)
	on.Lifecycle = &agentlog.AuditLifecycle{Enabled: true, RetentionDays: 1}
	if err = s.SavePolicy(testContext, on); err != nil {
		t.Fatal(err)
	}
	newLine := strings.Split(lines(3), "\n")[2] + "\n"
	newLine = strings.ReplaceAll(newLine, "2026-09-23T01:00:00Z", time.Now().Add(time.Second).UTC().Format(time.RFC3339Nano))
	if err = os.WriteFile(src.Path, []byte(lines(2)+newLine), 0600); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	page, _ := s.Events(testContext, "", 500)
	if len(page.Events) != 1 || !bytes.Contains(page.Events[0], []byte(`"native_call_id":"call-2"`)) {
		t.Fatal("resume recollected disabled interval", len(page.Events))
	}
	resume := s.collectionResumeAt
	if resume.IsZero() {
		t.Fatal("resume boundary not saved")
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	if err = s.LoadPolicy(testContext); err != nil || !s.collectionResumeAt.Equal(resume) {
		t.Fatal("resume boundary lost", err)
	}
	// Discovery after resuming must not backfill an unseen source from the pause.
	unseen := source(t, lines(1))
	gap := collect(t, s, unseen)
	if gap.Coverage.Status != "partial" || gap.Coverage.Filtered != 1 || !strings.Contains(strings.Join(gap.Cursor.Gaps, ","), "aidr_audit_collection_disabled") {
		t.Fatal("undiscovered pause history collected", gap)
	}
	page, _ = s.Events(testContext, "", 500)
	if len(page.Events) != 1 {
		t.Fatal("unseen history persisted")
	}
	for _, name := range []string{"state.db", "state.db-wal"} {
		raw, _ := os.ReadFile(filepath.Join(dir, name))
		if bytes.Contains(raw, []byte("SYNTHETIC_PRIVATE_MARKER")) {
			t.Fatal("secret persisted")
		}
	}
}
