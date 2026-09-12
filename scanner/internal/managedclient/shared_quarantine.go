package managedclient

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
)

// The inventory contains the readers grouped before reporting policy events.
// Automatic policy applies to every discovered reader. Manual tasks retain
// their platform-authorized path scope in applyObservedAction.
func applyAutomaticObservedAction(ctx context.Context, home string, inventory Inventory, agent Agent, skill Skill, physical string, policy Policy, api API, store *Store, value *SkillObservation) (map[string]string, error) {
	if canonicalSkillRoot(skill.Path) != physical {
		value.ErrorCode = "skill_content_changed"
		return nil, fmt.Errorf("skill_content_changed")
	}
	info, err := os.Lstat(skill.Path)
	if (value.Action != "quarantine" && value.Action != "uninstall") || err != nil || info.Mode()&os.ModeSymlink == 0 {
		return nil, applyObservedAction(ctx, home, inventory, agent, skill, policy, api, store, value)
	}
	release, err := AcquireMutationLock(home)
	if err != nil {
		value.ErrorCode = "skill_action_busy"
		return nil, err
	}
	defer release()
	type reader struct {
		agent Agent
		skill Skill
		entry string
		paths []string
	}
	readers := []reader{}
	entries := map[string]int{}
	states := map[string]installTargetState{}
	for _, candidate := range inventory.Agents {
		if !candidate.SkillManagementSupported {
			continue
		}
		for _, alias := range candidate.Skills {
			if canonicalSkillRoot(alias.Path) != physical {
				value.ErrorCode = "skill_content_changed"
				return nil, fmt.Errorf("skill_content_changed")
			}
			if _, exists := states[alias.Path]; exists {
				continue
			}
			state, err := inspectInstallTarget(alias.Path)
			if err != nil || state.link == "" || alias.Signature != skill.Signature || state.signature != skill.Signature || skill.Signature == "" {
				value.ErrorCode = "skill_content_changed"
				return nil, fmt.Errorf("skill_content_changed")
			}
			states[alias.Path] = state
			parent, err := filepath.EvalSymlinks(filepath.Dir(alias.Path))
			if err != nil {
				value.ErrorCode = "skill_content_changed"
				return nil, fmt.Errorf("skill_content_changed")
			}
			entry := filepath.Join(parent, filepath.Base(alias.Path))
			if index, exists := entries[entry]; exists {
				readers[index].paths = append(readers[index].paths, alias.Path)
			} else {
				entries[entry] = len(readers)
				readers = append(readers, reader{candidate, alias, entry, []string{alias.Path}})
			}
		}
	}
	if len(readers) == 0 {
		value.ErrorCode = "skill_content_changed"
		return nil, fmt.Errorf("skill_content_changed")
	}
	ids := map[string]string{}
	var retained QuarantineItem
	for i, reader := range readers {
		path := reader.skill.Path
		for _, alias := range reader.paths {
			parent, err := filepath.EvalSymlinks(filepath.Dir(alias))
			if err != nil || filepath.Join(parent, filepath.Base(alias)) != reader.entry {
				value.ErrorCode = "skill_content_changed"
				return ids, fmt.Errorf("skill_content_changed")
			}
			if err := checkInstallTarget(alias, states); err != nil {
				value.ErrorCode = "skill_content_changed"
				return ids, err
			}
		}
		var item QuarantineItem
		if i == 0 {
			item, err = quarantineSkill(home, store, reader.agent.AgentType, reader.skill.Name, path, value.Trigger, skill.Signature)
			retained = item
		} else {
			item = retained
			item.ID = retained.ID + "-" + observationKey(path)
			item.AgentType, item.SkillName, item.OriginalPath = reader.agent.AgentType, reader.skill.Name, path
			_, err = store.db.Exec(`INSERT INTO client_quarantine(id,agent_type,skill_name,original_path,quarantine_path,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?)`,
				item.ID, item.AgentType, item.SkillName, path, item.QuarantinePath, item.Reason, item.Status, item.CreatedAt)
			if err != nil {
				return ids, err
			}
			if err == nil {
				// Each known link gets its own recovery destination; their retained
				// content is shared. The external directory remains untouched.
				err = os.Remove(path)
				if err != nil {
					_, _ = store.db.Exec(`UPDATE client_quarantine SET status='quarantine_failed' WHERE id=?`, item.ID)
				}
			}
		}
		if item.ID != "" {
			for _, alias := range reader.paths {
				ids[alias] = item.ID
				if alias == skill.Path {
					value.QuarantineID = item.ID
				}
			}
		}
		if err != nil {
			return ids, err
		}
		for _, alias := range reader.paths {
			if _, err = store.db.Exec(`DELETE FROM client_installs WHERE target_path=?`, alias); err != nil {
				return ids, err
			}
		}
		if value.Action == "uninstall" {
			if _, err = store.db.Exec(`UPDATE client_quarantine SET status='uninstalled' WHERE id=?`, item.ID); err != nil {
				return ids, err
			}
		}
	}
	return ids, nil
}
