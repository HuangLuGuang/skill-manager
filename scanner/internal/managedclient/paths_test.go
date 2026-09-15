package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestWriteUIStateSignalUsesAtomicRuntimeMarker(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(RuntimeRoot(home), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := WriteUIStateSignal(home, "local_state_changed"); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(UIStateSignalPath(home))
	if err != nil {
		t.Fatal(err)
	}
	var signal UIStateSignal
	if err := json.Unmarshal(body, &signal); err != nil {
		t.Fatal(err)
	}
	if signal.Revision == "" || signal.CreatedAt == "" || signal.EventType != "local_state_changed" {
		t.Fatalf("unexpected UI state signal: %#v", signal)
	}
	info, err := os.Stat(UIStateSignalPath(home))
	if err != nil || info.Mode().Perm()&0o077 != 0 {
		t.Fatalf("UI state signal permissions are too broad: %v %v", info, err)
	}
}

func TestEnsureDataLayoutMigratesLegacyContent(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows keeps legacy directories because directory symlinks require elevated privileges")
	}
	home := t.TempDir()
	legacySkill := filepath.Join(RuntimeRoot(home), "skills", "skill-1", "release")
	writeSkill(t, legacySkill, "safe-skill")

	if err := EnsureDataLayout(home); err != nil {
		t.Fatal(err)
	}

	currentSkill := filepath.Join(ManagedSkillsRoot(home), "skill-1", "release", "SKILL.md")
	if _, err := os.Stat(currentSkill); err != nil {
		t.Fatalf("legacy Skill was not migrated: %v", err)
	}
	legacyInfo, err := os.Lstat(legacyContentRoot(home, "skills"))
	if err != nil || legacyInfo.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("legacy compatibility link was not created: %v", err)
	}
	if _, err := os.Stat(filepath.Join(legacySkill, "SKILL.md")); err != nil {
		t.Fatalf("legacy path no longer resolves: %v", err)
	}
}

func TestEnsureDataLayoutRecreatesCompatibilityLinks(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows does not create directory compatibility links")
	}
	home := t.TempDir()
	writeSkill(t, filepath.Join(ManagedSkillsRoot(home), "skill-1", "release"), "safe-skill")

	if err := EnsureDataLayout(home); err != nil {
		t.Fatal(err)
	}
	if err := os.RemoveAll(RuntimeRoot(home)); err != nil {
		t.Fatal(err)
	}
	if err := EnsureDataLayout(home); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(legacyContentRoot(home, "skills"), "skill-1", "release", "SKILL.md")); err != nil {
		t.Fatalf("compatibility path was not recreated: %v", err)
	}
}

func TestMigratedPendingContentIsListedOnce(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows keeps legacy directories instead of creating compatibility links")
	}
	home := t.TempDir()
	writeSkill(t, filepath.Join(RuntimeRoot(home), "pending", "codex", "safe-skill"), "safe-skill")
	if err := EnsureDataLayout(home); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(RuntimeRoot(home), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	items, err := store.PendingItems()
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("migrated pending Skill was duplicated: %#v", items)
	}
}

func TestManagedRootsRecognizeCurrentAndLegacyLinks(t *testing.T) {
	home := t.TempDir()
	for _, target := range []string{
		filepath.Join(ManagedSkillsRoot(home), "skill-1", "release"),
		filepath.Join(legacyContentRoot(home, "skills"), "skill-1", "release"),
	} {
		link := filepath.Join(t.TempDir(), "safe-skill")
		if err := os.Symlink(target, link); err != nil {
			t.Fatal(err)
		}
		if !brokenManagedSymlink(home, link) {
			t.Fatalf("managed link was not recognized: %s", target)
		}
	}
}
