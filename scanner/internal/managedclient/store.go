package managedclient

import (
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

type Store struct {
	db   *sql.DB
	root string
}

type LocalStatus struct {
	ManagedSkills       int                 `json:"managed_skills"`
	GovernanceEnabled   bool                `json:"governance_enabled"`
	PendingSkills       int                 `json:"pending_skills"`
	QuarantinedSkills   int                 `json:"quarantined_skills"`
	QueuedEvents        int                 `json:"queued_events"`
	LastInventoryAt     string              `json:"last_inventory_at,omitempty"`
	LastFullScanAt      string              `json:"last_full_scan_at,omitempty"`
	NextFullScanAt      string              `json:"next_full_scan_at,omitempty"`
	PatrolFindings      []PatrolFinding     `json:"patrol_findings"`
	Tasks               []LocalTask         `json:"tasks"`
	UnreadNotifications int                 `json:"unread_notifications"`
	Notifications       []LocalNotification `json:"notifications"`
}

type LocalNotification struct {
	ID          int64  `json:"id"`
	Severity    string `json:"severity"`
	EventType   string `json:"event_type"`
	AgentType   string `json:"agent_type"`
	SkillName   string `json:"skill_name"`
	Title       string `json:"title"`
	Message     string `json:"message"`
	CreatedAt   string `json:"created_at"`
	DeliveredAt string `json:"delivered_at,omitempty"`
	ReadAt      string `json:"read_at,omitempty"`
}

type LocalTask struct {
	Task
	Status    string `json:"status"`
	Error     string `json:"error,omitempty"`
	UpdatedAt string `json:"updated_at"`
}

type PatrolFinding struct {
	EventType string `json:"event_type"`
	AgentType string `json:"agent_type"`
	SkillName string `json:"skill_name"`
}

func OpenStore(path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	_, statErr := os.Stat(path)
	newDatabase := os.IsNotExist(statErr)
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(`PRAGMA busy_timeout=5000`); err != nil {
		db.Close()
		return nil, err
	}
	if newDatabase {
		if _, err := db.Exec(`PRAGMA journal_mode=WAL`); err != nil {
			db.Close()
			return nil, err
		}
	}
	if _, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS client_state (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS client_tasks (
			task_id INTEGER PRIMARY KEY,
			status TEXT NOT NULL,
			error TEXT,
			updated_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS client_installs (
			agent_type TEXT NOT NULL,
			managed_agent_id TEXT NOT NULL,
			skill_id TEXT NOT NULL,
			skill_name TEXT NOT NULL,
			target_path TEXT NOT NULL,
			manifest_json TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(agent_type, skill_id)
		);
		CREATE TABLE IF NOT EXISTS client_quarantine (
			id TEXT PRIMARY KEY,
			agent_type TEXT NOT NULL,
			skill_name TEXT NOT NULL,
			original_path TEXT NOT NULL,
			quarantine_path TEXT NOT NULL,
			reason TEXT NOT NULL,
			status TEXT NOT NULL,
			created_at TEXT NOT NULL,
			restored_at TEXT
		);
		CREATE TABLE IF NOT EXISTS client_pending (
			id TEXT PRIMARY KEY,
			agent_type TEXT NOT NULL,
			skill_name TEXT NOT NULL,
			original_path TEXT NOT NULL,
			pending_path TEXT NOT NULL UNIQUE,
			reason TEXT NOT NULL,
			status TEXT NOT NULL,
			skill_id TEXT,
			created_at TEXT NOT NULL,
			submitted_at TEXT
		);
		CREATE TABLE IF NOT EXISTS client_events_queue (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			client_id TEXT NOT NULL,
			event_type TEXT NOT NULL,
			agent_type TEXT,
			skill_name TEXT,
			details_json TEXT NOT NULL,
			created_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS client_exclusions (
			path TEXT PRIMARY KEY,
			created_at TEXT NOT NULL
		);
		CREATE TABLE IF NOT EXISTS client_notifications (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			severity TEXT NOT NULL,
			event_type TEXT NOT NULL,
			agent_type TEXT NOT NULL,
			skill_name TEXT NOT NULL,
			title TEXT NOT NULL,
			message TEXT NOT NULL,
			created_at TEXT NOT NULL,
			delivered_at TEXT,
			read_at TEXT
		);
	`); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec(`ALTER TABLE client_tasks ADD COLUMN task_json TEXT NOT NULL DEFAULT '{}'`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	return &Store{db: db, root: filepath.Dir(path)}, nil
}

type PendingItem struct {
	ID           string `json:"id"`
	AgentType    string `json:"agent_type"`
	SkillName    string `json:"skill_name"`
	OriginalPath string `json:"original_path,omitempty"`
	PendingPath  string `json:"pending_path"`
	Reason       string `json:"reason"`
	Status       string `json:"status"`
	SkillID      string `json:"skill_id,omitempty"`
	CreatedAt    string `json:"created_at"`
	SubmittedAt  string `json:"submitted_at,omitempty"`
}

func pendingID(path string) string {
	digest := sha256.Sum256([]byte(filepath.Clean(path)))
	return fmt.Sprintf("%x", digest[:8])
}

func (store *Store) SavePending(item PendingItem) error {
	if item.ID == "" {
		item.ID = pendingID(item.PendingPath)
	}
	if item.Status == "" {
		item.Status = "pending"
	}
	if item.CreatedAt == "" {
		item.CreatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	_, err := store.db.Exec(
		`INSERT INTO client_pending(id, agent_type, skill_name, original_path, pending_path, reason, status, skill_id, created_at, submitted_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(pending_path) DO UPDATE SET
		   original_path=excluded.original_path,
		   reason=excluded.reason`,
		item.ID, item.AgentType, item.SkillName, item.OriginalPath, item.PendingPath,
		item.Reason, item.Status, item.SkillID, item.CreatedAt, nullableString(item.SubmittedAt),
	)
	return err
}

func (store *Store) PendingItems() ([]PendingItem, error) {
	rows, err := store.db.Query(
		`SELECT id, agent_type, skill_name, original_path, pending_path, reason, status,
		        COALESCE(skill_id, ''), created_at, COALESCE(submitted_at, '')
		 FROM client_pending ORDER BY created_at DESC`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []PendingItem{}
	known := map[string]bool{}
	for rows.Next() {
		var item PendingItem
		if err := rows.Scan(&item.ID, &item.AgentType, &item.SkillName, &item.OriginalPath, &item.PendingPath, &item.Reason, &item.Status, &item.SkillID, &item.CreatedAt, &item.SubmittedAt); err != nil {
			return nil, err
		}
		if _, err := os.Stat(item.PendingPath); err != nil {
			continue
		}
		known[filepath.Clean(item.PendingPath)] = true
		result = append(result, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	legacy, _ := filepath.Glob(filepath.Join(store.root, "pending", "*", "*"))
	for _, path := range legacy {
		info, statErr := os.Stat(path)
		if statErr != nil || !info.IsDir() || known[filepath.Clean(path)] {
			continue
		}
		result = append(result, PendingItem{
			ID:          pendingID(path),
			AgentType:   filepath.Base(filepath.Dir(path)),
			SkillName:   filepath.Base(path),
			PendingPath: path,
			Reason:      "legacy_pending",
			Status:      "pending",
			CreatedAt:   info.ModTime().UTC().Format(time.RFC3339Nano),
		})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].CreatedAt > result[j].CreatedAt })
	return result, nil
}

func (store *Store) PendingItem(id string) (PendingItem, error) {
	items, err := store.PendingItems()
	if err != nil {
		return PendingItem{}, err
	}
	for _, item := range items {
		if item.ID == id {
			return item, nil
		}
	}
	return PendingItem{}, fmt.Errorf("pending skill not found: %s", id)
}

func (store *Store) MarkPendingSubmitted(item PendingItem, skillID string) error {
	item.Status = "submitted"
	item.SkillID = skillID
	item.SubmittedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if err := store.SavePending(item); err != nil {
		return err
	}
	_, err := store.db.Exec(
		`UPDATE client_pending SET status = ?, skill_id = ?, submitted_at = ? WHERE pending_path = ?`,
		item.Status, item.SkillID, item.SubmittedAt, item.PendingPath,
	)
	return err
}

func (store *Store) UpdatePendingStatus(id, status string) error {
	_, err := store.db.Exec(`UPDATE client_pending SET status = ? WHERE id = ?`, status, id)
	return err
}

func (store *Store) RemovePending(id string) error {
	item, err := store.PendingItem(id)
	if err != nil {
		return err
	}
	if err := os.RemoveAll(item.PendingPath); err != nil {
		return err
	}
	_, err = store.db.Exec(`DELETE FROM client_pending WHERE id = ?`, id)
	return err
}

func nullableString(value string) any {
	if value == "" {
		return nil
	}
	return value
}

type Installation struct {
	AgentType      string
	ManagedAgentID string
	SkillID        string
	SkillName      string
	TargetPath     string
	Manifest       releaseManifest
}

func (store *Store) SaveInstall(install Installation) error {
	body, err := json.Marshal(install.Manifest)
	if err != nil {
		return err
	}
	_, err = store.db.Exec(
		`INSERT INTO client_installs(agent_type, managed_agent_id, skill_id, skill_name, target_path, manifest_json, updated_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(agent_type, skill_id) DO UPDATE SET
		   managed_agent_id=excluded.managed_agent_id,
		   skill_name=excluded.skill_name,
		   target_path=excluded.target_path,
		   manifest_json=excluded.manifest_json,
		   updated_at=excluded.updated_at`,
		install.AgentType,
		install.ManagedAgentID,
		install.SkillID,
		install.SkillName,
		install.TargetPath,
		string(body),
		time.Now().UTC().Format(time.RFC3339Nano),
	)
	return err
}

func (store *Store) Installations() ([]Installation, error) {
	rows, err := store.db.Query(
		`SELECT agent_type, managed_agent_id, skill_id, skill_name, target_path, manifest_json
		 FROM client_installs ORDER BY agent_type, skill_name`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Installation{}
	for rows.Next() {
		var item Installation
		var body string
		if err := rows.Scan(
			&item.AgentType,
			&item.ManagedAgentID,
			&item.SkillID,
			&item.SkillName,
			&item.TargetPath,
			&body,
		); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(body), &item.Manifest); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (store *Store) EnrichInventory(inventory *Inventory) error {
	installs, err := store.Installations()
	if err != nil {
		return err
	}
	byPath := map[string]Installation{}
	for _, install := range installs {
		byPath[filepath.Clean(install.TargetPath)] = install
	}
	for agentIndex := range inventory.Agents {
		for skillIndex := range inventory.Agents[agentIndex].Skills {
			skill := &inventory.Agents[agentIndex].Skills[skillIndex]
			install, ok := byPath[filepath.Clean(skill.Path)]
			if !ok {
				continue
			}
			skill.SkillID = install.SkillID
			skill.Status = "managed"
			skill.InstallMode = "copy"
			if info, statErr := os.Lstat(skill.Path); statErr == nil && info.Mode()&os.ModeSymlink != 0 {
				skill.InstallMode = "symlink"
			}
		}
	}
	return nil
}

func (store *Store) RemoveInstall(agentType, skillID string) error {
	_, err := store.db.Exec(`DELETE FROM client_installs WHERE agent_type = ? AND skill_id = ?`, agentType, skillID)
	return err
}

func (store *Store) Close() error {
	return store.db.Close()
}

func (store *Store) LocalStatus() (LocalStatus, error) {
	result := LocalStatus{PatrolFindings: []PatrolFinding{}, Tasks: []LocalTask{}, Notifications: []LocalNotification{}}
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_installs`).Scan(&result.ManagedSkills); err != nil {
		return result, err
	}
	var err error
	result.GovernanceEnabled, err = store.GovernanceEnabled()
	if err != nil {
		return result, err
	}
	pending, err := store.PendingItems()
	if err != nil {
		return result, err
	}
	result.PendingSkills = len(pending)
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_quarantine WHERE status = 'quarantined'`).Scan(&result.QuarantinedSkills); err != nil {
		return result, err
	}
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_events_queue`).Scan(&result.QueuedEvents); err != nil {
		return result, err
	}
	_ = store.db.QueryRow(`SELECT updated_at FROM client_state WHERE key = 'inventory'`).Scan(&result.LastInventoryAt)
	_ = store.db.QueryRow(`SELECT updated_at FROM client_state WHERE key = 'patrol:full'`).Scan(&result.LastFullScanAt)
	if last, parseErr := time.Parse(time.RFC3339Nano, result.LastFullScanAt); parseErr == nil {
		interval := 30 * time.Minute
		if body, ok, stateErr := store.State("policy"); stateErr == nil && ok {
			var policy Policy
			if json.Unmarshal([]byte(body), &policy) == nil && policy.FullScanSeconds > 0 {
				interval = time.Duration(policy.FullScanSeconds) * time.Second
			}
		}
		result.NextFullScanAt = last.Add(interval).Format(time.RFC3339Nano)
	}
	if body, ok, err := store.State("patrol_findings"); err == nil && ok {
		_ = json.Unmarshal([]byte(body), &result.PatrolFindings)
	}
	result.Tasks, err = store.TaskHistory(20)
	if err != nil {
		return result, err
	}
	result.Notifications, err = store.Notifications(100)
	if err != nil {
		return result, err
	}
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_notifications WHERE read_at IS NULL`).Scan(&result.UnreadNotifications); err != nil {
		return result, err
	}
	return result, nil
}

func (store *Store) RecordNotification(item LocalNotification) error {
	cutoff := time.Now().UTC().Add(-5 * time.Minute).Format(time.RFC3339Nano)
	var exists int
	if err := store.db.QueryRow(
		`SELECT COUNT(*) FROM client_notifications WHERE event_type = ? AND agent_type = ? AND skill_name = ? AND created_at >= ?`,
		item.EventType, item.AgentType, item.SkillName, cutoff,
	).Scan(&exists); err != nil {
		return err
	}
	if exists > 0 {
		return nil
	}
	_, err := store.db.Exec(
		`INSERT INTO client_notifications(severity, event_type, agent_type, skill_name, title, message, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)`,
		item.Severity, item.EventType, item.AgentType, item.SkillName, item.Title, item.Message, time.Now().UTC().Format(time.RFC3339Nano),
	)
	return err
}

func (store *Store) Notifications(limit int) ([]LocalNotification, error) {
	if limit <= 0 || limit > 200 {
		limit = 100
	}
	rows, err := store.db.Query(`SELECT id, severity, event_type, agent_type, skill_name, title, message, created_at, COALESCE(delivered_at, ''), COALESCE(read_at, '') FROM client_notifications ORDER BY id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []LocalNotification{}
	for rows.Next() {
		var item LocalNotification
		if err := rows.Scan(&item.ID, &item.Severity, &item.EventType, &item.AgentType, &item.SkillName, &item.Title, &item.Message, &item.CreatedAt, &item.DeliveredAt, &item.ReadAt); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) PendingNotifications(limit int) ([]LocalNotification, error) {
	if limit <= 0 {
		limit = 20
	}
	rows, err := store.db.Query(`SELECT id, severity, event_type, agent_type, skill_name, title, message, created_at, '', COALESCE(read_at, '') FROM client_notifications WHERE delivered_at IS NULL ORDER BY id LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []LocalNotification{}
	for rows.Next() {
		var item LocalNotification
		if err := rows.Scan(&item.ID, &item.Severity, &item.EventType, &item.AgentType, &item.SkillName, &item.Title, &item.Message, &item.CreatedAt, &item.DeliveredAt, &item.ReadAt); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) MarkNotificationDelivered(id int64) error {
	_, err := store.db.Exec(`UPDATE client_notifications SET delivered_at = ? WHERE id = ?`, time.Now().UTC().Format(time.RFC3339Nano), id)
	return err
}

func (store *Store) MarkNotificationsRead() error {
	_, err := store.db.Exec(`UPDATE client_notifications SET read_at = ? WHERE read_at IS NULL`, time.Now().UTC().Format(time.RFC3339Nano))
	return err
}

func (store *Store) MarkNotificationRead(id int64) error {
	_, err := store.db.Exec(`UPDATE client_notifications SET read_at = ? WHERE id = ?`, time.Now().UTC().Format(time.RFC3339Nano), id)
	return err
}

func (store *Store) ClearNotifications() error {
	_, err := store.db.Exec(`DELETE FROM client_notifications`)
	return err
}

func (store *Store) GovernanceEnabled() (bool, error) {
	value, ok, err := store.State("governance_enabled")
	return ok && value == "1", err
}

func (store *Store) SetGovernanceEnabled(enabled bool) error {
	value := "0"
	if enabled {
		value = "1"
	}
	return store.SetState("governance_enabled", value)
}

func (store *Store) ResetPatrolFindings() error {
	return store.SetState("patrol_findings", "[]")
}

func (store *Store) RecordPatrolFinding(finding PatrolFinding) error {
	var findings []PatrolFinding
	body, ok, err := store.State("patrol_findings")
	if err != nil {
		return err
	}
	if ok {
		_ = json.Unmarshal([]byte(body), &findings)
	}
	for index, item := range findings {
		if item.AgentType == finding.AgentType && item.SkillName == finding.SkillName {
			findings[index] = finding
			body, _ := json.Marshal(findings)
			return store.SetState("patrol_findings", string(body))
		}
	}
	findings = append(findings, finding)
	encoded, _ := json.Marshal(findings)
	return store.SetState("patrol_findings", string(encoded))
}

func (store *Store) SaveInventory(inventory Inventory) error {
	body, err := json.Marshal(inventory)
	if err != nil {
		return err
	}
	_, err = store.db.Exec(
		`INSERT INTO client_state(key, value, updated_at) VALUES('inventory', ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`,
		string(body),
		time.Now().UTC().Format(time.RFC3339Nano),
	)
	return err
}

func (store *Store) SetState(key, value string) error {
	_, err := store.db.Exec(
		`INSERT INTO client_state(key, value, updated_at) VALUES(?, ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`,
		key, value, time.Now().UTC().Format(time.RFC3339Nano),
	)
	return err
}

func (store *Store) State(key string) (string, bool, error) {
	var value string
	err := store.db.QueryRow(`SELECT value FROM client_state WHERE key = ?`, key).Scan(&value)
	if err == sql.ErrNoRows {
		return "", false, nil
	}
	return value, err == nil, err
}

type QueuedEvent struct {
	ID        int64
	ClientID  string
	EventType string
	AgentType string
	SkillName string
	Details   map[string]any
}

func (store *Store) QueueEvent(event QueuedEvent) error {
	details, err := json.Marshal(event.Details)
	if err != nil {
		return err
	}
	_, err = store.db.Exec(
		`INSERT INTO client_events_queue(client_id, event_type, agent_type, skill_name, details_json, created_at)
		 VALUES(?, ?, ?, ?, ?, ?)`,
		event.ClientID, event.EventType, event.AgentType, event.SkillName, string(details), time.Now().UTC().Format(time.RFC3339Nano),
	)
	return err
}

func (store *Store) QueuedEvents() ([]QueuedEvent, error) {
	rows, err := store.db.Query(
		`SELECT id, client_id, event_type, agent_type, skill_name, details_json
		 FROM client_events_queue ORDER BY id LIMIT 500`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []QueuedEvent{}
	for rows.Next() {
		var item QueuedEvent
		var agentType, skillName sql.NullString
		var details string
		if err := rows.Scan(&item.ID, &item.ClientID, &item.EventType, &agentType, &skillName, &details); err != nil {
			return nil, err
		}
		item.AgentType, item.SkillName = agentType.String, skillName.String
		if err := json.Unmarshal([]byte(details), &item.Details); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (store *Store) DeleteQueuedEvent(id int64) error {
	_, err := store.db.Exec(`DELETE FROM client_events_queue WHERE id = ?`, id)
	return err
}

func (store *Store) SaveTakeoverScope(selected, excluded []string) error {
	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, path := range selected {
		if _, err := tx.Exec(`DELETE FROM client_exclusions WHERE path = ?`, filepath.Clean(path)); err != nil {
			return err
		}
	}
	for _, path := range excluded {
		if _, err := tx.Exec(
			`INSERT OR IGNORE INTO client_exclusions(path, created_at) VALUES(?, ?)`,
			filepath.Clean(path), time.Now().UTC().Format(time.RFC3339Nano),
		); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (store *Store) IsExcluded(path string) (bool, error) {
	var value string
	err := store.db.QueryRow(`SELECT path FROM client_exclusions WHERE path = ?`, filepath.Clean(path)).Scan(&value)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (store *Store) MarkSeen(key string) (bool, error) {
	result, err := store.db.Exec(
		`INSERT OR IGNORE INTO client_state(key, value, updated_at) VALUES(?, '1', ?)`,
		key,
		time.Now().UTC().Format(time.RFC3339Nano),
	)
	if err != nil {
		return false, err
	}
	affected, err := result.RowsAffected()
	return affected == 1, err
}

func (store *Store) Due(key string, interval time.Duration) (bool, error) {
	var updated string
	err := store.db.QueryRow(`SELECT updated_at FROM client_state WHERE key = ?`, key).Scan(&updated)
	if err != nil && err != sql.ErrNoRows {
		return false, err
	}
	if err == nil {
		last, parseErr := time.Parse(time.RFC3339Nano, updated)
		if parseErr == nil && time.Since(last) < interval {
			return false, nil
		}
	}
	return true, nil
}

func (store *Store) MarkSchedule(key string) error {
	now := time.Now().UTC().Format(time.RFC3339Nano)
	_, err := store.db.Exec(
		`INSERT INTO client_state(key, value, updated_at) VALUES(?, '1', ?)
		 ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`,
		key,
		now,
	)
	return err
}

func (store *Store) TaskCompleted(taskID int64) (bool, error) {
	var status string
	err := store.db.QueryRow(`SELECT status FROM client_tasks WHERE task_id = ?`, taskID).Scan(&status)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return status == "succeeded", err
}

func (store *Store) TaskHistory(limit int) ([]LocalTask, error) {
	rows, err := store.db.Query(
		`SELECT task_id, status, COALESCE(error, ''), updated_at, task_json FROM client_tasks ORDER BY updated_at DESC LIMIT ?`,
		limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []LocalTask{}
	for rows.Next() {
		var item LocalTask
		var body string
		if err := rows.Scan(&item.ID, &item.Status, &item.Error, &item.UpdatedAt, &body); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(body), &item.Task)
		result = append(result, item)
	}
	return result, rows.Err()
}

func (store *Store) SaveTask(task Task, status, taskError string) error {
	body, err := json.Marshal(task)
	if err != nil {
		return err
	}
	_, err = store.db.Exec(
		`INSERT INTO client_tasks(task_id, status, error, updated_at, task_json) VALUES(?, ?, ?, ?, ?)
		 ON CONFLICT(task_id) DO UPDATE SET status=excluded.status, error=excluded.error, updated_at=excluded.updated_at, task_json=excluded.task_json`,
		task.ID,
		status,
		taskError,
		time.Now().UTC().Format(time.RFC3339Nano),
		string(body),
	)
	return err
}
