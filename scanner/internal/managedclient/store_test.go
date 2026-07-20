package managedclient

import (
	"encoding/json"
	"path/filepath"
	"testing"
	"time"
)

func TestStorePersistsInventoryAndCompletedTasks(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SaveInventory(Inventory{ClientID: "client-1"}); err != nil {
		t.Fatal(err)
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
