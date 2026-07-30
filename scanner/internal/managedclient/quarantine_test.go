package managedclient

import (
	"os"
	"path/filepath"
	"testing"
)

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
