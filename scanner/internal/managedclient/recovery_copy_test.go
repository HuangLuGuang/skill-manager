package managedclient

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestQuarantineRestorePreservesLinksAndIgnoredFiles(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	external := filepath.Join(home, "external.txt")
	if err := os.WriteFile(external, []byte("external unchanged"), 0600); err != nil {
		t.Fatal(err)
	}
	links := map[string]string{"internal": "SKILL.md", "external": external, "dangling": "missing", "directory": ".git"}
	for name, target := range links {
		if err := os.Symlink(target, filepath.Join(skill.Path, name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.MkdirAll(filepath.Join(skill.Path, ".git", "empty"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(skill.Path, ".git", "data"), []byte("retained"), 0600); err != nil {
		t.Fatal(err)
	}
	item, err := QuarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(skill.Path); !os.IsNotExist(err) {
		t.Fatalf("source not quarantined: %v", err)
	}
	for name, target := range links {
		if actual, err := os.Readlink(filepath.Join(item.QuarantinePath, name)); err != nil || actual != target {
			t.Fatalf("link %s lost: %q %v", name, actual, err)
		}
	}
	task := Task{ID: 1, TaskType: "skill_action", Payload: map[string]any{"action": "restore_quarantine", "source": "manual", "path": skill.Path, "expected_signature": skill.Signature, "quarantine_id": item.ID}}
	if err := restoreQuarantineTask(context.Background(), home, inventory, inventory.Agents[0], NewAPI("http://127.0.0.1:1", "fixture", time.Second), store, task); err != nil {
		t.Fatal(err)
	}
	for name, target := range links {
		if actual, err := os.Readlink(filepath.Join(skill.Path, name)); err != nil || actual != target {
			t.Fatalf("restored link %s lost: %q %v", name, actual, err)
		}
	}
	if b, err := os.ReadFile(filepath.Join(skill.Path, ".git", "data")); err != nil || string(b) != "retained" {
		t.Fatal("ignored file lost", err)
	}
	if info, err := os.Stat(filepath.Join(skill.Path, ".git", "empty")); err != nil || !info.IsDir() {
		t.Fatal("empty directory lost", err)
	}
	if b, err := os.ReadFile(external); err != nil || string(b) != "external unchanged" {
		t.Fatal("external target changed", err)
	}
}

func TestQuarantineCleansCopyAfterDatabaseFailure(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	locked := filepath.Join(skill.Path, ".git")
	if err := os.Mkdir(locked, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(locked, "data"), []byte("retain source"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(locked, 0500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(locked, 0700) })
	if _, err := store.db.Exec(`CREATE TRIGGER reject_quarantine BEFORE INSERT ON client_quarantine BEGIN SELECT RAISE(FAIL, 'storage failure'); END`); err != nil {
		t.Fatal(err)
	}
	for attempt := 0; attempt < 3; attempt++ {
		if _, err := QuarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual"); err == nil || !strings.Contains(err.Error(), "storage failure") {
			t.Fatalf("expected failed insert: %v", err)
		}
		entries, err := os.ReadDir(QuarantineRoot(home))
		if err != nil || len(entries) != 0 {
			t.Fatalf("abandoned backups: %v %v", entries, err)
		}
	}
	if b, err := os.ReadFile(filepath.Join(locked, "data")); err != nil || string(b) != "retain source" {
		t.Fatal("source changed", err)
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 0 {
		t.Fatal(items, err)
	}
}

func TestQuarantineRejectsOversizeIgnoredDataWithoutDeletingSource(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	if err := os.Mkdir(filepath.Join(skill.Path, ".git"), 0700); err != nil {
		t.Fatal(err)
	}
	file, err := os.Create(filepath.Join(skill.Path, ".git", "oversize"))
	if err != nil {
		t.Fatal(err)
	}
	err = file.Truncate(recoveryCopyMaxBytes + 1)
	file.Close()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := QuarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual"); err == nil || !strings.Contains(err.Error(), "skill_copy_limit_exceeded") {
		t.Fatal(err)
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal(err)
	}
	if entries, err := os.ReadDir(QuarantineRoot(home)); err != nil || len(entries) != 0 {
		t.Fatal(entries, err)
	}
}
