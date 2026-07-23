package managedclient

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"

	"skill-manager/scanner/internal/manifest"
)

var Version = "dev"

const InventoryCacheVersion = "2"

type Skill struct {
	SkillID      string `json:"skill_id,omitempty"`
	Name         string `json:"name"`
	Path         string `json:"path"`
	Signature    string `json:"signature,omitempty"`
	Status       string `json:"status"`
	InstallMode  string `json:"install_mode,omitempty"`
	SourceTarget string `json:"-"`
	Error        string `json:"error,omitempty"`
}

type Agent struct {
	AgentType                string         `json:"agent_type"`
	DisplayName              string         `json:"display_name,omitempty"`
	Version                  string         `json:"version,omitempty"`
	InstallPath              string         `json:"install_path,omitempty"`
	SkillsPath               string         `json:"skills_path,omitempty"`
	SkillManagementSupported bool           `json:"skill_management_supported"`
	Capabilities             map[string]any `json:"capabilities"`
	Skills                   []Skill        `json:"skills"`
}

type Inventory struct {
	ClientID         string  `json:"client_id"`
	Name             string  `json:"name"`
	Hostname         string  `json:"hostname"`
	OS               string  `json:"os"`
	Arch             string  `json:"arch"`
	ClientVersion    string  `json:"client_version"`
	DiscoveryVersion string  `json:"discovery_version,omitempty"`
	Agents           []Agent `json:"agents"`
}

type adapter struct {
	agentType     string
	binaries      []string
	skillRoots    []string
	supportsSkill bool
	appPaths      []string
	sharedSkills  bool
}

type BuiltinAgentSetting struct {
	AgentType    string   `json:"agent_type"`
	DefaultRoots []string `json:"default_roots"`
	CurrentRoots []string `json:"current_roots"`
	Customized   bool     `json:"customized"`
}

func adapters() []adapter {
	return []adapter{
		{agentType: "global-skills", skillRoots: []string{".agents/skills"}, supportsSkill: true, sharedSkills: true},
		{agentType: "claude-code", binaries: []string{"claude"}, skillRoots: []string{".claude/skills"}, supportsSkill: true},
		{agentType: "codex", binaries: []string{"codex"}, skillRoots: []string{".codex/skills"}, supportsSkill: true},
		{agentType: "gemini", binaries: []string{"gemini"}, skillRoots: []string{".gemini/skills"}, supportsSkill: true},
		{agentType: "opencode", binaries: []string{"opencode"}, skillRoots: []string{".opencode/skills", ".config/opencode/skills"}, supportsSkill: true},
		{agentType: "openclaw", binaries: []string{"openclaw"}, skillRoots: []string{".openclaw/skills"}, supportsSkill: true},
		{agentType: "hermes", binaries: []string{"hermes"}, skillRoots: []string{".hermes/skills"}, supportsSkill: true},
		{agentType: "trae-cn", binaries: []string{"trae-cn"}, skillRoots: []string{".trae-cn/skills"}, supportsSkill: true},
		{agentType: "trae", binaries: []string{"trae"}, skillRoots: []string{".trae/skills"}, supportsSkill: true},
		{agentType: "cursor", binaries: []string{"cursor"}, skillRoots: []string{".cursor/skills"}, supportsSkill: true},
		{agentType: "codebuddy", binaries: []string{"codebuddy"}, skillRoots: []string{".codebuddy/skills"}, supportsSkill: true},
		{agentType: "workbuddy", binaries: []string{"workbuddy"}, skillRoots: []string{".workbuddy/skills"}, supportsSkill: true},
	}
}

func Discover(home string) (Inventory, error) {
	hostname, _ := os.Hostname()
	result := Inventory{
		ClientID:      DeviceID(hostname, home),
		Name:          hostname,
		Hostname:      hostname,
		OS:            runtime.GOOS,
		Arch:          runtime.GOARCH,
		ClientVersion: Version,
		Agents:        []Agent{},
	}
	opts := DefaultManifestOptions()
	config, err := LoadConfig(home)
	if err != nil {
		return result, err
	}
	specs := adapters()
	for index := range specs {
		if roots := config.AgentSkillRoots[specs[index].agentType]; len(roots) > 0 {
			specs[index].skillRoots = roots
		}
	}
	type discoveryResult struct {
		agent     Agent
		installed bool
		err       error
	}
	discovered := make([]discoveryResult, len(specs))
	var wait sync.WaitGroup
	for index, spec := range specs {
		wait.Add(1)
		go func(index int, spec adapter) {
			defer wait.Done()
			discovered[index].agent, discovered[index].installed, discovered[index].err = discoverAgent(home, spec, opts)
		}(index, spec)
	}
	wait.Wait()
	builtinRoots := map[string]string{}
	for _, item := range discovered {
		if item.err != nil {
			return result, item.err
		}
		if item.installed {
			result.Agents = append(result.Agents, item.agent)
			for _, root := range agentSkillRoots(item.agent) {
				builtinRoots[canonicalSkillRoot(root)] = item.agent.AgentType
			}
		}
	}
	for _, custom := range config.CustomAgents {
		if _, duplicated := builtinRoots[canonicalSkillRoot(custom.SkillsPath)]; duplicated {
			continue
		}
		agent := Agent{
			AgentType:                custom.AgentType,
			DisplayName:              custom.Name,
			SkillsPath:               custom.SkillsPath,
			SkillManagementSupported: true,
			Capabilities:             map[string]any{"skill_management": true, "custom": true, "display_name": custom.Name},
			Skills:                   []Skill{},
		}
		info, statErr := os.Stat(custom.SkillsPath)
		if statErr != nil || !info.IsDir() {
			agent.Capabilities["path_available"] = false
			result.Agents = append(result.Agents, agent)
			continue
		}
		agent.Capabilities["path_available"] = true
		agent.Capabilities["skill_roots"] = []string{custom.SkillsPath}
		agent.Skills, err = readSkills(custom.SkillsPath, filepath.Join(home, ".agent-manager", "skills"), opts)
		if err != nil {
			return result, fmt.Errorf("%s skill discovery failed at %s: %w", custom.Name, custom.SkillsPath, err)
		}
		result.Agents = append(result.Agents, agent)
	}
	return result, nil
}

func agentSkillRoots(agent Agent) []string {
	if roots, ok := agent.Capabilities["skill_roots"].([]string); ok {
		return roots
	}
	if agent.SkillsPath != "" {
		return []string{agent.SkillsPath}
	}
	return nil
}

func canonicalSkillRoot(path string) string {
	path = filepath.Clean(path)
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return filepath.Clean(resolved)
	}
	return path
}

func DeviceID(hostname, home string) string {
	sum := sha256.Sum256([]byte(hostname + "\x00" + home))
	return "amc_" + hex.EncodeToString(sum[:12])
}

func discoverAgent(home string, spec adapter, opts manifest.Options) (Agent, bool, error) {
	agent := Agent{
		AgentType:                spec.agentType,
		SkillManagementSupported: spec.supportsSkill,
		Capabilities:             map[string]any{"skill_management": spec.supportsSkill},
		Skills:                   []Skill{},
	}
	if spec.sharedSkills {
		agent.Capabilities["shared_skills"] = true
	}
	for _, binary := range spec.binaries {
		if path, err := exec.LookPath(binary); err == nil {
			agent.InstallPath = path
			break
		}
	}
	for _, rel := range spec.appPaths {
		path := filepath.FromSlash(rel)
		if filepath.IsAbs(path) {
			currentHome, _ := os.UserHomeDir()
			if filepath.Clean(home) != filepath.Clean(currentHome) {
				continue
			}
		} else {
			path = filepath.Join(home, path)
		}
		if _, err := os.Stat(path); err == nil && agent.InstallPath == "" {
			agent.InstallPath = path
		}
	}
	var roots []string
	relatedDirectoryFound := false
	for _, configuredRoot := range spec.skillRoots {
		root := resolveSkillRoot(home, configuredRoot)
		parent := filepath.Dir(root)
		if info, err := os.Stat(parent); err == nil && info.IsDir() {
			relatedDirectoryFound = true
		}
		if info, err := os.Stat(root); err == nil && info.IsDir() {
			roots = append(roots, root)
		}
	}
	if !relatedDirectoryFound {
		return agent, false, nil
	}
	if len(roots) > 0 {
		agent.SkillsPath = roots[0]
		agent.Capabilities["skill_roots"] = roots
	}
	for _, root := range roots {
		skills, err := readSkills(root, filepath.Join(home, ".agent-manager", "skills"), opts)
		if err != nil {
			return agent, false, fmt.Errorf("%s skill discovery failed at %s: %w", spec.agentType, root, err)
		}
		agent.Skills = append(agent.Skills, skills...)
	}
	return agent, true, nil
}

func BuiltinAgentSettings(home string) ([]BuiltinAgentSetting, error) {
	config, err := LoadConfig(home)
	if err != nil {
		return nil, err
	}
	return builtinAgentSettings(home, config), nil
}

func builtinAgentSettings(home string, config Config) []BuiltinAgentSetting {
	result := make([]BuiltinAgentSetting, 0, len(adapters()))
	for _, spec := range adapters() {
		defaults := resolvedSkillRoots(home, spec.skillRoots)
		current := defaults
		customized := false
		if configured := config.AgentSkillRoots[spec.agentType]; len(configured) > 0 {
			current = resolvedSkillRoots(home, configured)
			customized = true
		}
		result = append(result, BuiltinAgentSetting{
			AgentType:    spec.agentType,
			DefaultRoots: defaults,
			CurrentRoots: current,
			Customized:   customized,
		})
	}
	return result
}

func SetBuiltinAgentRoots(home, agentType string, roots []string) error {
	agentType = strings.TrimSpace(agentType)
	supported := false
	for _, spec := range adapters() {
		if spec.agentType == agentType {
			supported = true
			break
		}
	}
	if !supported {
		return fmt.Errorf("unsupported built-in Agent: %s", agentType)
	}
	normalized := resolvedSkillRoots(home, roots)
	if len(normalized) == 0 {
		return errors.New("at least one Skill directory is required")
	}
	config, err := LoadConfig(home)
	if err != nil {
		return err
	}
	if config.AgentSkillRoots == nil {
		config.AgentSkillRoots = map[string][]string{}
	}
	config.AgentSkillRoots[agentType] = normalized
	return SaveConfig(home, config)
}

func ResetBuiltinAgentRoots(home, agentType string) error {
	config, err := LoadConfig(home)
	if err != nil {
		return err
	}
	if config.AgentSkillRoots == nil {
		return nil
	}
	delete(config.AgentSkillRoots, strings.TrimSpace(agentType))
	return SaveConfig(home, config)
}

func resolvedSkillRoots(home string, roots []string) []string {
	result := make([]string, 0, len(roots))
	seen := map[string]bool{}
	for _, value := range roots {
		root := resolveSkillRoot(home, value)
		if root == "" || seen[root] {
			continue
		}
		seen[root] = true
		result = append(result, root)
	}
	return result
}

func resolveSkillRoot(home, value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if value == "~" {
		return filepath.Clean(home)
	}
	if strings.HasPrefix(value, "~/") || strings.HasPrefix(value, `~\`) {
		return filepath.Join(home, filepath.FromSlash(value[2:]))
	}
	value = filepath.FromSlash(value)
	if !filepath.IsAbs(value) {
		value = filepath.Join(home, value)
	}
	return filepath.Clean(value)
}

func readSkills(root, managedRoot string, opts manifest.Options) ([]Skill, error) {
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	result := []Skill{}
	userRoot := filepath.Dir(filepath.Dir(managedRoot))
	for _, entry := range entries {
		path := filepath.Join(root, entry.Name())
		buildRoot := path
		info, err := os.Lstat(path)
		if err != nil {
			continue
		}
		if info.Mode()&os.ModeSymlink != 0 {
			resolved, err := filepath.EvalSymlinks(path)
			if err != nil || !pathWithin(resolved, userRoot) {
				continue
			}
			info, err := os.Stat(resolved)
			if err != nil || !info.IsDir() {
				continue
			}
			buildRoot = resolved
		} else if !info.IsDir() {
			continue
		}
		if _, err := os.Stat(filepath.Join(buildRoot, "SKILL.md")); err != nil {
			continue
		}
		value, err := manifest.Build(buildRoot, opts)
		if err != nil {
			name, _ := manifest.ReadSkillMetadata(buildRoot)
			if name == "" {
				name = filepath.Base(path)
			}
			result = append(result, Skill{
				Name:         name,
				Path:         path,
				Status:       "unscannable",
				SourceTarget: symlinkTarget(path, buildRoot),
				Error:        err.Error(),
			})
			continue
		}
		result = append(result, Skill{
			Name:         value.Name,
			Path:         path,
			Signature:    manifest.ContentSignature(value.Files),
			Status:       "observed",
			SourceTarget: symlinkTarget(path, buildRoot),
		})
	}
	return result, nil
}

func symlinkTarget(path, resolved string) string {
	if resolved != path {
		return resolved
	}
	return ""
}

func pathWithin(path, root string) bool {
	absolutePath, err := filepath.EvalSymlinks(path)
	if err != nil {
		return false
	}
	absoluteRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(absoluteRoot, absolutePath)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}
