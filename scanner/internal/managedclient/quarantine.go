package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/localize"
	"skill-manager/scanner/internal/manifest"
)

type QuarantineItem struct {
	Signature       string             `json:"signature"`
	ErrorCode       string             `json:"error_code,omitempty"`
	ID              string             `json:"id"`
	AgentType       string             `json:"agent_type"`
	SkillName       string             `json:"skill_name"`
	OriginalPath    string             `json:"original_path"`
	QuarantinePath  string             `json:"quarantine_path"`
	Reason          string             `json:"reason"`
	Status          string             `json:"status"`
	CreatedAt       string             `json:"created_at"`
	RestoredAt      string             `json:"restored_at,omitempty"`
	PendingID       string             `json:"pending_id,omitempty"`
	DetectionStatus string             `json:"detection_status,omitempty"`
	SkillID         string             `json:"skill_id,omitempty"`
	VersionID       string             `json:"version_id,omitempty"`
	AffectedTargets []QuarantineTarget `json:"affected_targets,omitempty"`
}

type QuarantineTarget struct {
	AgentType    string `json:"agent_type"`
	OriginalPath string `json:"original_path"`
	Status       string `json:"status"`
}

func QuarantineSkill(home string, store *Store, agentType, skillName, source, reason string) (QuarantineItem, error) {
	return quarantineCurrentSkill(context.Background(), home, store, agentType, skillName, source, reason, "")
}

func quarantineCurrentSkill(ctx context.Context, home string, store *Store, agentType, skillName, source, reason, expectedSignature string) (QuarantineItem, error) {
	_, release, err := withMutationLock(ctx, home)
	if err != nil {
		return QuarantineItem{}, err
	}
	defer release()
	if err := checkPatrolSnapshot(ctx, source); err != nil {
		return QuarantineItem{}, err
	}
	if expectedSignature == "" {
		state, err := inspectInstallTarget(source)
		if err != nil {
			return QuarantineItem{}, err
		}
		expectedSignature = state.signature
	}
	if expectedSignature == "" {
		return QuarantineItem{}, fmt.Errorf("skill_content_changed")
	}
	return quarantineSkill(home, store, agentType, skillName, source, reason, expectedSignature)
}

func quarantineSkill(home string, store *Store, agentType, skillName, source, reason, expectedSignature string) (result QuarantineItem, err error) {
	now := time.Now().UTC()
	sum := sha256.Sum256([]byte(source + "\x00" + now.Format(time.RFC3339Nano)))
	id := now.Format("20060102T150405Z") + "-" + hex.EncodeToString(sum[:6])
	root := filepath.Join(QuarantineRoot(home), id)
	if err := os.MkdirAll(QuarantineRoot(home), 0700); err != nil {
		return QuarantineItem{}, err
	}
	if err := os.Mkdir(root, 0700); err != nil {
		return QuarantineItem{}, err
	}
	retained := false
	defer func() {
		if !retained {
			err = errors.Join(err, removeOwnedCopy(root))
		}
	}()
	target := filepath.Join(root, filepath.Base(source))
	if err := copyRecoveryTree(source, target); err != nil {
		return QuarantineItem{}, err
	}
	if expectedSignature != "" {
		for _, path := range []string{source, target} {
			if err := checkObservedContent(Skill{Path: path, Signature: expectedSignature}); err != nil {
				return QuarantineItem{}, err
			}
		}
	}
	item := QuarantineItem{
		ID: id, AgentType: agentType, SkillName: skillName, OriginalPath: source,
		QuarantinePath: target, Reason: reason, Status: "quarantined", CreatedAt: now.Format(time.RFC3339Nano),
	}
	_, err = store.db.Exec(
		`INSERT INTO client_quarantine(id, agent_type, skill_name, original_path, quarantine_path, reason, status, created_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?, ?)`,
		item.ID, item.AgentType, item.SkillName, item.OriginalPath, item.QuarantinePath, item.Reason, item.Status, item.CreatedAt,
	)
	if err != nil {
		return QuarantineItem{}, err
	}
	retained = true
	if err := os.RemoveAll(source); err != nil {
		item.Status = "quarantine_failed"
		_, _ = store.db.Exec(`UPDATE client_quarantine SET status='quarantine_failed' WHERE id=?`, item.ID)
		return item, err
	}
	return item, nil
}

func (store *Store) QuarantineItems() ([]QuarantineItem, error) {
	rows, err := store.db.Query(
		`SELECT q.id, q.agent_type, q.skill_name, q.original_path, q.quarantine_path,
		        q.reason, q.status, q.created_at, COALESCE(q.restored_at, ''),
		        COALESCE(p.id, ''), COALESCE(p.status, ''),
		        COALESCE(p.skill_id, ''), COALESCE(p.version_id, '')
		 FROM client_quarantine q
		 LEFT JOIN client_pending p ON p.id = (
		   SELECT p2.id FROM client_pending p2
		   WHERE p2.agent_type = q.agent_type
		     AND p2.original_path = q.original_path
		     AND p2.reason = 'quarantine_rescan'
		     AND p2.pending_path LIKE '%-quarantine-' || q.id
		   ORDER BY p2.created_at DESC LIMIT 1
		 )
		 WHERE q.status IN ('quarantined', 'uninstalled', 'quarantine_failed', 'backed_up') ORDER BY q.created_at DESC`,
	)
	if err != nil {
		return nil, err
	}
	result := []QuarantineItem{}
	for rows.Next() {
		var item QuarantineItem
		if err := rows.Scan(
			&item.ID, &item.AgentType, &item.SkillName, &item.OriginalPath,
			&item.QuarantinePath, &item.Reason, &item.Status, &item.CreatedAt,
			&item.RestoredAt, &item.PendingID, &item.DetectionStatus,
			&item.SkillID, &item.VersionID,
		); err != nil {
			return nil, err
		}
		value, err := manifest.Build(item.QuarantinePath, DefaultManifestOptions())
		if err == nil {
			info, statErr := os.Lstat(filepath.Join(item.QuarantinePath, "SKILL.md"))
			if statErr != nil || !info.Mode().IsRegular() {
				err = fmt.Errorf("recovery_content_unavailable")
			}
		}
		if err == nil {
			item.Signature = manifest.ContentSignature(value.Files)
		} else {
			item.ErrorCode = "recovery_content_unavailable"
		}
		result = append(result, item)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, err
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	// The store uses a single SQLite connection. Resolve persisted recovery
	// errors only after closing the result cursor above; querying client_state
	// while rows is open would deadlock the connection pool.
	for index := range result {
		if persisted, ok, stateErr := store.State("recovery:error:" + result[index].ID); stateErr == nil && ok && strings.TrimSpace(persisted) != "" {
			result[index].ErrorCode = persisted
		}
	}

	targetRows, err := store.db.Query(
		`SELECT quarantine_path, agent_type, original_path, status
		 FROM client_quarantine
		 ORDER BY created_at, id`,
	)
	if err != nil {
		return nil, err
	}
	defer targetRows.Close()
	targetsByPath := map[string][]QuarantineTarget{}
	for targetRows.Next() {
		var quarantinePath string
		var target QuarantineTarget
		if err := targetRows.Scan(&quarantinePath, &target.AgentType, &target.OriginalPath, &target.Status); err != nil {
			return nil, err
		}
		targetsByPath[quarantinePath] = append(targetsByPath[quarantinePath], target)
	}
	if err := targetRows.Err(); err != nil {
		return nil, err
	}
	for index := range result {
		result[index].AffectedTargets = targetsByPath[result[index].QuarantinePath]
	}
	return result, nil
}

func (store *Store) ResolveQuarantine(agentType, skillName string) error {
	_, err := store.db.Exec(
		`UPDATE client_quarantine SET status = 'resolved', restored_at = ?
		 WHERE agent_type = ? AND skill_name = ? AND status = 'quarantined'`,
		time.Now().UTC().Format(time.RFC3339Nano), agentType, skillName,
	)
	return err
}

// A permitted live path ends its previous automatic isolation incident. The
// retained copy remains historical evidence, even if the application recreated
// the path with newer content rather than restoring the original bytes.
func (store *Store) resolvePermittedUnverifiedCopy(ctx context.Context, home, agentType string, skill Skill, policy Policy, observation SkillObservation) error {
	if !classificationEnabled(policy) || observation.ActionStatus != "completed" || observation.ErrorCode != "" || observation.Malicious {
		return nil
	}
	if observation.Trigger != "unverified" && observation.Trigger != "unverified_content_changed" {
		return nil
	}
	if (observation.Action != "record" && observation.Action != "record_only") || policy.Classification.Rules[observation.Trigger] != observation.Action {
		return nil
	}
	var count int
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_quarantine
		WHERE agent_type=? AND original_path=? AND status='quarantined'
		AND reason IN ('unverified','unverified_content_changed','unmanaged_skill')`, agentType, skill.Path).Scan(&count); err != nil || count == 0 {
		return err
	}
	_, release, err := withMutationLock(ctx, home)
	if err != nil {
		return err
	}
	defer release()
	if err := checkObservedContent(Skill{Path: skill.Path, Signature: observation.Signature}); err != nil {
		return err
	}
	result, err := store.db.Exec(`UPDATE client_quarantine SET status='resolved', restored_at=?
		WHERE agent_type=? AND original_path=? AND status='quarantined'
		AND reason IN ('unverified','unverified_content_changed','unmanaged_skill')`, time.Now().UTC().Format(time.RFC3339Nano), agentType, skill.Path)
	if err != nil {
		return err
	}
	changed, err := result.RowsAffected()
	if err != nil || changed == 0 {
		return err
	}
	details := map[string]any{"agent_type": agentType, "path": skill.Path, "skill_name": skill.Name, "resolved_count": changed, "source": "permitted_local_copy"}
	store.LogDiagnostic("info", "recovery", "present_copy_resolved", details)
	return store.EmitUIStateEvent(home, "local_state_changed", details)
}

// ResolveInstalledRecovery archives recovery records superseded by a verified
// trusted installation at the exact Agent path. An uninstalled record is only
// resolved when its retained content matches the installed release, so a
// different historical version remains available for review.
func (store *Store) ResolveInstalledRecovery(agentType, skillName, targetPath, installedSignature string) (bool, error) {
	items, err := store.QuarantineItems()
	if err != nil {
		return false, err
	}
	targetPath = filepath.Clean(targetPath)
	changed := false
	for _, item := range items {
		if item.AgentType != agentType || item.SkillName != skillName || filepath.Clean(item.OriginalPath) != targetPath {
			continue
		}
		if item.Status == "uninstalled" && (installedSignature == "" || item.Signature != installedSignature) {
			continue
		}
		if item.Status != "quarantined" && item.Status != "uninstalled" {
			continue
		}
		result, err := store.db.Exec(
			`UPDATE client_quarantine SET status='resolved', restored_at=?
			 WHERE id=? AND status IN ('quarantined','uninstalled')`,
			time.Now().UTC().Format(time.RFC3339Nano), item.ID,
		)
		if err != nil {
			return changed, err
		}
		if count, err := result.RowsAffected(); err == nil && count > 0 {
			changed = true
		}
	}
	return changed, nil
}

// DiscardQuarantine removes one retained recovery copy while preserving the
// current Agent path and the audit row. The selected signature is required so
// content changed after confirmation cannot be deleted accidentally.
func (store *Store) DiscardQuarantine(id, expectedSignature string) (QuarantineItem, error) {
	items, err := store.QuarantineItems()
	if err != nil {
		return QuarantineItem{}, err
	}
	var item QuarantineItem
	for _, candidate := range items {
		if candidate.ID == id {
			item = candidate
			break
		}
	}
	if item.ID == "" {
		return QuarantineItem{}, fmt.Errorf("quarantined Skill not found: %s", id)
	}
	if strings.TrimSpace(expectedSignature) == "" || item.Signature != expectedSignature {
		return QuarantineItem{}, fmt.Errorf("skill_content_changed")
	}
	if strings.TrimSpace(item.QuarantinePath) == "" {
		return QuarantineItem{}, fmt.Errorf("quarantine item has no local path: %s", id)
	}
	var linkedPending *PendingItem
	if item.PendingID != "" {
		pending, err := store.PendingItem(item.PendingID)
		if err == nil {
			linkedPending = &pending
		}
	}

	var otherReferences int
	if err := store.db.QueryRow(
		`SELECT COUNT(*) FROM client_quarantine
		 WHERE quarantine_path=? AND id<>? AND status IN ('quarantined','uninstalled','quarantine_failed','backed_up')`,
		item.QuarantinePath, item.ID,
	).Scan(&otherReferences); err != nil {
		return QuarantineItem{}, err
	}
	if otherReferences == 0 {
		if err := os.RemoveAll(item.QuarantinePath); err != nil {
			return QuarantineItem{}, fmt.Errorf(localize.Text("删除隔离副本失败: %w", "failed to remove quarantine copy: %w"), err)
		}
		_ = os.Remove(filepath.Dir(item.QuarantinePath))
	}
	if linkedPending != nil && filepath.Clean(linkedPending.PendingPath) != filepath.Clean(item.QuarantinePath) {
		if err := os.RemoveAll(linkedPending.PendingPath); err != nil {
			return QuarantineItem{}, fmt.Errorf(localize.Text("删除待处理副本失败: %w", "failed to remove pending copy: %w"), err)
		}
	}

	tx, err := store.db.Begin()
	if err != nil {
		return QuarantineItem{}, err
	}
	defer tx.Rollback()
	if item.PendingID != "" {
		if _, err := tx.Exec(`DELETE FROM client_pending WHERE id=?`, item.PendingID); err != nil {
			return QuarantineItem{}, err
		}
	}
	if _, err := tx.Exec(
		`UPDATE client_quarantine SET status='discarded', restored_at=? WHERE id=?`,
		time.Now().UTC().Format(time.RFC3339Nano), item.ID,
	); err != nil {
		return QuarantineItem{}, err
	}
	if err := tx.Commit(); err != nil {
		return QuarantineItem{}, err
	}
	item.Status = "discarded"
	return item, nil
}

// DiscardPending permanently removes one disabled local copy. If the pending
// item was created from an active quarantine item, that exact quarantine copy
// is removed as well. The original Agent path is deliberately never touched:
// it may already contain a subsequently installed trusted version.
func (store *Store) DiscardPending(id string) (PendingItem, error) {
	item, err := store.PendingItem(id)
	if err != nil {
		return PendingItem{}, err
	}

	var linkedQuarantine *QuarantineItem
	quarantined, err := store.QuarantineItems()
	if err != nil {
		return PendingItem{}, err
	}
	for index := range quarantined {
		if quarantined[index].PendingID == item.ID {
			linkedQuarantine = &quarantined[index]
			break
		}
	}

	if strings.TrimSpace(item.PendingPath) == "" {
		return PendingItem{}, fmt.Errorf("pending skill has no local path: %s", id)
	}
	if err := os.RemoveAll(item.PendingPath); err != nil {
		return PendingItem{}, fmt.Errorf(
			localize.Text("删除待处理副本失败: %w", "failed to remove pending copy: %w"),
			err,
		)
	}
	if linkedQuarantine != nil {
		if strings.TrimSpace(linkedQuarantine.QuarantinePath) == "" {
			return PendingItem{}, fmt.Errorf("quarantine item has no local path: %s", linkedQuarantine.ID)
		}
		var otherReferences int
		if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_quarantine WHERE quarantine_path=? AND id<>?`, linkedQuarantine.QuarantinePath, linkedQuarantine.ID).Scan(&otherReferences); err != nil {
			return PendingItem{}, err
		}
		if otherReferences == 0 {
			if err := os.RemoveAll(linkedQuarantine.QuarantinePath); err != nil {
				return PendingItem{}, fmt.Errorf(
					localize.Text("删除关联隔离副本失败: %w", "failed to remove linked quarantine copy: %w"),
					err,
				)
			}
			// The parent is dedicated to one quarantine event. Remove it only when
			// empty so an unexpected sibling can never be deleted recursively.
			_ = os.Remove(filepath.Dir(linkedQuarantine.QuarantinePath))
		}
	}

	tx, err := store.db.Begin()
	if err != nil {
		return PendingItem{}, err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`DELETE FROM client_pending WHERE id = ?`, item.ID); err != nil {
		return PendingItem{}, err
	}
	if linkedQuarantine != nil {
		if _, err := tx.Exec(`DELETE FROM client_quarantine WHERE id = ? AND status = 'quarantined'`, linkedQuarantine.ID); err != nil {
			return PendingItem{}, err
		}
	}
	if err := tx.Commit(); err != nil {
		return PendingItem{}, err
	}
	return item, nil
}

func QueueQuarantineForDetection(home string, store *Store, id string) (PendingItem, error) {
	return QueueQuarantineForDetectionExpected(home, store, id, "")
}

func QueueQuarantineForDetectionExpected(home string, store *Store, id, expectedSignature string) (PendingItem, error) {
	items, err := store.QuarantineItems()
	if err != nil {
		return PendingItem{}, err
	}
	var quarantine QuarantineItem
	for _, candidate := range items {
		if candidate.ID == id {
			quarantine = candidate
			break
		}
	}
	if quarantine.ID == "" {
		return PendingItem{}, fmt.Errorf("quarantined Skill not found: %s", id)
	}
	if expectedSignature != "" && quarantine.Signature != expectedSignature {
		return PendingItem{}, fmt.Errorf("skill_content_changed")
	}
	if info, statErr := os.Stat(filepath.Join(quarantine.QuarantinePath, "SKILL.md")); statErr != nil || info.IsDir() {
		return PendingItem{}, fmt.Errorf("隔离内容缺少 SKILL.md，无法提交检测")
	}

	// One retained directory can back several Agent links. Queue one pending
	// target per active link so one platform verdict can restore every affected
	// Agent independently; a failed target remains available for retry.
	var selected PendingItem
	for _, candidate := range items {
		if candidate.QuarantinePath != quarantine.QuarantinePath {
			continue
		}
		pending, err := queueQuarantineTarget(home, store, candidate, expectedSignature)
		if err != nil {
			return PendingItem{}, err
		}
		if candidate.ID == quarantine.ID {
			selected = pending
		}
	}
	if selected.ID == "" {
		return PendingItem{}, fmt.Errorf("quarantined Skill not found: %s", id)
	}
	return selected, nil
}

func queueQuarantineTarget(home string, store *Store, quarantine QuarantineItem, expectedSignature string) (PendingItem, error) {
	target := filepath.Join(
		PendingRoot(home),
		quarantine.AgentType,
		filepath.Base(quarantine.QuarantinePath)+"-quarantine-"+quarantine.ID,
	)
	pendingItemID := pendingID(target)
	if existing, existingErr := store.PendingItem(pendingItemID); existingErr == nil {
		if expectedSignature != "" {
			value, buildErr := manifest.Build(existing.PendingPath, DefaultManifestOptions())
			if buildErr != nil || manifest.ContentSignature(value.Files) != expectedSignature {
				return PendingItem{}, fmt.Errorf("skill_content_changed")
			}
		}
		return existing, nil
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
		return PendingItem{}, err
	}
	if err := copyDir(quarantine.QuarantinePath, target); err != nil {
		return PendingItem{}, err
	}
	value, err := manifest.Build(target, DefaultManifestOptions())
	if err != nil {
		_ = os.RemoveAll(target)
		return PendingItem{}, err
	}
	if expectedSignature != "" && manifest.ContentSignature(value.Files) != expectedSignature {
		_ = os.RemoveAll(target)
		return PendingItem{}, fmt.Errorf("skill_content_changed")
	}
	pending := PendingItem{
		ID:           pendingItemID,
		AgentType:    quarantine.AgentType,
		SkillName:    quarantine.SkillName,
		OriginalPath: quarantine.OriginalPath,
		PendingPath:  target,
		Reason:       "quarantine_rescan",
		Fingerprint:  value.Fingerprint,
	}
	if err := store.SavePending(pending); err != nil {
		_ = os.RemoveAll(target)
		return PendingItem{}, err
	}
	return store.PendingItem(pending.ID)
}
