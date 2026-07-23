package managedclient

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/manifest"
)

type TakeoverItem struct {
	AgentType      string `json:"agent_type"`
	Name           string `json:"name"`
	Source         string `json:"source"`
	SkillID        string `json:"skill_id,omitempty"`
	ManagedAgentID string `json:"managed_agent_id,omitempty"`
	Signature      string `json:"signature,omitempty"`
	Action         string `json:"action"`
	Reason         string `json:"reason"`
	SourceTarget   string `json:"-"`
	PendingPath    string `json:"-"`
}

type TakeoverPlan struct {
	Items         []TakeoverItem `json:"items"`
	ExcludedPaths []string       `json:"-"`
}

func BuildTakeoverPlan(inventory Inventory, comparisons []CompareItem) TakeoverPlan {
	results := map[string]CompareItem{}
	for _, item := range comparisons {
		results[comparisonKey(item.AgentType, item.Name, item.LocalPath, item.LocalSignature)] = item
	}
	plan := TakeoverPlan{Items: []TakeoverItem{}}
	for _, agent := range inventory.Agents {
		if !agent.SkillManagementSupported {
			continue
		}
		for _, skill := range agent.Skills {
			result, ok := results[comparisonKey(agent.AgentType, skill.Name, skill.Path, skill.Signature)]
			if !ok {
				result, ok = results[comparisonKey(agent.AgentType, skill.Name, "", "")]
			}
			action := "pending"
			reason := "not_compared"
			if ok {
				reason = result.Reason
				if result.Allowed {
					action = "manage"
					if skill.Status == "managed" && skill.SkillID != "" && skill.SkillID == result.SkillID {
						action = "managed"
						reason = "already_managed"
					}
				}
			}
			plan.Items = append(plan.Items, TakeoverItem{
				AgentType:      agent.AgentType,
				Name:           skill.Name,
				Source:         skill.Path,
				SkillID:        result.SkillID,
				ManagedAgentID: result.ManagedAgentID,
				Signature:      skill.Signature,
				Action:         action,
				Reason:         reason,
				SourceTarget:   skill.SourceTarget,
			})
		}
	}
	return plan
}

func comparisonKey(agentType, name, path, signature string) string {
	return agentType + "\x00" + name + "\x00" + filepath.Clean(path) + "\x00" + signature
}

func RecordTakeover(home string, plan TakeoverPlan, store *Store) error {
	opts := DefaultManifestOptions()
	for _, item := range plan.Items {
		if item.Action == "managed" {
			continue
		}
		if item.Action != "manage" {
			fingerprint := ""
			if item.PendingPath != "" {
				if value, err := manifest.Build(item.PendingPath, opts); err == nil {
					fingerprint = value.Fingerprint
				}
			}
			if err := store.SavePending(PendingItem{
				AgentType:    item.AgentType,
				SkillName:    item.Name,
				OriginalPath: item.Source,
				PendingPath:  item.PendingPath,
				Reason:       item.Reason,
				Fingerprint:  fingerprint,
			}); err != nil {
				return err
			}
			continue
		}
		root := filepath.Join(home, ".agent-manager", "skills", item.SkillID, item.Signature)
		value, err := manifest.Build(root, opts)
		if err != nil {
			return err
		}
		files := make([]releaseFile, 0, len(value.Files))
		for _, file := range value.Files {
			files = append(files, releaseFile{Path: file.Path, Size: file.Size, SHA256: file.SHA256})
		}
		if err := store.SaveInstall(Installation{
			AgentType:      item.AgentType,
			ManagedAgentID: item.ManagedAgentID,
			SkillID:        item.SkillID,
			SkillName:      item.Name,
			TargetPath:     item.Source,
			Manifest: releaseManifest{
				Version:          1,
				SkillID:          item.SkillID,
				Name:             item.Name,
				ContentSignature: item.Signature,
				Files:            files,
			},
		}); err != nil {
			return err
		}
	}
	selected := make([]string, 0, len(plan.Items))
	for _, item := range plan.Items {
		selected = append(selected, item.Source)
	}
	if err := store.SaveTakeoverScope(selected, plan.ExcludedPaths); err != nil {
		return err
	}
	return store.SetGovernanceEnabled(true)
}

func RestoreTakeover(plan TakeoverPlan, backupRoot string) {
	rollback(plan.Items, backupRoot)
}

func ApplyTakeover(home string, plan *TakeoverPlan) (string, error) {
	root := filepath.Join(home, ".agent-manager")
	stamp := time.Now().UTC().Format("20060102T150405Z")
	backupRoot := filepath.Join(root, "backups", stamp)
	processed := []TakeoverItem{}
	for index := range plan.Items {
		item := &plan.Items[index]
		if item.Action == "managed" {
			continue
		}
		backup := filepath.Join(backupRoot, item.AgentType, filepath.Base(item.Source))
		if err := copyDir(item.Source, backup); err != nil {
			rollback(processed, backupRoot)
			return "", err
		}
		var err error
		if item.Action == "manage" {
			err = manageSkill(root, *item)
		} else {
			item.PendingPath, err = movePending(root, *item)
		}
		if err != nil {
			rollback(append(processed, *item), backupRoot)
			return "", err
		}
		processed = append(processed, *item)
	}
	return backupRoot, nil
}

func manageSkill(root string, item TakeoverItem) error {
	if item.SkillID == "" || item.Signature == "" {
		return fmt.Errorf("missing platform identity for %s", item.Name)
	}
	store := filepath.Join(root, "skills", item.SkillID, item.Signature)
	tmp := store + ".tmp"
	_ = os.RemoveAll(tmp)
	if err := copyDir(item.Source, tmp); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(store), 0o755); err != nil {
		return err
	}
	_ = os.RemoveAll(store)
	if err := os.Rename(tmp, store); err != nil {
		return err
	}
	if err := os.RemoveAll(item.Source); err != nil {
		return err
	}
	if err := os.Symlink(store, item.Source); err == nil {
		return nil
	}
	return copyDir(store, item.Source)
}

func movePending(root string, item TakeoverItem) (string, error) {
	target := filepath.Join(root, "pending", item.AgentType, filepath.Base(item.Source))
	if _, err := os.Stat(target); err == nil {
		target += "-" + time.Now().UTC().Format("20060102T150405.000000000")
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return "", err
	}
	if info, err := os.Lstat(item.Source); err == nil && info.Mode()&os.ModeSymlink != 0 {
		if err := copyDir(item.Source, target); err != nil {
			return "", err
		}
		if err := os.Remove(item.Source); err != nil {
			_ = os.RemoveAll(target)
			return "", err
		}
		return target, nil
	}
	if err := os.Rename(item.Source, target); err != nil {
		return "", err
	}
	return target, nil
}

func rollback(items []TakeoverItem, backupRoot string) {
	for i := len(items) - 1; i >= 0; i-- {
		item := items[i]
		if item.PendingPath != "" {
			_ = os.RemoveAll(item.PendingPath)
		}
		_ = os.RemoveAll(item.Source)
		if item.SourceTarget != "" {
			_ = os.Symlink(item.SourceTarget, item.Source)
			continue
		}
		backup := filepath.Join(backupRoot, item.AgentType, filepath.Base(item.Source))
		_ = copyDir(backup, item.Source)
	}
}

func copyDir(source, target string) error {
	resolved, err := filepath.EvalSymlinks(source)
	if err != nil {
		return err
	}
	info, err := os.Stat(resolved)
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("not a directory: %s", source)
	}
	return filepath.WalkDir(resolved, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(resolved, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return os.MkdirAll(target, info.Mode().Perm())
		}
		if strings.HasPrefix(rel, "..") || entry.Type()&os.ModeSymlink != 0 {
			return nil
		}
		dst := filepath.Join(target, rel)
		if entry.IsDir() {
			current, err := entry.Info()
			if err != nil {
				return err
			}
			return os.MkdirAll(dst, current.Mode().Perm())
		}
		current, err := entry.Info()
		if err != nil {
			return err
		}
		return copyFile(path, dst, current.Mode().Perm())
	})
}

func copyFile(source, target string, mode os.FileMode) error {
	src, err := os.Open(source)
	if err != nil {
		return err
	}
	defer src.Close()
	out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(out, src)
	closeErr := out.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}
