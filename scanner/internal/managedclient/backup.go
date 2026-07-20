package managedclient

import (
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
	root := filepath.Join(home, ".agent-manager", "backups")
	entries, err := os.ReadDir(root)
	if os.IsNotExist(err) {
		return []Backup{}, nil
	}
	if err != nil {
		return nil, err
	}
	result := make([]Backup, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), "restore-before-") {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			return nil, err
		}
		result = append(result, Backup{
			Name:      entry.Name(),
			Path:      filepath.Join(root, entry.Name()),
			CreatedAt: info.ModTime().UTC().Format(time.RFC3339),
		})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CreatedAt > result[j].CreatedAt })
	return result, nil
}

func RestoreBackup(home, name string) error {
	if name == "" || filepath.Base(name) != name || name == "." || name == ".." {
		return fmt.Errorf("invalid backup name")
	}
	root := filepath.Join(home, ".agent-manager", "backups")
	sourceRoot := filepath.Join(root, name)
	info, err := os.Lstat(sourceRoot)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("backup not found: %s", name)
	}
	roots := map[string]string{}
	for _, spec := range adapters() {
		if spec.supportsSkill && len(spec.skillRoots) > 0 {
			roots[spec.agentType] = filepath.Join(home, filepath.FromSlash(spec.skillRoots[0]))
		}
	}
	config, err := LoadConfig(home)
	if err != nil {
		return err
	}
	for _, agent := range config.CustomAgents {
		roots[agent.AgentType] = agent.SkillsPath
	}
	agents, err := os.ReadDir(sourceRoot)
	if err != nil {
		return err
	}
	safetyRoot := filepath.Join(root, "restore-before-"+time.Now().UTC().Format("20060102T150405Z"))
	for _, agent := range agents {
		targetRoot := roots[agent.Name()]
		if !agent.IsDir() || targetRoot == "" {
			continue
		}
		skills, err := os.ReadDir(filepath.Join(sourceRoot, agent.Name()))
		if err != nil {
			return err
		}
		for _, skill := range skills {
			if !skill.IsDir() {
				continue
			}
			source := filepath.Join(sourceRoot, agent.Name(), skill.Name())
			target := filepath.Join(targetRoot, skill.Name())
			if _, err := os.Lstat(target); err == nil {
				current := target
				if resolved, resolveErr := filepath.EvalSymlinks(target); resolveErr == nil {
					current = resolved
				}
				if err := copyDir(current, filepath.Join(safetyRoot, agent.Name(), skill.Name())); err != nil {
					return err
				}
			}
			if err := os.RemoveAll(target); err != nil {
				return err
			}
			if err := copyDir(source, target); err != nil {
				_ = os.RemoveAll(target)
				_ = copyDir(filepath.Join(safetyRoot, agent.Name(), skill.Name()), target)
				return err
			}
		}
	}
	return nil
}
