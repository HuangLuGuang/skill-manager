package managedclient

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestApplyPlatformScanEventsIgnoresOrphanAndAdvancesRevision(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	next, changed, err := applyPlatformScanEvents(store, []PlatformScanEvent{{
		Revision: 7, SkillID: "family", VersionID: "version", Status: "APPROVED",
	}}, 0)
	if err != nil || changed || next != 7 {
		t.Fatalf("orphan event was not ignored and advanced: next=%d changed=%v err=%v", next, changed, err)
	}
	if value, ok, _ := store.State("recovery:pending:missing"); ok || value != "" {
		t.Fatalf("orphan event unexpectedly queued recovery: %q", value)
	}
}

func TestApplyPlatformScanEventsOrdersAndStopsOnRetryableError(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SavePending(PendingItem{ID: "pending-1", SkillID: "family", VersionID: "version", Status: "PENDING", SkillName: "demo", PendingPath: home + "/pending"}); err != nil {
		t.Fatal(err)
	}
	next, changed, err := applyPlatformScanEvents(store, []PlatformScanEvent{
		{Revision: 3, SkillID: "family", VersionID: "version", Status: "APPROVED"},
		{Revision: 2, SkillID: "missing", VersionID: "missing", Status: "APPROVED"},
	}, 0)
	if err != nil || !changed || next != 3 {
		t.Fatalf("events were not ordered/applied: next=%d changed=%v err=%v", next, changed, err)
	}
	found, status, err := store.PendingStatus("family", "version")
	if err != nil || !found || status != "APPROVED" {
		t.Fatalf("approved status was not persisted: found=%v status=%q err=%v", found, status, err)
	}
	store.Close()
	if nextRevision, _, err := applyPlatformScanEvents(store, []PlatformScanEvent{
		{Revision: 4, SkillID: "family", VersionID: "version", Status: "REJECTED"},
		{Revision: 5, SkillID: "family", VersionID: "version", Status: "APPROVED"},
	}, next); err == nil || errors.Is(err, ErrPendingNotFound) || nextRevision != next {
		t.Fatalf("closed store error advanced past retryable event: revision=%d err=%v", nextRevision, err)
	}
}

func TestPlatformEventApplyPersistsRevisionAndWakeMarkers(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{ID: "pending-1", SkillID: "family", VersionID: "version", Status: "PENDING", SkillName: "demo", PendingPath: home + "/pending"}); err != nil {
		t.Fatal(err)
	}
	next, changed, err := applyPlatformScanEvents(store, []PlatformScanEvent{{Revision: 11, SkillID: "family", VersionID: "version", Status: "APPROVED"}}, 0)
	if err != nil || !changed || next != 11 {
		t.Fatalf("event apply failed: revision=%d changed=%v err=%v", next, changed, err)
	}
	if err := store.SetState("platform:scan-revision", "11"); err != nil {
		t.Fatal(err)
	}
	if value, ok, err := store.State("platform:scan-revision"); err != nil || !ok || value != "11" {
		t.Fatalf("scan revision not persisted: %q %v %v", value, ok, err)
	}
	if _, err := os.Stat(filepath.Join(RuntimeRoot(home), "worker-wake")); err != nil {
		t.Fatalf("worker wake marker missing: %v", err)
	}
	if _, err := os.Stat(UIStateSignalPath(home)); err != nil {
		t.Fatalf("UI signal marker missing: %v", err)
	}
}

func TestApplyPlatformScanEventsStopsOnTransientDatabaseError(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{ID: "pending-1", SkillID: "family", VersionID: "version", Status: "PENDING", SkillName: "demo", PendingPath: home + "/pending"}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`CREATE TRIGGER fail_pending_update BEFORE UPDATE OF status ON client_pending BEGIN SELECT RAISE(ABORT, 'transient_db'); END`); err != nil {
		t.Fatal(err)
	}
	events := []PlatformScanEvent{{Revision: 4, SkillID: "family", VersionID: "version", Status: "REJECTED"}, {Revision: 5, SkillID: "family", VersionID: "version", Status: "APPROVED"}}
	next, changed, err := applyPlatformScanEvents(store, events, 0)
	if err == nil || changed || next != 0 {
		t.Fatalf("transient failure was not held at current revision: next=%d changed=%v err=%v", next, changed, err)
	}
	if _, err := store.db.Exec(`DROP TRIGGER fail_pending_update`); err != nil {
		t.Fatal(err)
	}
	next, changed, err = applyPlatformScanEvents(store, events, next)
	if err != nil || !changed || next != 5 {
		t.Fatalf("retry did not process events in order: next=%d changed=%v err=%v", next, changed, err)
	}
}
