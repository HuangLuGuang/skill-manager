package managedclient

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/manifest"
)

func automaticRecoveryItems(store *Store, inventory Inventory) ([]QuarantineItem, error) {
	items, err := store.QuarantineItems()
	if err != nil {
		return nil, err
	}
	// Explicit isolation remains in place until an authorized restore request.
	automatic := items[:0]
	for _, item := range items {
		if item.Reason != "manual" {
			automatic = append(automatic, item)
		}
	}
	items = automatic
	pending, err := store.PendingItems()
	if err != nil {
		return nil, err
	}
	for _, p := range pending {
		if p.OriginalPath == "" {
			if agent, ok := findAgent(inventory, p.AgentType); ok {
				p.OriginalPath = pendingOriginalPath(p, agent)
			}
		}
		if p.Reason == "manual" || p.Reason == "observed_scan" || p.Reason == "quarantine_rescan" || p.OriginalPath == "" {
			continue
		}
		if _, err := os.Lstat(p.OriginalPath); !os.IsNotExist(err) {
			continue
		}
		root, err := filepath.EvalSymlinks(p.PendingPath)
		if err != nil {
			continue
		}
		if info, err := os.Lstat(filepath.Join(root, "SKILL.md")); err != nil || !info.Mode().IsRegular() {
			continue
		}
		value, err := manifest.Build(root, DefaultManifestOptions())
		if err != nil {
			continue
		}
		items = append(items, QuarantineItem{ID: "pending:" + p.ID, AgentType: p.AgentType, SkillName: p.SkillName,
			OriginalPath: p.OriginalPath, QuarantinePath: root, Signature: manifest.ContentSignature(value.Files),
			Reason: p.Reason, Status: "quarantined", CreatedAt: p.CreatedAt})
	}
	return items, nil
}

func restoreQuarantineTask(ctx context.Context, home string, inventory Inventory, agent Agent, api API, store *Store, task Task) error {
	return restoreQuarantine(ctx, home, inventory, agent, api, store, task, false)
}

func restoreQuarantine(ctx context.Context, home string, inventory Inventory, agent Agent, api API, store *Store, task Task, automatic bool) error {
	release, err := AcquireMutationLock(home)
	if err != nil {
		return err
	}
	defer release()
	var items []QuarantineItem
	if automatic {
		items, err = automaticRecoveryItems(store, inventory)
	} else {
		items, err = store.QuarantineItems()
	}
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
	if automatic && (!comparison.Certified || comparison.Malicious) {
		return fmt.Errorf("recovery_not_certified")
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
	if automatic && strings.HasPrefix(item.ID, "pending:") {
		tx, err := store.db.Begin()
		if err != nil {
			return err
		}
		defer tx.Rollback()
		if _, err = tx.Exec(`INSERT INTO client_quarantine(id,agent_type,skill_name,original_path,quarantine_path,reason,status,created_at,restored_at) VALUES(?,?,?,?,?,?,'restored',?,?)`, item.ID, item.AgentType, item.SkillName, path, item.QuarantinePath, item.Reason, item.CreatedAt, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
			return err
		}
		if _, err = tx.Exec(`DELETE FROM client_pending WHERE id=?`, strings.TrimPrefix(item.ID, "pending:")); err != nil {
			return err
		}
		if err = tx.Commit(); err != nil {
			return err
		}
	} else if _, err := store.db.Exec(`UPDATE client_quarantine SET status='restored', restored_at=? WHERE id=?`, time.Now().UTC().Format(time.RFC3339Nano), item.ID); err != nil {
		return err
	}
	if err := store.SaveObservation(path, observation); err != nil {
		return err
	}
	if !automatic {
		if err := store.SetState(fmt.Sprintf("skill-action-receipt:%d", task.ID), item.ID); err != nil {
			return err
		}
	}
	_ = RequestFullScan(home)
	policyVersion := policy.Mode
	if policy.Classification != nil {
		policyVersion = policy.Classification.Version
	}
	source := "manual"
	if automatic {
		source = "automatic"
	}
	return reportEvent(ctx, api, store, inventory.ClientID, "skill_governance_action", agent.AgentType, item.SkillName, map[string]any{
		"path": path, "signature": expected, "action": stringValue(task.Payload, "action"), "quarantine_id": item.ID,
		"task_id": task.ID, "source": source, "actor": task.Payload["actor"], "status": "completed",
		"policy_version": policyVersion,
	})
}

// ReconcileCertifiedQuarantine restores exact approved content even when the
// approval originated outside this client's pending submissions.
func ReconcileCertifiedQuarantine(ctx context.Context, home string, api API, store *Store, inventory Inventory) (bool, error) {
	items, err := automaticRecoveryItems(store, inventory)
	if err != nil {
		return false, err
	}
	changed := false
	for _, item := range items {
		if item.Status != "quarantined" || item.Signature == "" || item.ErrorCode != "" {
			continue
		}
		agent, ok := findAgent(inventory, item.AgentType)
		if !ok {
			continue
		}
		if _, err := os.Lstat(item.OriginalPath); !os.IsNotExist(err) {
			continue
		}
		key := "quarantine:auto-restore:" + item.ID
		due, err := store.Due(key, time.Minute)
		if err != nil {
			return changed, err
		}
		if !due {
			continue
		}
		if err := store.MarkSchedule(key); err != nil {
			return changed, err
		}
		task := Task{Payload: map[string]any{"action": "restore_quarantine", "path": item.OriginalPath, "expected_signature": item.Signature, "quarantine_id": item.ID}}
		err = restoreQuarantine(ctx, home, inventory, agent, api, store, task, true)
		if err != nil {
			if err.Error() == "recovery_not_certified" {
				continue
			}
			return changed, err
		}
		changed = true
	}
	return changed, nil
}
