package managedclient

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

func restoreQuarantineTask(ctx context.Context, home string, inventory Inventory, agent Agent, api API, store *Store, task Task) error {
	release, err := AcquireMutationLock(home)
	if err != nil {
		return err
	}
	defer release()
	items, err := store.QuarantineItems()
	if err != nil {
		return err
	}
	var item QuarantineItem
	for _, candidate := range items {
		if candidate.ID == stringValue(task.Payload, "quarantine_id") {
			item = candidate
			break
		}
	}
	path := stringValue(task.Payload, "path")
	expected := stringValue(task.Payload, "expected_signature")
	restoringBackup := stringValue(task.Payload, "action") == "restore_backup"
	expectedTarget := stringValue(task.Payload, "expected_target_signature")
	if item.ID == "" || item.AgentType != agent.AgentType || item.OriginalPath != path || expected == "" || item.Signature != expected {
		return fmt.Errorf("recovery_content_changed")
	}
	if restoringBackup && item.Status != "backed_up" {
		return fmt.Errorf("recovery_content_changed")
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(path))
	if err != nil {
		return fmt.Errorf("skill_target_unavailable")
	}
	allowed := false
	for _, root := range agentSkillRoots(agent) {
		resolved, err := filepath.EvalSymlinks(root)
		if err == nil && resolved == parent {
			allowed = true
			break
		}
	}
	if !allowed {
		return fmt.Errorf("skill_target_unavailable")
	}
	checkTarget := func() error {
		currentParent, err := filepath.EvalSymlinks(filepath.Dir(path))
		if err != nil || currentParent != parent {
			return fmt.Errorf("skill_content_changed")
		}
		if restoringBackup && expectedTarget != "" {
			return checkObservedContent(Skill{Path: path, Signature: expectedTarget})
		}
		if _, err := os.Lstat(path); err == nil || !os.IsNotExist(err) {
			return fmt.Errorf("recovery_path_occupied")
		}
		return nil
	}
	if err := checkTarget(); err != nil {
		return err
	}
	policy, err := api.Policy(ctx, inventory.ClientID)
	if err != nil {
		return err
	}
	skill := Skill{Name: item.SkillName, Path: path, Signature: expected}
	probe := Inventory{ClientID: inventory.ClientID, Agents: []Agent{agent}}
	probe.Agents[0].Skills = []Skill{skill}
	results, err := api.Compare(ctx, probe, policy.AgentBindings)
	if err != nil {
		return err
	}
	var comparison *CompareItem
	for index := range results {
		result := &results[index]
		if result.AgentType == agent.AgentType && result.LocalPath == path && result.LocalSignature == expected {
			comparison = result
			break
		}
	}
	if comparison == nil {
		return fmt.Errorf("recovery_verdict_unavailable")
	}
	previous, err := store.Observation(path)
	if err != nil {
		return err
	}
	observation := classifyObservation(previous, skill, comparison)
	action := "record"
	if classificationEnabled(policy) {
		if selected := policy.Classification.Rules[observation.Trigger]; selected != "" {
			action = selected
		}
	} else if (policy.Mode == "block" || policy.Mode == "repair") && !comparison.Certified {
		action = "quarantine"
	}
	if action != "record" && action != "record_only" && action != "submit_scan" {
		return fmt.Errorf("recovery_blocked_by_policy")
	}
	if err := checkTarget(); err != nil {
		return err
	}
	staging, err := os.MkdirTemp(parent, ".agent-manager-restore-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(staging)
	if err := copyDir(item.QuarantinePath, staging); err != nil {
		return err
	}
	if err := checkObservedContent(Skill{Path: staging, Signature: expected}); err != nil {
		return err
	}
	if err := checkTarget(); err != nil {
		return err
	}
	var replaced QuarantineItem
	if restoringBackup && expectedTarget != "" {
		replaced, err = quarantineSkill(home, store, agent.AgentType, item.SkillName, path, "before_restore_backup", expectedTarget)
		if err != nil {
			return err
		}
	}
	if err := os.Rename(staging, path); err != nil {
		if replaced.ID != "" {
			if _, statErr := os.Lstat(path); os.IsNotExist(statErr) {
				_ = copyDir(replaced.QuarantinePath, path)
			}
		}
		return err
	}
	if _, err := store.db.Exec(`UPDATE client_quarantine SET status='restored', restored_at=? WHERE id=?`, time.Now().UTC().Format(time.RFC3339Nano), item.ID); err != nil {
		return err
	}
	if err := store.SaveObservation(path, observation); err != nil {
		return err
	}
	if err := store.SetState(fmt.Sprintf("skill-action-receipt:%d", task.ID), item.ID); err != nil {
		return err
	}
	_ = RequestFullScan(home)
	policyVersion := policy.Mode
	if policy.Classification != nil {
		policyVersion = policy.Classification.Version
	}
	return reportEvent(ctx, api, store, inventory.ClientID, "skill_governance_action", agent.AgentType, item.SkillName, map[string]any{
		"path": path, "signature": expected, "action": stringValue(task.Payload, "action"), "quarantine_id": item.ID,
		"task_id": task.ID, "source": "manual", "actor": task.Payload["actor"], "status": "completed",
		"policy_version": policyVersion,
	})
}
