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
	"slices"
	"strings"
	"sync"

	"skill-manager/scanner/internal/manifest"
)

var Version = "dev"

const InventoryCacheVersion = "11"

type Skill struct {
	Governance    *SkillObservation `json:"governance,omitempty"`
	SkillID       string            `json:"skill_id,omitempty"`
	VersionID     string            `json:"version_id,omitempty"`
	VersionNo     int               `json:"version_no,omitempty"`
	SourceVersion string            `json:"source_version,omitempty"`
	Name          string            `json:"name"`
	Path          string            `json:"path"`
	Signature     string            `json:"signature,omitempty"`
	Status        string            `json:"status"`
	InstallMode   string            `json:"install_mode,omitempty"`
	SourceTarget  string            `json:"-"`
	Error         string            `json:"error,omitempty"`
}

type Agent struct {
	AssetInventory           *AssetInventory `json:"asset_inventory,omitempty"`
	LocalAgentID             string          `json:"local_agent_id"`
	AgentType                string          `json:"agent_type"`
	DisplayName              string          `json:"display_name,omitempty"`
	Version                  string          `json:"version,omitempty"`
	InstallPath              string          `json:"install_path,omitempty"`
	SkillsPath               string          `json:"skills_path,omitempty"`
	SkillManagementSupported bool            `json:"skill_management_supported"`
	Capabilities             map[string]any  `json:"capabilities"`
	Skills                   []Skill         `json:"skills"`
}

type Inventory struct {
	Recovery           []QuarantineItem `json:"recovery"`
	GovernanceProtocol int              `json:"governance_protocol"`
	ClientID           string           `json:"client_id"`
	Name               string           `json:"name"`
	Hostname           string           `json:"hostname"`
	OS                 string           `json:"os"`
	Arch               string           `json:"arch"`
	ClientVersion      string           `json:"client_version"`
	DiscoveryVersion   string           `json:"discovery_version,omitempty"`
	Agents             []Agent          `json:"agents"`
}

type adapter struct {
	displayName        string
	agentType          string
	binaries           []string
	skillRoots         []string
	supportsSkill      bool
	appPaths           []string
	sharedSkills       bool
	sharedSkillReaders []string
}

type BuiltinAgentSetting struct {
	AgentType          string   `json:"agent_type"`
	DefaultRoots       []string `json:"default_roots"`
	CurrentRoots       []string `json:"current_roots"`
	Customized         bool     `json:"customized"`
	SharedSkills       bool     `json:"shared_skills,omitempty"`
	SharedSkillReaders []string `json:"shared_skill_readers,omitempty"`
}

func adapters() []adapter {
	return []adapter{
		{
			agentType:          "global-skills",
			skillRoots:         []string{".agents/skills"},
			supportsSkill:      true,
			sharedSkills:       true,
			sharedSkillReaders: []string{"OpenCode", "Cursor"},
		},
		{agentType: "qoder", displayName: "Qoder", skillRoots: []string{".qoder/skills"}, supportsSkill: true},
		{agentType: "qoder-cn", displayName: "Qoder CN", skillRoots: []string{".qoder-cn/skills"}, supportsSkill: true},
		{agentType: "qoderwork", displayName: "QoderWork", skillRoots: []string{".qoderwork/skills"}, supportsSkill: true},
		{agentType: "zcode", displayName: "ZCode", skillRoots: []string{".zcode/skills"}, supportsSkill: true},
		{agentType: "claude-code", binaries: []string{"claude"}, skillRoots: []string{".claude/skills"}, supportsSkill: true},
		{agentType: "claude-desktop", displayName: "Claude Desktop", appPaths: []string{"/Applications/Claude.app", "Applications/Claude.app"}},
		{agentType: "codex", appPaths: []string{"/Applications/Codex.app", "Applications/Codex.app"}, binaries: []string{"codex"}, skillRoots: []string{".codex/skills"}, supportsSkill: true},
		{agentType: "gemini", binaries: []string{"gemini"}, skillRoots: []string{".gemini/skills"}, supportsSkill: true},
		{agentType: "opencode", appPaths: []string{"/Applications/OpenCode.app", "Applications/OpenCode.app"}, binaries: []string{"opencode"}, skillRoots: []string{".opencode/skills", ".config/opencode/skills"}, supportsSkill: true},
		{agentType: "openclaw", binaries: []string{"openclaw"}, skillRoots: []string{".openclaw/skills"}, supportsSkill: true},
		{agentType: "hermes", binaries: []string{"hermes"}, skillRoots: []string{".hermes/skills"}, supportsSkill: true},
		{agentType: "pi", displayName: "Pi", binaries: []string{"pi"}, skillRoots: []string{".pi/agent/skills"}, supportsSkill: true},
		{agentType: "grokbuild", displayName: "Grok Build", binaries: []string{"grok"}, skillRoots: []string{".grok/skills"}, supportsSkill: true},
		{agentType: "trae-cn", appPaths: []string{"/Applications/Trae CN.app", "Applications/Trae CN.app"}, binaries: []string{"trae-cn"}, skillRoots: []string{".trae-cn/skills", ".trae-cn/builtin_skills"}, supportsSkill: true},
		{agentType: "trae", appPaths: []string{"/Applications/Trae.app", "Applications/Trae.app", "/Applications/TRAE.app", "Applications/TRAE.app"}, binaries: []string{"trae"}, skillRoots: []string{".trae/skills", ".trae/builtin_skills"}, supportsSkill: true},
		{agentType: "cursor", appPaths: []string{"/Applications/Cursor.app", "Applications/Cursor.app"}, binaries: []string{"cursor"}, skillRoots: []string{".cursor/skills"}, supportsSkill: true},
		{agentType: "codebuddy", appPaths: []string{"/Applications/CodeBuddy.app", "Applications/CodeBuddy.app"}, binaries: []string{"codebuddy"}, skillRoots: []string{".codebuddy/skills"}, supportsSkill: true},
		{agentType: "workbuddy", appPaths: []string{"/Applications/WorkBuddy.app", "Applications/WorkBuddy.app"}, binaries: []string{"workbuddy"}, skillRoots: []string{".workbuddy/skills"}, supportsSkill: true},
		{agentType: "teleagent", displayName: "TeleAgent", appPaths: []string{"/Applications/TeleAgent.app", "Applications/TeleAgent.app"}, skillRoots: []string{".config/TeleAgent/users/*/skills"}, supportsSkill: true},
	}
}

func Discover(home string) (Inventory, error) {
	hostname, _ := os.Hostname()
	result := Inventory{
		GovernanceProtocol: 2,
		ClientID:           DeviceID(hostname, home),
		Name:               hostname,
		Hostname:           hostname,
		OS:                 runtime.GOOS,
		Arch:               runtime.GOARCH,
		ClientVersion:      Version,
		Agents:             []Agent{},
	}
	opts := DefaultManifestOptions()
	config, err := LoadConfig(home)
	if err != nil {
		return result, err
	}
	specs := adaptersForHome(home)
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
			LocalAgentID:             custom.AgentType,
			AgentType:                custom.AgentType,
			DisplayName:              custom.Name,
			SkillsPath:               custom.SkillsPath,
			SkillManagementSupported: true,
			Capabilities:             map[string]any{"skill_management": true, "skill_audit_observe": true, "custom": true, "display_name": custom.Name},
			Skills:                   []Skill{},
			AssetInventory:           discoverAssets(home, "", nil),
		}
		info, statErr := os.Stat(custom.SkillsPath)
		if statErr != nil || !info.IsDir() {
			agent.Capabilities["path_available"] = false
			result.Agents = append(result.Agents, agent)
			continue
		}
		agent.Capabilities["path_available"] = true
		agent.Capabilities["skill_roots"] = []string{custom.SkillsPath}
		agent.Skills, err = readSkills(custom.SkillsPath, ManagedSkillsRoot(home), opts)
		if err != nil {
			return result, fmt.Errorf("%s skill discovery failed at %s: %w", custom.Name, custom.SkillsPath, err)
		}
		result.Agents = append(result.Agents, agent)
	}
	annotateDiscoverySharing(&result, config)
	return result, nil
}

func agentSkillRoots(agent Agent) []string {
	if roots, ok := agent.Capabilities["skill_roots"].([]string); ok {
		return roots
	}
	if values, ok := agent.Capabilities["skill_roots"].([]any); ok {
		roots := []string{}
		for _, value := range values {
			if root, ok := value.(string); ok && root != "" {
				roots = append(roots, root)
			}
		}
		if len(roots) > 0 {
			return roots
		}
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
		DisplayName:              spec.displayName,
		LocalAgentID:             spec.agentType,
		AgentType:                spec.agentType,
		SkillManagementSupported: spec.supportsSkill,
		Capabilities:             map[string]any{"skill_management": spec.supportsSkill, "skill_audit_observe": true},
		Skills:                   []Skill{},
	}
	if contract, ok := modelAdapters[spec.agentType]; ok && len(modelConfigFiles(spec.agentType)) > 0 {
		agent.Capabilities["model_config_auto_apply"] = true
		agent.Capabilities["model_config_contract"] = contract
		_, probeErr := modelProbeCommand(agent.AgentType, "")
		agent.Capabilities["model_config_verification"] = contract.Verification == "isolated_cli" && probeErr == nil
		agent.Capabilities["model_config_state"] = InspectModelConfig(home, spec.agentType)
	}
	if spec.sharedSkills {
		agent.Capabilities["shared_skills"] = true
		agent.Capabilities["shared_skill_readers"] = spec.sharedSkillReaders
	}
	for _, binary := range spec.binaries {
		if path, err := exec.LookPath(binary); err == nil {
			agent.InstallPath = path
			break
		}
	}
	if agent.InstallPath == "" {
		for _, binary := range spec.binaries {
			directories := []string{filepath.Join(home, ".local/bin"), filepath.Join(home, ".cargo/bin"), filepath.Join(home, ".npm-global/bin"), filepath.Join(home, ".hermes/venv/bin"), filepath.Join(home, ".opencode/bin")}
			versioned, _ := filepath.Glob(filepath.Join(home, ".nvm/versions/node/*/bin"))
			directories = append(directories, versioned...)
			for _, directory := range directories {
				candidate := filepath.Join(directory, binary)
				if info, err := os.Stat(candidate); err == nil && !info.IsDir() && info.Mode()&0o111 != 0 {
					agent.InstallPath = candidate
					break
				}
			}
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
	var relatedRoot string
	relatedDirectoryFound := false
	for _, relative := range modelConfigFiles(spec.agentType) {
		if info, err := os.Stat(resolvedModelPath(home, spec.agentType, relative)); err == nil && info.Mode().IsRegular() {
			relatedDirectoryFound = true
			break
		}
	}
	for _, configuredRoot := range expandedSkillRoots(home, spec.skillRoots) {
		root := resolveSkillRoot(home, configuredRoot)
		parent := filepath.Dir(root)
		if info, err := os.Stat(parent); err == nil && info.IsDir() {
			relatedDirectoryFound = true
			if relatedRoot == "" {
				relatedRoot = root
			}
		}
		if info, err := os.Stat(root); err == nil && info.IsDir() {
			roots = append(roots, root)
		}
	}
	agent.Capabilities["installed"] = agent.InstallPath != ""
	if _, ok := modelAdapters[spec.agentType]; ok {
		agent.Version = discoverModelVersion(home, spec.agentType, agent.InstallPath)
		if agent.Capabilities["model_config_auto_apply"] == true {
			agent.Capabilities["model_config_contract"] = modelContractForVersion(spec.agentType, agent.Version)
		}
	}
	agent.AssetInventory = discoverAssets(home, spec.agentType, roots)
	if spec.agentType == "trae" || spec.agentType == "trae-cn" {
		collector := &assetCollector{result: agent.AssetInventory}
		for _, project := range collector.traeProjects(home, spec.agentType) {
			root := filepath.Join(project, ".trae/skills")
			if info, err := os.Stat(root); err == nil && info.IsDir() && !slices.Contains(roots, root) {
				roots = append(roots, root)
			}
		}
	}

	if len(agent.AssetInventory.MCPServers) > 0 || len(agent.AssetInventory.Plugins) > 0 {
		relatedDirectoryFound = true
	}
	if !relatedDirectoryFound && agent.InstallPath == "" {
		return agent, false, nil
	}
	if len(roots) == 0 && len(spec.skillRoots) > 0 {
		agent.SkillsPath = relatedRoot
		if agent.SkillsPath == "" && !strings.ContainsAny(spec.skillRoots[0], "*?[") {
			agent.SkillsPath = resolveSkillRoot(home, spec.skillRoots[0])
		}
		agent.Capabilities["skills_directory_exists"] = false
	}
	if len(roots) > 0 {
		agent.SkillsPath = roots[0]
		agent.Capabilities["skill_roots"] = roots
		agent.Capabilities["skills_directory_exists"] = true
	}
	for _, root := range roots {
		skills, err := readSkills(root, ManagedSkillsRoot(home), opts)
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
	result := make([]BuiltinAgentSetting, 0, len(adaptersForHome(home)))
	for _, spec := range adaptersForHome(home) {
		defaults := resolvedSkillRoots(home, spec.skillRoots)
		current := defaults
		customized := false
		if configured := config.AgentSkillRoots[spec.agentType]; len(configured) > 0 {
			current = resolvedSkillRoots(home, configured)
			customized = true
		}
		result = append(result, BuiltinAgentSetting{
			AgentType:          spec.agentType,
			DefaultRoots:       defaults,
			CurrentRoots:       current,
			Customized:         customized,
			SharedSkills:       spec.sharedSkills,
			SharedSkillReaders: spec.sharedSkillReaders,
		})
	}
	return result
}

func SetBuiltinAgentRoots(home, agentType string, roots []string) error {
	agentType = strings.TrimSpace(agentType)
	supported := false
	for _, spec := range adaptersForHome(home) {
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
		key := canonicalSkillRoot(root)
		if root == "" || seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, root)
	}
	return result
}

func expandedSkillRoots(home string, roots []string) []string {
	result := []string{}
	for _, pattern := range resolvedSkillRoots(home, roots) {
		if !strings.ContainsAny(pattern, "*?[") {
			result = append(result, pattern)
			continue
		}
		matches, _ := filepath.Glob(pattern)
		result = append(result, matches...)
	}
	return resolvedSkillRoots(home, result)
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
	userRoot := homeFromManagedRoot(managedRoot)
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".agent-manager-restore-") {
			continue
		}
		path := filepath.Join(root, entry.Name())
		buildRoot := path
		info, err := os.Lstat(path)
		if err != nil {
			continue
		}
		if info.Mode()&os.ModeSymlink != 0 {
			resolved, err := filepath.EvalSymlinks(path)
			if err != nil {
				target, _ := os.Readlink(path)
				if target != "" && !filepath.IsAbs(target) {
					target = filepath.Join(filepath.Dir(path), target)
				}
				result = append(result, Skill{
					Name:         entry.Name(),
					Path:         path,
					Status:       "broken_link",
					SourceTarget: filepath.Clean(target),
					Error:        "Skill 软链接目标不存在，可能已删除客户端受管目录；请从平台重新安装可信版本",
				})
				continue
			}
			if !pathWithin(resolved, userRoot) && !pathWithin(resolved, root) {
				result = append(result, Skill{
					Name: entry.Name(), Path: path, Status: "external_link",
					SourceTarget: resolved, Error: "skill_link_outside_scope",
				})
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

func homeFromManagedRoot(managedRoot string) string {
	productRoot := filepath.Dir(managedRoot)
	if filepath.Base(productRoot) == dataProductName &&
		filepath.Base(filepath.Dir(productRoot)) == dataDirectoryName {
		return filepath.Dir(filepath.Dir(productRoot))
	}
	return filepath.Dir(filepath.Dir(managedRoot))
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
