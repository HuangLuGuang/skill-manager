package managedclient

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestListAndPlanBackup(t *testing.T) {
	home := t.TempDir()
	backup := filepath.Join(home, ".agent-manager", "backups", "20260716T120000Z", "codex", "safe")
	writeSkill(t, backup, "safe")
	current := filepath.Join(home, ".codex", "skills", "safe")
	writeSkill(t, current, "changed")

	backups, err := ListBackups(home)
	if err != nil || len(backups) != 1 || backups[0].Name != "20260716T120000Z" {
		t.Fatalf("unexpected backups: %#v %v", backups, err)
	}
	release, err := AcquireMutationLock(home)
	if err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	_, blocked := RequestBackupRestore(context.Background(), home, backups[0].Name, "request", API{}, store)
	release()
	if blocked == nil || blocked.Error() != "skill_action_busy" {
		t.Fatalf("backup restore bypassed an in-flight file operation: %v", blocked)
	}
	untouched, err := os.ReadFile(filepath.Join(current, "SKILL.md"))
	if err != nil || !strings.Contains(string(untouched), "name: changed") {
		t.Fatal("blocked restore modified current content", err)
	}
	if _, err := PlanBackupRestore(home, backups[0].Name); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(current, "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: changed") {
		t.Fatalf("planning modified the current content: %q %v", body, err)
	}
	if _, err := PlanBackupRestore(home, "../escape"); err == nil {
		t.Fatal("unsafe backup name was accepted")
	}

	outside := filepath.Join(home, "outside-backup")
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(home, ".agent-manager", "backups", "linked")); err != nil {
		t.Fatal(err)
	}
	if _, err := PlanBackupRestore(home, "linked"); err == nil {
		t.Fatal("symlinked backup root was accepted")
	}
}

func TestPlanBackupSupportsCustomAgent(t *testing.T) {
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
	if _, err := PlanBackupRestore(home, "20260716T130000Z"); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(root, "safe", "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: changed") {
		t.Fatalf("custom Agent planning modified the current content: %q %v", body, err)
	}
}

func TestBackupWithUnknownAgentDoesNotSilentlyPlanPartialRestore(t *testing.T) {
	home := t.TempDir()
	const name = "20260911T130000Z"
	writeSkill(t, filepath.Join(BackupsRoot(home), name, "codex", "safe"), "safe")
	writeSkill(t, filepath.Join(BackupsRoot(home), name, "removed-custom-agent", "custom"), "custom")
	plan, err := PlanBackupRestore(home, name)
	if err == nil || err.Error() != "backup_agent_unavailable" || len(plan) != 0 {
		t.Fatal("unknown Agent was silently excluded from the restore", plan, err)
	}
}

func TestInstallBackupPlanUsesRecordedConfiguredRoot(t *testing.T) {
	home := t.TempDir()
	primary := filepath.Join(home, "primary")
	secondary := filepath.Join(home, "secondary")
	for _, root := range []string{primary, secondary} {
		writeSkill(t, filepath.Join(root, "safe"), "original")
	}
	if err := SaveConfig(home, Config{Server: "http://manager", Token: "test", AgentSkillRoots: map[string][]string{"codex": {primary, secondary}}}); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(secondary, "safe")
	backup, err := retainInstallBackup(home, target, target, "codex", "safe", "1:0")
	if err != nil {
		t.Fatal(err)
	}
	writeSkill(t, target, "replacement")
	plan, err := PlanBackupRestore(home, filepath.Base(backup))
	if err != nil || len(plan) != 1 || plan[0].Target != target {
		t.Fatal("incorrect original path", plan, err)
	}
	body, err := os.ReadFile(filepath.Join(target, "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: replacement") {
		t.Fatal("planning modified recorded target", string(body), err)
	}
	if _, err := os.Stat(filepath.Join(home, ".codex", "skills", "safe")); !os.IsNotExist(err) {
		t.Fatal("restore wrote to the default Agent directory", err)
	}
	writeSkill(t, filepath.Join(backup, "codex", "safe"), "tampered")
	writeSkill(t, target, "keep-current")
	if _, err := PlanBackupRestore(home, filepath.Base(backup)); err == nil || err.Error() != "skill_content_changed" {
		t.Fatal("changed backup was accepted", err)
	}
	body, err = os.ReadFile(filepath.Join(target, "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: keep-current") {
		t.Fatal("rejected backup modified active content", err)
	}
}
