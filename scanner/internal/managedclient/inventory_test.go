package managedclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"skill-manager/scanner/internal/manifest"
)

func TestDiscoverFindsSupportedAgentsAndSkills(t *testing.T) {
	home := t.TempDir()
	roots := map[string]string{
		"claude-code":   ".claude/skills",
		"codex":         ".codex/skills",
		"gemini":        ".gemini/skills",
		"opencode":      ".config/opencode/skills",
		"openclaw":      ".openclaw/skills",
		"hermes":        ".hermes/skills",
		"trae-cn":       ".trae-cn/skills",
		"trae":          ".trae/skills",
		"cursor":        ".cursor/skills",
		"global-skills": ".agents/skills",
		"codebuddy":     ".codebuddy/skills",
		"workbuddy":     ".workbuddy/skills",
	}
	for agentType, root := range roots {
		writeSkill(t, filepath.Join(home, filepath.FromSlash(root), agentType+"-skill"), agentType+"-skill")
	}
	writeSkill(t, filepath.Join(home, ".opencode", "skills", "opencode-user-skill"), "opencode-user-skill")
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
	if len(inventory.Agents) != 13 {
		t.Fatalf("expected 13 agents, got %#v", inventory.Agents)
	}
	if inventory.Agents[0].AgentType != "global-skills" {
		t.Fatalf("global Skills must be listed first: %#v", inventory.Agents)
	}
	byType := map[string]Agent{}
	for _, agent := range inventory.Agents {
		byType[agent.AgentType] = agent
	}
	if got := byType["codex"].Skills[0].Name; got != "codex-skill" {
		t.Fatalf("unexpected codex skill %q", got)
	}
	if shared, _ := byType["global-skills"].Capabilities["shared_skills"].(bool); !shared {
		t.Fatalf("global Skills directory was not marked shared: %#v", byType["global-skills"])
	}
	for agentType := range roots {
		agent := byType[agentType]
		if !agent.SkillManagementSupported {
			t.Fatalf("%s must support skill management", agentType)
		}
		expected := 1
		if agentType == "opencode" {
			expected = 2
		}
		if len(agent.Skills) != expected {
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

func TestDiscoverSkipsBinaryWithoutAgentDirectory(t *testing.T) {
	home := t.TempDir()
	bin := t.TempDir()
	path := filepath.Join(bin, "test-agent")
	if err := os.WriteFile(path, []byte("#!/bin/sh\necho test\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)
	spec := adapter{agentType: "test", binaries: []string{"test-agent"}, skillRoots: []string{".test-agent/skills"}, supportsSkill: true}

	if _, found, err := discoverAgent(home, spec, DefaultManifestOptions()); err != nil || found {
		t.Fatalf("binary without Agent directory should be hidden: found=%v err=%v", found, err)
	}
	if err := os.MkdirAll(filepath.Join(home, ".test-agent"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, found, err := discoverAgent(home, spec, DefaultManifestOptions()); err != nil || !found {
		t.Fatalf("Agent directory should make Agent visible: found=%v err=%v", found, err)
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

func TestDiscoverDeduplicatesCustomAgentUsingBuiltinRoot(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, ".trae-cn", "skills")
	writeSkill(t, filepath.Join(root, "code-review"), "code-review")
	if err := SaveConfig(home, Config{
		Server: "http://agent-manager",
		Token:  "token",
		CustomAgents: []CustomAgentConfig{{
			AgentType:  "custom-trae",
			Name:       "Trae IDE",
			SkillsPath: root,
		}},
	}); err != nil {
		t.Fatal(err)
	}

	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || inventory.Agents[0].AgentType != "trae-cn" {
		t.Fatalf("duplicate custom Agent should be hidden in favor of built-in Agent: %#v", inventory.Agents)
	}
	if _, err := AddCustomAgent(home, "Trae IDE", root); err == nil || !strings.Contains(err.Error(), "内置 Agent trae-cn") {
		t.Fatalf("expected duplicate built-in directory error, got %v", err)
	}
}

func TestBuiltinAgentSkillRootsCanBeCustomizedAndReset(t *testing.T) {
	home := t.TempDir()
	if err := SaveConfig(home, Config{Server: "http://agent-manager", Token: "token"}); err != nil {
		t.Fatal(err)
	}
	defaultRoot := filepath.Join(home, ".codex", "skills")
	customRoot := filepath.Join(home, "custom-codex-skills")
	writeSkill(t, filepath.Join(defaultRoot, "default-skill"), "default-skill")
	writeSkill(t, filepath.Join(customRoot, "custom-skill"), "custom-skill")

	if err := SetBuiltinAgentRoots(home, "codex", []string{customRoot}); err != nil {
		t.Fatal(err)
	}
	settings, err := BuiltinAgentSettings(home)
	if err != nil {
		t.Fatal(err)
	}
	var codex BuiltinAgentSetting
	for _, item := range settings {
		if item.AgentType == "codex" {
			codex = item
			break
		}
	}
	if !codex.Customized || len(codex.CurrentRoots) != 1 || codex.CurrentRoots[0] != customRoot || codex.DefaultRoots[0] != defaultRoot {
		t.Fatalf("unexpected customized setting: %#v", codex)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || inventory.Agents[0].AgentType != "codex" || inventory.Agents[0].Skills[0].Name != "custom-skill" {
		t.Fatalf("custom root was not used for discovery: %#v", inventory.Agents)
	}

	if err := ResetBuiltinAgentRoots(home, "codex"); err != nil {
		t.Fatal(err)
	}
	inventory, err = Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || inventory.Agents[0].Skills[0].Name != "default-skill" {
		t.Fatalf("default root was not restored: %#v", inventory.Agents)
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
