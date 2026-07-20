package managedclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestListAndRestoreBackup(t *testing.T) {
	home := t.TempDir()
	backup := filepath.Join(home, ".agent-manager", "backups", "20260716T120000Z", "codex", "safe")
	writeSkill(t, backup, "safe")
	current := filepath.Join(home, ".codex", "skills", "safe")
	writeSkill(t, current, "changed")

	backups, err := ListBackups(home)
	if err != nil || len(backups) != 1 || backups[0].Name != "20260716T120000Z" {
		t.Fatalf("unexpected backups: %#v %v", backups, err)
	}
	if err := RestoreBackup(home, backups[0].Name); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(current, "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: safe") {
		t.Fatalf("backup was not restored: %q %v", body, err)
	}
	if err := RestoreBackup(home, "../escape"); err == nil {
		t.Fatal("unsafe backup name was accepted")
	}

	outside := filepath.Join(home, "outside-backup")
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(home, ".agent-manager", "backups", "linked")); err != nil {
		t.Fatal(err)
	}
	if err := RestoreBackup(home, "linked"); err == nil {
		t.Fatal("symlinked backup root was accepted")
	}
}

func TestRestoreBackupSupportsCustomAgent(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, "my-agent", "skills")
	writeSkill(t, filepath.Join(root, "safe"), "changed")
	if err := SaveConfig(home, Config{Server: "http://agent-manager", Token: "token"}); err != nil {
		t.Fatal(err)
	}
	agent, err := AddCustomAgent(home, "My Agent", root)
	if err != nil {
		t.Fatal(err)
	}
	writeSkill(t, filepath.Join(home, ".agent-manager", "backups", "20260716T130000Z", agent.AgentType, "safe"), "safe")
	if err := RestoreBackup(home, "20260716T130000Z"); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(root, "safe", "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: safe") {
		t.Fatalf("custom Agent backup was not restored: %q %v", body, err)
	}
}
