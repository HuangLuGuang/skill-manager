package managedclient

import (
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestOpenStoreMigratesPendingVersionFields(t *testing.T) {
	path := filepath.Join(t.TempDir(), "client.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE client_pending (
		id TEXT PRIMARY KEY,
		agent_type TEXT NOT NULL,
		skill_name TEXT NOT NULL,
		original_path TEXT NOT NULL,
		pending_path TEXT NOT NULL UNIQUE,
		reason TEXT NOT NULL,
		status TEXT NOT NULL,
		skill_id TEXT,
		created_at TEXT NOT NULL,
		submitted_at TEXT
	)`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}

	store, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.db.Exec(`INSERT INTO client_pending(
		id, agent_type, skill_name, original_path, pending_path, reason, status, version_id, content_fingerprint, created_at
	) VALUES('pending-1', 'codex', 'demo', '', '/tmp/demo', 'test', 'pending', 'version-2', 'sha256:test', '2026-07-23T00:00:00Z')`); err != nil {
		t.Fatalf("pending version migrations were not applied: %v", err)
	}
}

func TestOpenStoreCollapsesExistingRepeatedGovernanceNotificationsOnce(t *testing.T) {
	path := filepath.Join(t.TempDir(), "client.db")
	store, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`DELETE FROM client_state WHERE key = 'migration:collapse-repeated-governance-notifications-v1'`); err != nil {
		t.Fatal(err)
	}
	for _, values := range []struct {
		eventType, signature, delivered string
	}{
		{"skill_governance_detected", "same", "2026-09-14T01:00:01Z"},
		{"skill_governance_detected", "same", ""},
		{"skill_governance_detected", "same", ""},
		{"skill_governance_detected", "changed", ""},
		{"skill_auto_install_failed", "same", ""},
	} {
		details, _ := json.Marshal(map[string]string{"signature": values.signature})
		if _, err := store.db.Exec(`INSERT INTO client_notifications(
			severity,event_type,agent_type,skill_name,title,message,created_at,delivered_at,details_json
		) VALUES('warning',?,'codex','sample','title','message','2026-09-14T01:00:00Z',NULLIF(?,''),?)`, values.eventType, values.delivered, string(details)); err != nil {
			t.Fatal(err)
		}
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	items, err := store.Notifications(20)
	if err != nil || len(items) != 3 {
		t.Fatalf("repeated notification migration failed: %#v %v", items, err)
	}
	pending, err := store.PendingNotifications(20)
	if err != nil || len(pending) != 2 {
		t.Fatalf("migration did not remove the delivered incident backlog: %#v %v", pending, err)
	}
	if _, err := store.db.Exec(`INSERT INTO client_notifications(
		severity,event_type,agent_type,skill_name,title,message,created_at,details_json
	) VALUES('warning','skill_governance_detected','codex','sample','title','message','2026-09-14T02:00:00Z','{"signature":"same"}')`); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	items, err = store.Notifications(20)
	if err != nil || len(items) != 4 {
		t.Fatalf("one-time migration collapsed a later incident: %#v %v", items, err)
	}
}

func TestStorePersistsInventoryAndCompletedTasks(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	var busyTimeout int
	if err := store.db.QueryRow(`PRAGMA busy_timeout`).Scan(&busyTimeout); err != nil || busyTimeout != 5000 {
		t.Fatalf("unexpected busy timeout: %d %v", busyTimeout, err)
	}
	if err := store.SaveInventory(Inventory{ClientID: "client-1"}); err != nil {
		t.Fatal(err)
	}
	body, ok, err := store.State("inventory")
	var cached Inventory
	if err != nil || !ok || json.Unmarshal([]byte(body), &cached) != nil || cached.DiscoveryVersion != InventoryCacheVersion {
		t.Fatalf("inventory cache version was not persisted: %q %v %v", body, ok, err)
	}
	if err := store.SaveTask(Task{ID: 7, TaskType: "install_skill", Payload: map[string]any{"skill_name": "demo"}}, "succeeded", ""); err != nil {
		t.Fatal(err)
	}
	managedPath := filepath.Join(t.TempDir(), "managed")
	if err := store.SaveInstall(Installation{
		AgentType:  "codex",
		SkillID:    "skill-1",
		SkillName:  "managed",
		TargetPath: managedPath,
		Manifest:   releaseManifest{Name: "managed", VersionID: "version-2", VersionNo: 2, SourceVersion: "1.4.0"},
	}); err != nil {
		t.Fatal(err)
	}
	inventory := Inventory{Agents: []Agent{{
		AgentType: "codex",
		Skills:    []Skill{{Name: "managed", Path: managedPath, Status: "observed"}},
	}}}
	if err := store.EnrichInventory(&inventory); err != nil {
		t.Fatal(err)
	}
	if got := inventory.Agents[0].Skills[0]; got.SkillID != "skill-1" || got.VersionID != "version-2" || got.VersionNo != 2 || got.SourceVersion != "1.4.0" || got.Status != "managed" {
		t.Fatalf("installation metadata was not merged into inventory: %#v", got)
	}
	completed, err := store.TaskCompleted(7)
	if err != nil || !completed {
		t.Fatalf("task was not persisted: completed=%v err=%v", completed, err)
	}
	tasks, err := store.TaskHistory(10)
	if err != nil || len(tasks) != 1 || tasks[0].TaskType != "install_skill" || tasks[0].Payload["skill_name"] != "demo" {
		t.Fatalf("unexpected task history: %#v %v", tasks, err)
	}
	due, err := store.Due("full", time.Hour)
	if err != nil || !due {
		t.Fatalf("first schedule should be due: %v %v", due, err)
	}
	if err := store.MarkSchedule("full"); err != nil {
		t.Fatal(err)
	}
	due, err = store.Due("full", time.Hour)
	if err != nil || due {
		t.Fatalf("recent schedule should not be due: %v %v", due, err)
	}
	policy, _ := json.Marshal(Policy{FullScanSeconds: 120})
	if err := store.SetState("policy", string(policy)); err != nil {
		t.Fatal(err)
	}
	if err := store.MarkSchedule("patrol:full"); err != nil {
		t.Fatal(err)
	}
	status, err := store.LocalStatus()
	last, lastErr := time.Parse(time.RFC3339Nano, status.LastFullScanAt)
	next, nextErr := time.Parse(time.RFC3339Nano, status.NextFullScanAt)
	if err != nil || lastErr != nil || nextErr != nil || next.Sub(last) != 2*time.Minute {
		t.Fatalf("unexpected patrol schedule: %#v %v %v %v", status, err, lastErr, nextErr)
	}
}

func TestSaveInstallReplacesStaleIdentityForSameAgentPath(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	target := filepath.Join(t.TempDir(), ".codex", "skills", "safe")
	for _, install := range []Installation{
		{AgentType: "codex", SkillID: "family-1", SkillName: "safe", TargetPath: target, Manifest: releaseManifest{VersionID: "version-1"}},
		{AgentType: "codex", SkillID: "family-2", SkillName: "safe", TargetPath: target, Manifest: releaseManifest{VersionID: "version-2"}},
	} {
		if err := store.SaveInstall(install); err != nil {
			t.Fatal(err)
		}
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 1 || installs[0].SkillID != "family-2" {
		t.Fatalf("stale target identity was retained: %#v %v", installs, err)
	}
}

func TestResolvePendingForInstallOnlyClearsMatchingAgentPath(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	target := filepath.Join(home, ".claude", "skills", "google-scholar-search")
	items := []PendingItem{
		{ID: "matching", AgentType: "claude-code", SkillName: "google-scholar-search", OriginalPath: target, PendingPath: filepath.Join(home, "pending", "matching"), Status: "REJECTED"},
		{ID: "other-agent", AgentType: "opencode", SkillName: "google-scholar-search", OriginalPath: filepath.Join(home, ".opencode", "skills", "google-scholar-search"), PendingPath: filepath.Join(home, "pending", "other-agent"), Status: "REJECTED"},
		{ID: "other-path", AgentType: "claude-code", SkillName: "google-scholar-search", OriginalPath: filepath.Join(home, "custom", "google-scholar-search"), PendingPath: filepath.Join(home, "pending", "other-path"), Status: "REJECTED"},
	}
	for _, item := range items {
		if err := os.MkdirAll(item.PendingPath, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := store.SavePending(item); err != nil {
			t.Fatal(err)
		}
	}

	if err := store.ResolvePendingForInstall("claude-code", "google-scholar-search", target); err != nil {
		t.Fatal(err)
	}

	remaining, err := store.PendingItems()
	if err != nil {
		t.Fatal(err)
	}
	if len(remaining) != 2 {
		t.Fatalf("unexpected pending count after trusted install: %#v", remaining)
	}
	for _, item := range remaining {
		if item.ID == "matching" {
			t.Fatalf("matching pending record was not resolved: %#v", remaining)
		}
	}
	if _, err := os.Stat(items[0].PendingPath); !os.IsNotExist(err) {
		t.Fatalf("resolved pending content was not removed: %v", err)
	}
}
