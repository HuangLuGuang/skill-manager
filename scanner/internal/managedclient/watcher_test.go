package managedclient

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestInstallationStagingIsOutsideWatchRoots(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(RuntimeRoot(home), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	staging, err := newInstallStaging(home)
	if err != nil {
		t.Fatal(err)
	}
	writeSkill(t, filepath.Join(staging, "release.tmp"), "demo")
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	for root := range watcher.roots {
		if pathWithinLexical(staging, root) {
			t.Fatalf("staging is watched by %s", root)
		}
	}
}

func TestSkillWatcherDetectsFileChange(t *testing.T) {
	if skillWatchDebounce > 500*time.Millisecond {
		t.Fatalf("Skill change debounce is too slow: %s", skillWatchDebounce)
	}
	home := t.TempDir()
	root := filepath.Join(home, ".codex", "skills", "demo")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("name: demo\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	select {
	case paths := <-watcher.Changes():
		if len(paths) == 0 || filepath.Clean(paths[0]) != filepath.Join(root, "SKILL.md") {
			t.Fatalf("watcher discarded the changed path: %#v", paths)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Skill file change did not wake the watcher")
	}
}

func TestSkillWatcherDetectsNewStandardSkillRoot(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(home, ".codex", "skills", "new-skill")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("name: new-skill\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	select {
	case <-watcher.Changes():
	case <-time.After(3 * time.Second):
		t.Fatal("new standard Skill root did not wake the watcher")
	}
}

func TestSkillWatcherDetectsNewDynamicAgentSkillRoot(t *testing.T) {
	home := t.TempDir()
	users := filepath.Join(home, ".config", "TeleAgent", "users")
	if err := os.MkdirAll(users, 0o755); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(users, "new-user", "skills", "new-skill")
	writeSkill(t, root, "new-skill")
	select {
	case paths := <-watcher.Changes():
		if len(paths) == 0 {
			t.Fatal("dynamic Skill creation produced no changed paths")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("new dynamic Agent Skill root did not wake the watcher")
	}
}

func TestSkillWatcherDetectsNewSkillInConfiguredAgentRoot(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, "configured-skills")
	if err := SaveConfig(home, Config{Server: "http://manager.invalid", Token: "test", AgentSkillRoots: map[string][]string{"codex": {root}}}); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	writeSkill(t, filepath.Join(root, "new-skill"), "new-skill")
	select {
	case <-watcher.Changes():
	case <-time.After(3 * time.Second):
		t.Fatal("configured Agent Skill root did not wake the watcher")
	}
}

func TestSkillWatcherIgnoresChangesOutsideSkillRoots(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, "unrelated.txt"), []byte("unrelated"), 0o644); err != nil {
		t.Fatal(err)
	}
	select {
	case <-watcher.Changes():
		t.Fatal("unrelated home directory change woke the Skill watcher")
	case <-time.After(1500 * time.Millisecond):
	}
}

func TestSkillWatcherSuppressesClientOwnedChangesByRoot(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, ".codex", "skills", "demo")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	watcher, err := NewSkillWatcher()
	if err != nil {
		t.Fatal(err)
	}
	defer watcher.Close()
	if err := watcher.Refresh(home, store); err != nil {
		t.Fatal(err)
	}
	watcher.SuppressRoots([]string{root}, time.Second)
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("name: demo\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	select {
	case paths := <-watcher.Changes():
		t.Fatalf("client-owned change triggered another patrol: %#v", paths)
	case <-time.After(700 * time.Millisecond):
	}
}

func TestNotificationsAreRelevantAndDeduplicated(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	if _, ok := notificationForEvent("skill_modified", "codex", "demo", map[string]any{"mode": "repair"}); ok {
		t.Fatal("intermediate modification should not notify before automatic repair")
	}
	if _, ok := notificationForEvent("skill_modified", "codex", "demo", map[string]any{"mode": "repair", "offline": true}); !ok {
		t.Fatal("offline repair failure should notify")
	}
	if _, ok := notificationForEvent("unmanaged_skill_found", "codex", "demo", map[string]any{"mode": "repair"}); !ok {
		t.Fatal("unmanaged Skill left in place should notify")
	}
	item, ok := notificationForEvent("skill_repaired", "codex", "demo", nil)
	if !ok || item.Title != "Skill 已自动恢复" || item.Severity != "info" {
		t.Fatalf("unexpected notification: %#v", item)
	}
	if err := store.RecordNotification(item); err != nil {
		t.Fatal(err)
	}
	if err := store.RecordNotification(item); err != nil {
		t.Fatal(err)
	}
	items, err := store.Notifications(10)
	if err != nil || len(items) != 1 {
		t.Fatalf("duplicate notification was not suppressed: %#v %v", items, err)
	}
	status, err := store.LocalStatus()
	if err != nil || status.UnreadNotifications != 1 {
		t.Fatalf("unexpected unread count: %#v %v", status, err)
	}
	if err := store.MarkNotificationsRead(); err != nil {
		t.Fatal(err)
	}
	status, err = store.LocalStatus()
	if err != nil || status.UnreadNotifications != 0 {
		t.Fatalf("notifications were not marked read: %#v %v", status, err)
	}
	if err := store.ClearNotifications(); err != nil {
		t.Fatal(err)
	}
	status, err = store.LocalStatus()
	if err != nil || len(status.Notifications) != 0 {
		t.Fatalf("notifications were not cleared: %#v %v", status, err)
	}
}
