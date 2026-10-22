package managedclient

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestInteractiveMutationLockWaitsForBackgroundAction(t *testing.T) {
	home := t.TempDir()
	release, err := AcquireMutationLock(home)
	if err != nil {
		t.Fatal(err)
	}
	go func() {
		time.Sleep(50 * time.Millisecond)
		release()
	}()
	waited, err := AcquireMutationLockWithTimeout(home, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	waited()
}

func TestLegacyPatrolAndQuarantineRespectMutationLock(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	release, err := AcquireMutationLock(home)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	if err := patrol(context.Background(), home, Inventory{}, Policy{Mode: "block"}, API{}, store, true, false); err != nil {
		t.Fatalf("read-only patrol should not acquire file locks: %v", err)
	}
	if _, err := QuarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual"); !errors.Is(err, ErrSkillActionBusy) {
		t.Fatalf("quarantine bypassed mutation lock: %v", err)
	}
	if _, err := os.Stat(skill.Path); err != nil {
		t.Fatal(err)
	}
}

func TestLegacyQuarantineRejectsEditedObservationAndSharesPatrolLock(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	ctx, release, err := withMutationLock(context.Background(), home)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	if err := os.WriteFile(filepath.Join(skill.Path, "SKILL.md"), []byte("new content"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := quarantineCurrentSkill(ctx, home, store, "codex", skill.Name, skill.Path, "unmanaged_skill", skill.Signature); err == nil || err.Error() != "skill_content_changed" {
		t.Fatalf("expected fingerprint conflict, got %v", err)
	}
	if content, err := os.ReadFile(filepath.Join(skill.Path, "SKILL.md")); err != nil || string(content) != "new content" {
		t.Fatalf("edited content lost: %q %v", content, err)
	}
	item, err := quarantineCurrentSkill(ctx, home, store, "codex", skill.Name, skill.Path, "manual", "")
	if err != nil {
		t.Fatal(err)
	}
	if content, err := os.ReadFile(filepath.Join(item.QuarantinePath, "SKILL.md")); err != nil || string(content) != "new content" {
		t.Fatalf("retained copy missing: %q %v", content, err)
	}
}

func TestQuarantineRetainsCopyWhenSourceRemovalFails(t *testing.T) {
	if runtime.GOOS == "windows" || os.Geteuid() == 0 {
		t.Skip("requires Unix directory permission enforcement")
	}
	home, store, _, skill := observedFixture(t)
	locked := filepath.Join(skill.Path, "locked")
	if err := os.Mkdir(locked, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(locked, "content.txt"), []byte("recoverable"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(locked, 0500); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(locked, 0700)
	item, err := QuarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual")
	if err == nil || item.ID == "" {
		t.Fatalf("expected retained recovery record on removal failure: %v %v", item, err)
	}
	defer os.Chmod(filepath.Join(item.QuarantinePath, "locked"), 0700)
	content, err := os.ReadFile(filepath.Join(item.QuarantinePath, "locked", "content.txt"))
	if err != nil || string(content) != "recoverable" {
		t.Fatal("backup lost after partial removal", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].Status != "quarantine_failed" {
		t.Fatal(items, err)
	}
}

func TestQuarantineAndRestoreSkill(t *testing.T) {
	home := t.TempDir()
	source := filepath.Join(home, ".codex", "skills", "unsafe")
	if err := os.MkdirAll(source, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("unsafe"), 0o644); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	item, err := QuarantineSkill(home, store, "codex", "unsafe", source, "unmanaged_skill")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(source); !os.IsNotExist(err) {
		t.Fatalf("source still exists after quarantine: %v", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].Status != "quarantined" {
		t.Fatalf("unexpected quarantine items: %#v %v", items, err)
	}
	if _, err := os.Stat(item.QuarantinePath); err != nil {
		t.Fatalf("quarantined content was not retained: %v", err)
	}
	if err := store.ResolveQuarantine("codex", "unsafe"); err != nil {
		t.Fatal(err)
	}
	items, err = store.QuarantineItems()
	if err != nil || len(items) != 0 {
		t.Fatalf("resolved item remained in active quarantine: %#v %v", items, err)
	}
}

func TestQueueQuarantineForDetectionKeepsOriginalUntilApprovedInstall(t *testing.T) {
	home := t.TempDir()
	source := filepath.Join(home, ".codex", "skills", "changed")
	writeSkill(t, source, "changed")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	quarantine, err := QuarantineSkill(home, store, "codex", "changed", source, "signature_mismatch")
	if err != nil {
		t.Fatal(err)
	}

	pending, err := QueueQuarantineForDetection(home, store, quarantine.ID)
	if err != nil {
		t.Fatal(err)
	}
	if pending.Reason != "quarantine_rescan" || pending.Fingerprint == "" {
		t.Fatalf("unexpected pending item: %#v", pending)
	}
	if _, err := os.Stat(filepath.Join(pending.PendingPath, "SKILL.md")); err != nil {
		t.Fatalf("pending copy was not created: %v", err)
	}
	if _, err := os.Stat(filepath.Join(quarantine.QuarantinePath, "SKILL.md")); err != nil {
		t.Fatalf("quarantine original was removed before approval: %v", err)
	}

	repeated, err := QueueQuarantineForDetection(home, store, quarantine.ID)
	if err != nil {
		t.Fatal(err)
	}
	if repeated.ID != pending.ID || repeated.PendingPath != pending.PendingPath {
		t.Fatalf("queue operation was not idempotent: %#v %#v", pending, repeated)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 {
		t.Fatalf("queued quarantine item disappeared: %#v %v", items, err)
	}
	if items[0].PendingID != pending.ID || items[0].DetectionStatus != "pending" {
		t.Fatalf("quarantine item did not expose detection progress: %#v", items[0])
	}
	if err := store.MarkPendingSubmitted(pending, "family-1", "version-1"); err != nil {
		t.Fatal(err)
	}
	if err := store.UpdatePendingStatus("family-1", "version-1", "REJECTED"); err != nil {
		t.Fatal(err)
	}
	items, err = store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].DetectionStatus != "REJECTED" || items[0].SkillID != "family-1" || items[0].VersionID != "version-1" {
		t.Fatalf("terminal detection result was not exposed in quarantine: %#v %v", items, err)
	}
}

func TestQueueQuarantineForDetectionRejectsContentChangedAfterSelection(t *testing.T) {
	home := t.TempDir()
	source := filepath.Join(home, ".codex", "skills", "changed")
	writeSkill(t, source, "selected content")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	quarantine, err := QuarantineSkill(home, store, "codex", "changed", source, "signature_mismatch")
	if err != nil {
		t.Fatal(err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].Signature == "" {
		t.Fatal(items, err)
	}
	selectedSignature := items[0].Signature
	writeSkill(t, quarantine.QuarantinePath, "changed after selection")

	if _, err := QueueQuarantineForDetectionExpected(home, store, quarantine.ID, selectedSignature); err == nil || err.Error() != "skill_content_changed" {
		t.Fatalf("changed quarantine copy was submitted: %v", err)
	}
	if pending, err := store.PendingItems(); err != nil || len(pending) != 0 {
		t.Fatalf("changed copy created pending content: %#v %v", pending, err)
	}
}

func TestDiscardPendingRemovesLinkedQuarantineButKeepsInstalledSkill(t *testing.T) {
	home := t.TempDir()
	source := filepath.Join(home, ".codex", "skills", "changed")
	writeSkill(t, source, "untrusted")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	quarantine, err := QuarantineSkill(home, store, "codex", "changed", source, "signature_mismatch")
	if err != nil {
		t.Fatal(err)
	}
	pending, err := QueueQuarantineForDetection(home, store, quarantine.ID)
	if err != nil {
		t.Fatal(err)
	}

	// A trusted version may have been installed at the original path while a
	// stale disabled record remains visible. Discard must never delete it.
	writeSkill(t, source, "trusted")
	if _, err := store.DiscardPending(pending.ID); err != nil {
		t.Fatal(err)
	}
	content, err := os.ReadFile(filepath.Join(source, "SKILL.md"))
	if err != nil || string(content) != "---\nname: trusted\ndescription: test\n---\n" {
		t.Fatalf("installed Skill was changed: %q %v", content, err)
	}
	if _, err := os.Stat(pending.PendingPath); !os.IsNotExist(err) {
		t.Fatalf("pending copy still exists: %v", err)
	}
	if _, err := os.Stat(quarantine.QuarantinePath); !os.IsNotExist(err) {
		t.Fatalf("linked quarantine copy still exists: %v", err)
	}
	if items, err := store.PendingItems(); err != nil || len(items) != 0 {
		t.Fatalf("pending record still exists: %#v %v", items, err)
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 0 {
		t.Fatalf("quarantine record still exists: %#v %v", items, err)
	}
}

func TestDiscardPendingOnlyRemovesSelectedAgentCopy(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	items := []PendingItem{
		{ID: "codex-copy", AgentType: "codex", SkillName: "demo", OriginalPath: filepath.Join(home, ".codex", "skills", "demo"), PendingPath: filepath.Join(home, "pending", "codex")},
		{ID: "claude-copy", AgentType: "claude-code", SkillName: "demo", OriginalPath: filepath.Join(home, ".claude", "skills", "demo"), PendingPath: filepath.Join(home, "pending", "claude")},
	}
	for _, item := range items {
		writeSkill(t, item.PendingPath, item.SkillName)
		if err := store.SavePending(item); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := store.DiscardPending(items[0].ID); err != nil {
		t.Fatal(err)
	}
	remaining, err := store.PendingItems()
	if err != nil || len(remaining) != 1 || remaining[0].ID != items[1].ID {
		t.Fatalf("discard affected another Agent copy: %#v %v", remaining, err)
	}
	if _, err := os.Stat(items[1].PendingPath); err != nil {
		t.Fatalf("another Agent copy was deleted: %v", err)
	}
}

func TestResolveInstalledRecoveryRequiresExactPathAndMatchingUninstalledSignature(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	target := filepath.Join(home, ".hermes", "skills", "demo")
	otherTarget := filepath.Join(home, ".codex", "skills", "demo")
	writeSkill(t, target, "demo")
	first, err := QuarantineSkill(home, store, "hermes", "demo", target, "manual")
	if err != nil {
		t.Fatal(err)
	}
	writeSkill(t, otherTarget, "demo")
	second, err := QuarantineSkill(home, store, "codex", "demo", otherTarget, "manual")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`UPDATE client_quarantine SET status='uninstalled' WHERE id IN (?,?)`, first.ID, second.ID); err != nil {
		t.Fatal(err)
	}
	items, err := store.QuarantineItems()
	if err != nil {
		t.Fatal(err)
	}
	var signature string
	for _, item := range items {
		if item.ID == first.ID {
			signature = item.Signature
		}
	}
	if changed, err := store.ResolveInstalledRecovery("hermes", "demo", target, "different"); err != nil || changed {
		t.Fatalf("different version resolved: %v %v", changed, err)
	}
	if changed, err := store.ResolveInstalledRecovery("hermes", "demo", target, signature); err != nil || !changed {
		t.Fatalf("matching installed copy was not resolved: %v %v", changed, err)
	}
	remaining, err := store.QuarantineItems()
	if err != nil || len(remaining) != 1 || remaining[0].ID != second.ID {
		t.Fatalf("unrelated Agent copy changed: %#v %v", remaining, err)
	}
}

func TestDiscardQuarantineKeepsCurrentInstalledSkillAndAuditRow(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	target := filepath.Join(home, ".hermes", "skills", "demo")
	writeSkill(t, target, "untrusted")
	item, err := QuarantineSkill(home, store, "hermes", "demo", target, "manual")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`UPDATE client_quarantine SET status='uninstalled' WHERE id=?`, item.ID); err != nil {
		t.Fatal(err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 {
		t.Fatal(items, err)
	}
	writeSkill(t, target, "trusted")
	if _, err := store.DiscardQuarantine(item.ID, "wrong"); err == nil || err.Error() != "skill_content_changed" {
		t.Fatalf("signature mismatch was accepted: %v", err)
	}
	if _, err := os.Stat(item.QuarantinePath); err != nil {
		t.Fatalf("copy changed after rejected confirmation: %v", err)
	}
	if _, err := store.DiscardQuarantine(item.ID, items[0].Signature); err != nil {
		t.Fatal(err)
	}
	content, err := os.ReadFile(filepath.Join(target, "SKILL.md"))
	if err != nil || !strings.Contains(string(content), "name: trusted") {
		t.Fatalf("current installed Skill changed: %q %v", content, err)
	}
	if _, err := os.Stat(item.QuarantinePath); !os.IsNotExist(err) {
		t.Fatalf("retained copy still exists: %v", err)
	}
	var status string
	if err := store.db.QueryRow(`SELECT status FROM client_quarantine WHERE id=?`, item.ID).Scan(&status); err != nil || status != "discarded" {
		t.Fatalf("audit row not retained: %q %v", status, err)
	}
}

func TestQueuedEventsPersistUntilDeleted(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.QueueEvent(QueuedEvent{ClientID: "host", EventType: "skill_modified", Details: map[string]any{"offline": true}}); err != nil {
		t.Fatal(err)
	}
	items, err := store.QueuedEvents()
	if err != nil || len(items) != 1 || items[0].Details["offline"] != true {
		t.Fatalf("unexpected queued events: %#v %v", items, err)
	}
	if err := store.DeleteQueuedEvent(items[0].ID); err != nil {
		t.Fatal(err)
	}
	items, _ = store.QueuedEvents()
	if len(items) != 0 {
		t.Fatalf("event was not deleted: %#v", items)
	}
}
