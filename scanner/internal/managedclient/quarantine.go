package managedclient

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"time"
)

type QuarantineItem struct {
	ID             string `json:"id"`
	AgentType      string `json:"agent_type"`
	SkillName      string `json:"skill_name"`
	OriginalPath   string `json:"original_path"`
	QuarantinePath string `json:"quarantine_path"`
	Reason         string `json:"reason"`
	Status         string `json:"status"`
	CreatedAt      string `json:"created_at"`
	RestoredAt     string `json:"restored_at,omitempty"`
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
		`SELECT id, agent_type, skill_name, original_path, quarantine_path, reason, status, created_at, COALESCE(restored_at, '')
		 FROM client_quarantine WHERE status = 'quarantined' ORDER BY created_at DESC`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []QuarantineItem{}
	for rows.Next() {
		var item QuarantineItem
		if err := rows.Scan(&item.ID, &item.AgentType, &item.SkillName, &item.OriginalPath, &item.QuarantinePath, &item.Reason, &item.Status, &item.CreatedAt, &item.RestoredAt); err != nil {
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
