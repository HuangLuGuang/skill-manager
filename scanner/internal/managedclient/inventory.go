package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"skill-manager/scanner/internal/manifest"
)

const Version = "0.1.0"

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
	ClientID      string  `json:"client_id"`
	Name          string  `json:"name"`
	Hostname      string  `json:"hostname"`
	OS            string  `json:"os"`
	Arch          string  `json:"arch"`
	ClientVersion string  `json:"client_version"`
	Agents        []Agent `json:"agents"`
}

type adapter struct {
	agentType     string
	binaries      []string
	skillRoots    []string
	supportsSkill bool
	appPaths      []string
}

func adapters() []adapter {
	return []adapter{
		{agentType: "claude-code", binaries: []string{"claude"}, skillRoots: []string{".claude/skills"}, supportsSkill: true},
		{agentType: "codex", binaries: []string{"codex"}, skillRoots: []string{".codex/skills", ".agents/skills"}, supportsSkill: true},
		{agentType: "gemini", binaries: []string{"gemini"}, skillRoots: []string{".gemini/skills"}, supportsSkill: true},
		{agentType: "opencode", binaries: []string{"opencode"}, skillRoots: []string{".config/opencode/skills"}, supportsSkill: true},
		{agentType: "openclaw", binaries: []string{"openclaw"}, skillRoots: []string{".openclaw/skills"}, supportsSkill: true},
		{agentType: "hermes", binaries: []string{"hermes"}, skillRoots: []string{".hermes/skills"}, supportsSkill: true},
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
	specs := adapters()
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
	for _, item := range discovered {
		if item.err != nil {
			return result, item.err
		}
		if item.installed {
			result.Agents = append(result.Agents, item.agent)
		}
	}
	config, err := LoadConfig(home)
	if err != nil {
		return result, err
	}
	for _, custom := range config.CustomAgents {
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
	for _, binary := range spec.binaries {
		if path, err := exec.LookPath(binary); err == nil {
			agent.InstallPath = path
			agent.Version = commandVersion(path)
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
	for _, rel := range spec.skillRoots {
		root := filepath.Join(home, filepath.FromSlash(rel))
		if info, err := os.Stat(root); err == nil && info.IsDir() {
			roots = append(roots, root)
		}
	}
	if len(roots) > 0 {
		agent.SkillsPath = roots[0]
		agent.Capabilities["skill_roots"] = roots
	}
	if agent.InstallPath == "" && len(roots) == 0 {
		return agent, false, nil
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

func commandVersion(path string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	output, err := exec.CommandContext(ctx, path, "--version").CombinedOutput()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(output))
}
