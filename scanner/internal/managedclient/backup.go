package managedclient

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Backup struct {
	Name      string `json:"name"`
	Path      string `json:"path"`
	CreatedAt string `json:"created_at"`
}

func ListBackups(home string) ([]Backup, error) {
	result := []Backup{}
	known := map[string]bool{}
	for _, root := range backupRoots(home) {
		entries, err := os.ReadDir(root)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			if !entry.IsDir() || strings.HasPrefix(entry.Name(), "restore-before-") || known[entry.Name()] {
				continue
			}
			info, err := entry.Info()
			if err != nil {
				return nil, err
			}
			known[entry.Name()] = true
			result = append(result, Backup{
				Name:      entry.Name(),
				Path:      filepath.Join(root, entry.Name()),
				CreatedAt: info.ModTime().UTC().Format(time.RFC3339),
			})
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CreatedAt > result[j].CreatedAt })
	return result, nil
}

type BackupRestoreItem struct {
	AgentType       string
	SkillName       string
	Source          string
	Target          string
	Signature       string
	TargetSignature string
}

func PlanBackupRestore(home, name string) ([]BackupRestoreItem, error) {
	if name == "" || filepath.Base(name) != name || name == "." || name == ".." {
		return nil, fmt.Errorf("invalid backup name")
	}
	sourceRoot := ""
	for _, candidateRoot := range backupRoots(home) {
		candidate := filepath.Join(candidateRoot, name)
		info, err := os.Lstat(candidate)
		if err == nil && info.IsDir() && info.Mode()&os.ModeSymlink == 0 {
			sourceRoot = candidate
			break
		}
	}
	if sourceRoot == "" {
		return nil, fmt.Errorf("backup not found: %s", name)
	}
	roots := map[string]string{}
	for _, spec := range adapters() {
		if spec.supportsSkill && len(spec.skillRoots) > 0 {
			roots[spec.agentType] = filepath.Join(home, filepath.FromSlash(spec.skillRoots[0]))
		}
	}
	config, err := LoadConfig(home)
	if err != nil {
		return nil, err
	}
	for _, agent := range config.CustomAgents {
		roots[agent.AgentType] = agent.SkillsPath
	}
	for agentType, configured := range config.AgentSkillRoots {
		if len(configured) == 1 {
			roots[agentType] = resolveSkillRoot(home, configured[0])
		}
	}
	var metadata struct {
		AgentType    string `json:"agent_type"`
		SkillName    string `json:"skill_name"`
		OriginalPath string `json:"original_path"`
		Signature    string `json:"signature"`
	}
	metadataBody, metadataErr := os.ReadFile(filepath.Join(sourceRoot, "metadata.json"))
	if metadataErr == nil {
		if err := json.Unmarshal(metadataBody, &metadata); err != nil {
			return nil, err
		}
		if metadata.OriginalPath == "" || metadata.Signature == "" {
			return nil, fmt.Errorf("backup_metadata_invalid")
		}
	} else if !os.IsNotExist(metadataErr) {
		return nil, metadataErr
	}
	agents, err := os.ReadDir(sourceRoot)
	if err != nil {
		return nil, err
	}
	result := []BackupRestoreItem{}
	for _, agent := range agents {
		targetRoot := roots[agent.Name()]
		if !agent.IsDir() {
			continue
		}
		if targetRoot == "" {
			return nil, fmt.Errorf("backup_agent_unavailable")
		}
		skills, err := os.ReadDir(filepath.Join(sourceRoot, agent.Name()))
		if err != nil {
			return nil, err
		}
		for _, skill := range skills {
			if !skill.IsDir() {
				continue
			}
			source := filepath.Join(sourceRoot, agent.Name(), skill.Name())
			target := filepath.Join(targetRoot, skill.Name())
			if metadataErr == nil {
				if metadata.AgentType != agent.Name() || metadata.SkillName != skill.Name() {
					return nil, fmt.Errorf("backup_metadata_invalid")
				}
				target = metadata.OriginalPath
				allowedRoots := []string{targetRoot}
				if configured := config.AgentSkillRoots[agent.Name()]; len(configured) > 0 {
					allowedRoots = configured
				}
				allowed := false
				parent, err := filepath.EvalSymlinks(filepath.Dir(target))
				if err != nil {
					return nil, err
				}
				for _, root := range allowedRoots {
					resolved, err := filepath.EvalSymlinks(resolveSkillRoot(home, root))
					if err == nil && resolved == parent {
						allowed = true
						break
					}
				}
				if !allowed || filepath.Base(target) != skill.Name() {
					return nil, fmt.Errorf("skill_target_unavailable")
				}
				if err := checkObservedContent(Skill{Path: source, Signature: metadata.Signature}); err != nil {
					return nil, err
				}
			} else if len(config.AgentSkillRoots[agent.Name()]) > 1 {
				return nil, fmt.Errorf("backup_target_ambiguous")
			}
			snapshot, err := inspectInstallTarget(source)
			if err != nil {
				return nil, err
			}
			current, err := inspectInstallTarget(target)
			if err != nil && !os.IsNotExist(err) {
				return nil, err
			}
			result = append(result, BackupRestoreItem{AgentType: agent.Name(), SkillName: skill.Name(), Source: source, Target: target, Signature: snapshot.signature, TargetSignature: current.signature})
		}
	}
	return result, nil
}

func backupRoots(home string) []string {
	return []string{BackupsRoot(home), legacyContentRoot(home, "backups")}
}
