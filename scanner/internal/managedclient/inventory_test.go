package managedclient

import (
	"os"
	"path/filepath"
	"testing"

	"skill-manager/scanner/internal/manifest"
)

func TestDiscoverFindsSupportedAgentsAndSkills(t *testing.T) {
	home := t.TempDir()
	roots := map[string]string{
		"claude-code": ".claude/skills",
		"codex":       ".codex/skills",
		"gemini":      ".gemini/skills",
		"opencode":    ".config/opencode/skills",
		"openclaw":    ".openclaw/skills",
		"hermes":      ".hermes/skills",
	}
	for agentType, root := range roots {
		writeSkill(t, filepath.Join(home, filepath.FromSlash(root), agentType+"-skill"), agentType+"-skill")
	}
	customRoot := filepath.Join(home, "custom-agent", "skills")
	writeSkill(t, filepath.Join(customRoot, "custom-skill"), "custom-skill")
	if err := SaveConfig(home, Config{Server: "http://agent-manager", Token: "token"}); err != nil {
		t.Fatal(err)
	}
	custom, err := AddCustomAgent(home, "内部助手", customRoot)
	if err != nil {
		t.Fatal(err)
	}

	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 7 {
		t.Fatalf("expected 7 agents, got %#v", inventory.Agents)
	}
	byType := map[string]Agent{}
	for _, agent := range inventory.Agents {
		byType[agent.AgentType] = agent
	}
	if got := byType["codex"].Skills[0].Name; got != "codex-skill" {
		t.Fatalf("unexpected codex skill %q", got)
	}
	for agentType := range roots {
		agent := byType[agentType]
		if !agent.SkillManagementSupported {
			t.Fatalf("%s must support skill management", agentType)
		}
		if len(agent.Skills) != 1 {
			t.Fatalf("%s skill discovery failed: %#v", agentType, byType[agentType])
		}
	}
	if got := byType[custom.AgentType]; got.DisplayName != "内部助手" || got.SkillsPath != custom.SkillsPath || len(got.Skills) != 1 {
		t.Fatalf("custom Agent discovery failed: %#v", got)
	}
	if inventory.ClientID != DeviceID(inventory.Hostname, home) {
		t.Fatal("device ID is not stable")
	}
}

func TestRemoveCustomAgentKeepsSkillDirectory(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, "other-agent", "skills")
	writeSkill(t, filepath.Join(root, "kept-skill"), "kept-skill")
	if err := SaveConfig(home, Config{Server: "http://agent-manager", Token: "token"}); err != nil {
		t.Fatal(err)
	}
	item, err := AddCustomAgent(home, "Other Agent", root)
	if err != nil {
		t.Fatal(err)
	}
	if err := RemoveCustomAgent(home, item.AgentType); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "kept-skill", "SKILL.md")); err != nil {
		t.Fatalf("removing custom Agent touched its Skill directory: %v", err)
	}
	config, err := LoadConfig(home)
	if err != nil || len(config.CustomAgents) != 0 {
		t.Fatalf("custom Agent config was not removed: %#v %v", config.CustomAgents, err)
	}
}

func TestDiscoverIncludesUserOwnedSymlinkedSkill(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, ".codex", "skills")
	outside := filepath.Join(home, "outside")
	writeSkill(t, outside, "outside")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "linked")); err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || len(inventory.Agents[0].Skills) != 1 {
		t.Fatalf("user-owned symlinked skill was not discovered: %#v", inventory.Agents)
	}
	resolved, err := filepath.EvalSymlinks(outside)
	if err != nil {
		t.Fatal(err)
	}
	if inventory.Agents[0].Skills[0].SourceTarget != resolved {
		t.Fatalf("symlink target was not preserved: %#v", inventory.Agents[0].Skills[0])
	}
}

func TestDiscoverSkipsSymlinkOutsideUserHome(t *testing.T) {
	home := t.TempDir()
	outside := t.TempDir()
	writeSkill(t, outside, "outside")
	root := filepath.Join(home, ".codex", "skills")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "linked")); err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || len(inventory.Agents[0].Skills) != 0 {
		t.Fatalf("external symlink escaped user home: %#v", inventory.Agents)
	}
}

func TestDiscoverIncludesManagedSymlink(t *testing.T) {
	home := t.TempDir()
	store := filepath.Join(home, ".agent-manager", "skills", "skill-1", "abc")
	writeSkill(t, store, "managed")
	root := filepath.Join(home, ".codex", "skills")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(store, filepath.Join(root, "managed")); err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || len(inventory.Agents[0].Skills) != 1 {
		t.Fatalf("managed symlink was not discovered: %#v", inventory.Agents)
	}
}

func TestReadSkillsKeepsSkillWhenSignatureLimitsAreExceeded(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, ".codex", "skills")
	skill := filepath.Join(root, "large")
	writeSkill(t, skill, "large")
	if err := os.WriteFile(filepath.Join(skill, "extra.txt"), []byte("extra"), 0o644); err != nil {
		t.Fatal(err)
	}
	items, err := readSkills(root, filepath.Join(home, ".agent-manager", "skills"), manifest.Options{MaxFiles: 1})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Name != "large" || items[0].Status != "unscannable" || items[0].Error == "" {
		t.Fatalf("large skill should remain visible: %#v", items)
	}
}

func writeSkill(t *testing.T, path, name string) {
	t.Helper()
	if err := os.MkdirAll(path, 0o755); err != nil {
		t.Fatal(err)
	}
	content := "---\nname: " + name + "\ndescription: test\n---\n"
	if err := os.WriteFile(filepath.Join(path, "SKILL.md"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}
