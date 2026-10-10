package hooks

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestSuppressedMaintenanceIsBoundedAndHealthCountsOnlyRecentReceipts(t *testing.T) {
	s := openTestStore(t, storeDirectory(t), 20)
	ctx := context.Background()
	off := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{}, Lifecycle: &agentlog.AuditLifecycle{Enabled: false, RetentionDays: 7}}
	if err := s.SetPolicy(ctx, off); err != nil {
		t.Fatal(err)
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 501; i++ {
		if _, err = tx.ExecContext(ctx, `INSERT INTO hook_suppressed_receipts VALUES(?,?,?)`, fmt.Sprintf("old-%d", i), "opaque-synthetic-hash", time.Now().Add(-49*time.Hour).Unix()); err != nil {
			t.Fatal(err)
		}
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	before, err := s.Status(ctx)
	if err != nil || before.Suppressed != 0 {
		t.Fatal("expired receipts advertised as recent", before, err)
	}
	if _, err = s.Receive(ctx, testID(1), "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
		t.Fatal(err)
	}
	var count int
	if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM hook_suppressed_receipts`).Scan(&count); err != nil || count != 2 {
		t.Fatal("prune exceeded 500 rows", count, err)
	}
	after, err := s.Status(ctx)
	if err != nil || after.Suppressed != 1 {
		t.Fatal(after, err)
	}
}

func TestAuditPauseKeepsFrozenBytesAndNeverRestoresSuppressedContent(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 20)
	if _, err := s.Receive(ctx, testID(1), "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
		t.Fatal(err)
	}
	frozen, err := s.Prepare(ctx)
	if err != nil {
		t.Fatal(err)
	}
	off := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{Prompt: true}, Lifecycle: &agentlog.AuditLifecycle{Enabled: false, RetentionDays: 1}}
	if err := s.SetPolicy(ctx, off); err != nil {
		t.Fatal(err)
	}
	id := testID(2)
	raw := []byte(`{"hook_event_name":"UserPromptSubmit","session_id":"s","prompt":"SYNTHETIC-DO-NOT-PERSIST"}`)
	skipped, err := s.Receive(ctx, id, "501", "codex", "UserPromptSubmit", raw)
	if err != nil || skipped.Sequence != "" || len(skipped.Event.Contents) != 0 {
		t.Fatal("pause persisted a new audit", err)
	}
	state, _ := s.Status(ctx)
	if state.Queued != 1 || state.LastSequence != "1" || state.Suppressed != 1 {
		t.Fatal(state)
	}
	same, _ := s.Prepare(ctx)
	if !bytes.Equal(same.Payload, frozen.Payload) || same.Digest != frozen.Digest {
		t.Fatal("pause rewrote frozen bytes")
	}
	if err = s.Acknowledge(ctx, state.Device, state.Stream, frozen.Digest, frozen.Count, true); err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openTestStore(t, dir, 20)
	state, _ = s.Status(ctx)
	if state.Policy.CollectionEnabled() || state.Queued != 0 || state.Suppressed != 1 {
		t.Fatal("pause did not survive restart", state)
	}
	on := off
	on.Version = "3"
	on.Receipt = strings.Repeat("b", 32)
	on.Lifecycle = &agentlog.AuditLifecycle{Enabled: true, RetentionDays: 1}
	if err = s.SetPolicy(ctx, on); err != nil {
		t.Fatal(err)
	}
	replay, err := s.Receive(ctx, id, "501", "codex", "UserPromptSubmit", raw)
	if err != nil || replay.Sequence != "" {
		t.Fatal("resume restored disabled history", err)
	}
	next, err := s.Receive(ctx, testID(3), "501", "codex", "UserPromptSubmit", []byte(`{"hook_event_name":"UserPromptSubmit","session_id":"s","prompt":"NEW-SYNTHETIC-CONTENT"}`))
	if err != nil || next.Sequence != "2" || next.Event.Schema != 3 || next.Event.Contents[0].Text != "NEW-SYNTHETIC-CONTENT" {
		t.Fatal(next, err)
	}
	for _, name := range []string{"hooks.db", "hooks.db-wal", "hooks.db-shm", "state.db", "state.db-wal"} {
		b, e := os.ReadFile(filepath.Join(dir, name))
		if e != nil && !os.IsNotExist(e) {
			t.Fatal(e)
		}
		if bytes.Contains(b, []byte("SYNTHETIC-DO-NOT-PERSIST")) {
			t.Fatal("disabled source text persisted")
		}
	}
}
