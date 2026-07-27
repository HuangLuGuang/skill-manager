package managedclient

import (
	"database/sql"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"
)

func TestOpenStoreMigratesPendingContentFingerprint(t *testing.T) {
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
		id, agent_type, skill_name, original_path, pending_path, reason, status, content_fingerprint, created_at
	) VALUES('pending-1', 'codex', 'demo', '', '/tmp/demo', 'test', 'pending', 'sha256:test', '2026-07-23T00:00:00Z')`); err != nil {
		t.Fatalf("content_fingerprint migration was not applied: %v", err)
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
		Manifest:   releaseManifest{Name: "managed"},
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
	if got := inventory.Agents[0].Skills[0]; got.SkillID != "skill-1" || got.Status != "managed" {
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
