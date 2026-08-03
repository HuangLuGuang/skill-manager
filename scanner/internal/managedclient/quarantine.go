package managedclient

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/localize"
	"skill-manager/scanner/internal/manifest"
)

type QuarantineItem struct {
	ID              string `json:"id"`
	AgentType       string `json:"agent_type"`
	SkillName       string `json:"skill_name"`
	OriginalPath    string `json:"original_path"`
	QuarantinePath  string `json:"quarantine_path"`
	Reason          string `json:"reason"`
	Status          string `json:"status"`
	CreatedAt       string `json:"created_at"`
	RestoredAt      string `json:"restored_at,omitempty"`
	PendingID       string `json:"pending_id,omitempty"`
	DetectionStatus string `json:"detection_status,omitempty"`
	SkillID         string `json:"skill_id,omitempty"`
	VersionID       string `json:"version_id,omitempty"`
}

func QuarantineSkill(home string, store *Store, agentType, skillName, source, reason string) (QuarantineItem, error) {
	now := time.Now().UTC()
	sum := sha256.Sum256([]byte(source + "\x00" + now.Format(time.RFC3339Nano)))
	id := now.Format("20060102T150405Z") + "-" + hex.EncodeToString(sum[:6])
	target := filepath.Join(QuarantineRoot(home), id, filepath.Base(source))
	if err := copyDir(source, target); err != nil {
		return QuarantineItem{}, err
	}
	item := QuarantineItem{
		ID: id, AgentType: agentType, SkillName: skillName, OriginalPath: source,
		QuarantinePath: target, Reason: reason, Status: "quarantined", CreatedAt: now.Format(time.RFC3339Nano),
	}
	_, err := store.db.Exec(
		`INSERT INTO client_quarantine(id, agent_type, skill_name, original_path, quarantine_path, reason, status, created_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?, ?)`,
		item.ID, item.AgentType, item.SkillName, item.OriginalPath, item.QuarantinePath, item.Reason, item.Status, item.CreatedAt,
	)
	if err != nil {
		_ = os.RemoveAll(filepath.Dir(target))
		return QuarantineItem{}, err
	}
	if err := os.RemoveAll(source); err != nil {
		_, _ = store.db.Exec(`DELETE FROM client_quarantine WHERE id = ?`, item.ID)
		_ = os.RemoveAll(filepath.Dir(target))
		return QuarantineItem{}, err
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
		 WHERE q.status = 'quarantined' ORDER BY q.created_at DESC`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
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
		result = append(result, item)
	}
	return result, rows.Err()
}

func (store *Store) ResolveQuarantine(agentType, skillName string) error {
	_, err := store.db.Exec(
		`UPDATE client_quarantine SET status = 'resolved', restored_at = ?
		 WHERE agent_type = ? AND skill_name = ? AND status = 'quarantined'`,
		time.Now().UTC().Format(time.RFC3339Nano), agentType, skillName,
	)
	return err
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
	if info, statErr := os.Stat(filepath.Join(quarantine.QuarantinePath, "SKILL.md")); statErr != nil || info.IsDir() {
		return PendingItem{}, fmt.Errorf("隔离内容缺少 SKILL.md，无法提交检测")
	}

	target := filepath.Join(
		PendingRoot(home),
		quarantine.AgentType,
		filepath.Base(quarantine.QuarantinePath)+"-quarantine-"+quarantine.ID,
	)
	pendingItemID := pendingID(target)
	if existing, existingErr := store.PendingItem(pendingItemID); existingErr == nil {
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
