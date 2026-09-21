package managedclient

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"skill-manager/scanner/internal/manifest"
)

func TestDiscoverDeduplicatesAliasedSkillRoots(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, "real-skills")
	alias := filepath.Join(home, "alias-skills")
	writeSkill(t, filepath.Join(root, "sample"), "sample")
	if err := os.Symlink(root, alias); err != nil {
		t.Fatal(err)
	}
	if err := SaveConfig(home, Config{Server: "http://manager.invalid", Token: "test", AgentSkillRoots: map[string][]string{"codex": {root, alias}}}); err != nil {
		t.Fatal(err)
	}
	value, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	agent, ok := findAgent(value, "codex")
	if !ok || len(agent.Skills) != 1 || len(agentSkillRoots(agent)) != 1 || agent.Skills[0].Path != filepath.Join(root, "sample") {
		t.Fatal("aliased root duplicated Skill inventory", agent)
	}
}

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
	if readers, _ := byType["global-skills"].Capabilities["shared_skill_readers"].([]string); len(readers) != 2 || readers[0] != "Cursor" || readers[1] != "OpenCode" {
		t.Fatalf("global Skills readers were not reported: %#v", byType["global-skills"])
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
	for _, agentType := range []string{"claude-code", "codex", "hermes"} {
		agent := byType[agentType]
		if supported, _ := agent.Capabilities["model_config_auto_apply"].(bool); !supported {
			t.Fatalf("%s did not report model configuration support: %#v", agentType, agent.Capabilities)
		}
		if _, ok := agent.Capabilities["model_config_state"].(ModelConfigState); !ok {
			t.Fatalf("%s did not report live model configuration state: %#v", agentType, agent.Capabilities)
		}
	}
	if got := byType[custom.AgentType]; got.DisplayName != "内部助手" || got.SkillsPath != custom.SkillsPath || len(got.Skills) != 1 {
		t.Fatalf("custom Agent discovery failed: %#v", got)
	}
	if inventory.ClientID != DeviceID(inventory.Hostname, home) {
		t.Fatal("device ID is not stable")
	}
}

func TestDiscoverInstalledAgentWithoutSkillsDirectory(t *testing.T) {
	home := t.TempDir()
	bin := t.TempDir()
	path := filepath.Join(bin, "test-agent")
	if err := os.WriteFile(path, []byte("#!/bin/sh\necho test\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)
	spec := adapter{agentType: "test", binaries: []string{"test-agent"}, skillRoots: []string{".test-agent/skills"}, supportsSkill: true}

	if agent, found, err := discoverAgent(home, spec, DefaultManifestOptions()); err != nil || !found || agent.InstallPath != path || len(agent.Skills) != 0 {
		t.Fatalf("installed Agent should be visible without Skills: found=%v agent=%+v err=%v", found, agent, err)
	}
	if err := os.MkdirAll(filepath.Join(home, ".test-agent"), 0o755); err != nil {
		t.Fatal(err)
	}
	directoryOnlySpec := adapter{agentType: "test", skillRoots: []string{".test-agent/skills"}, supportsSkill: true}
	agent, found, err := discoverAgent(home, directoryOnlySpec, DefaultManifestOptions())
	if err != nil || !found {
		t.Fatalf("Agent directory should make Agent visible: found=%v err=%v", found, err)
	}
	expectedSkillsPath := filepath.Join(home, ".test-agent", "skills")
	if agent.SkillsPath != expectedSkillsPath || len(agent.Skills) != 0 || agent.Capabilities["skills_directory_exists"] != false {
		t.Fatalf("Agent without Skills directory should retain its target path and report zero Skills: %+v", agent)
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
	t.Setenv("PATH", t.TempDir())
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
	t.Setenv("PATH", t.TempDir())
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
	var codex, shared BuiltinAgentSetting
	for _, item := range settings {
		if item.AgentType == "codex" {
			codex = item
		}
		if item.AgentType == "global-skills" {
			shared = item
		}
	}
	if !codex.Customized || len(codex.CurrentRoots) != 1 || codex.CurrentRoots[0] != customRoot || codex.DefaultRoots[0] != defaultRoot {
		t.Fatalf("unexpected customized setting: %#v", codex)
	}
	if !shared.SharedSkills || len(shared.SharedSkillReaders) != 2 {
		t.Fatalf("unexpected shared Skills setting: %#v", shared)
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
	t.Setenv("PATH", t.TempDir())
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

func TestDiscoverReportsSymlinkOutsideAllowedRootsWithoutReadingContent(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
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
	if len(inventory.Agents) != 1 || len(inventory.Agents[0].Skills) != 1 {
		t.Fatalf("external symlink not reported: %#v", inventory.Agents)
	}
	skill := inventory.Agents[0].Skills[0]
	if skill.Status != "external_link" || skill.Signature != "" || skill.Error != "skill_link_outside_scope" || skill.Name != "linked" {
		t.Fatalf("external contents should remain unread: %#v", skill)
	}
}

func TestCustomRootOutsideHomeAllowsLinksWithinThatRoot(t *testing.T) {
	home := t.TempDir()
	if err := SaveConfig(home, Config{Server: "http://example.invalid", Token: "test"}); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	writeSkill(t, filepath.Join(root, "source"), "source")
	if err := os.Symlink(filepath.Join(root, "source"), filepath.Join(root, "linked")); err != nil {
		t.Fatal(err)
	}
	custom, err := AddCustomAgent(home, "External workspace", root)
	if err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	for _, agent := range inventory.Agents {
		if agent.AgentType != custom.AgentType {
			continue
		}
		if len(agent.Skills) != 2 {
			t.Fatal("missing configured-root link", agent.Skills)
		}
		for _, skill := range agent.Skills {
			if skill.Signature == "" || skill.Error != "" {
				t.Fatal(skill)
			}
		}
		return
	}
	t.Fatal("custom Agent not discovered")
}

func TestDiscoverIncludesManagedSymlink(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
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

func TestDiscoverKeepsBrokenManagedSymlinkVisible(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	home := t.TempDir()
	root := filepath.Join(home, ".codex", "skills")
	target := filepath.Join(home, ".agent-manager", "skills", "deleted", "release")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(root, "deleted-skill")); err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || len(inventory.Agents[0].Skills) != 1 {
		t.Fatalf("broken managed symlink should remain visible: %#v", inventory.Agents)
	}
	skill := inventory.Agents[0].Skills[0]
	if skill.Name != "deleted-skill" || skill.Status != "broken_link" || !strings.Contains(skill.Error, "软链接目标不存在") {
		t.Fatalf("unexpected broken symlink result: %#v", skill)
	}
}

func TestTemplateHeavySkillFitsDefaultManifestLimits(t *testing.T) {
	root := t.TempDir()
	writeSkill(t, root, "template-heavy")
	for i := 0; i < 2100; i++ {
		if err := os.WriteFile(filepath.Join(root, fmt.Sprintf("template-%d.svg", i)), []byte("<svg/>"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 4; i++ {
		file, err := os.Create(filepath.Join(root, fmt.Sprintf("reference-%d.bin", i)))
		if err != nil {
			t.Fatal(err)
		}
		err = file.Truncate(15 * 1024 * 1024)
		file.Close()
		if err != nil {
			t.Fatal(err)
		}
	}
	value, err := manifest.Build(root, DefaultManifestOptions())
	if err != nil {
		t.Fatal(err)
	}
	if len(value.Files) != 2105 || value.TotalBytes < 60*1024*1024 || manifest.ContentSignature(value.Files) == "" {
		t.Fatalf("incomplete manifest: %d files, %d bytes", len(value.Files), value.TotalBytes)
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

func TestDiscoverResidualDirectoryIsNotInstallation(t *testing.T) {
	home := t.TempDir()
	t.Setenv("PATH", t.TempDir())
	writeSkill(t, filepath.Join(home, ".removed-agent", "skills", "retained"), "retained")
	spec := adapter{agentType: "removed-agent", binaries: []string{"removed-agent"}, skillRoots: []string{".removed-agent/skills"}, supportsSkill: true}
	agent, found, err := discoverAgent(home, spec, DefaultManifestOptions())
	if err != nil || !found || agent.InstallPath != "" || agent.Capabilities["installed"] != false || len(agent.Skills) != 1 {
		t.Fatalf("retain inventory without claiming installation: agent=%+v found=%v err=%v", agent, found, err)
	}
}

func TestDiscoverNativeAndVersionedInstallations(t *testing.T) {
	for _, relative := range []string{".local/bin/test-agent", ".nvm/versions/node/v22/bin/test-agent"} {
		t.Run(relative, func(t *testing.T) {
			home := t.TempDir()
			t.Setenv("PATH", t.TempDir())
			path := filepath.Join(home, relative)
			if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte("#!/bin/sh\n"), 0o755); err != nil {
				t.Fatal(err)
			}
			agent, found, err := discoverAgent(home, adapter{agentType: "test", binaries: []string{"test-agent"}, skillRoots: []string{".test/skills"}, supportsSkill: true}, DefaultManifestOptions())
			if err != nil || !found || agent.InstallPath != path || agent.SkillsPath != filepath.Join(home, ".test/skills") || len(agent.Skills) != 0 {
				t.Fatalf("installation not found: %+v %v", agent, err)
			}
		})
	}
}
