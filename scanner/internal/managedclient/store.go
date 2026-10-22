package managedclient

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"time"

	"skill-manager/scanner/internal/localize"

	_ "modernc.org/sqlite"
)

var ErrPendingNotFound = errors.New("pending_not_found")

type Store struct {
	db   *sql.DB
	root string
}

type LocalStatus struct {
	Classification      *ClassificationPolicy `json:"classification,omitempty"`
	Sync                map[string]SyncStatus `json:"sync"`
	ManagedSkills       int                   `json:"managed_skills"`
	GovernanceEnabled   bool                  `json:"governance_enabled"`
	PendingSkills       int                   `json:"pending_skills"`
	QuarantinedSkills   int                   `json:"quarantined_skills"`
	QueuedEvents        int                   `json:"queued_events"`
	LastInventoryAt     string                `json:"last_inventory_at,omitempty"`
	LastFullScanAt      string                `json:"last_full_scan_at,omitempty"`
	NextFullScanAt      string                `json:"next_full_scan_at,omitempty"`
	PatrolFindings      []PatrolFinding       `json:"patrol_findings"`
	Tasks               []LocalTask           `json:"tasks"`
	UnreadNotifications int                   `json:"unread_notifications"`
	Notifications       []LocalNotification   `json:"notifications"`
	ClientUpdates       ClientUpdateVersions  `json:"client_updates"`
}

type SyncStatus struct {
	LastSuccessAt string `json:"last_success_at,omitempty"`
	Error         string `json:"error,omitempty"`
}

type LocalNotification struct {
	Details     map[string]string `json:"details,omitempty"`
	ID          int64             `json:"id"`
	Severity    string            `json:"severity"`
	EventType   string            `json:"event_type"`
	AgentType   string            `json:"agent_type"`
	SkillName   string            `json:"skill_name"`
	Title       string            `json:"title"`
	Message     string            `json:"message"`
	CreatedAt   string            `json:"created_at"`
	DeliveredAt string            `json:"delivered_at,omitempty"`
	ReadAt      string            `json:"read_at,omitempty"`
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
			version_id TEXT,
			version_no INTEGER NOT NULL DEFAULT 0,
			source_version TEXT NOT NULL DEFAULT '',
			content_fingerprint TEXT NOT NULL DEFAULT '',
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
		CREATE TABLE IF NOT EXISTS client_ui_events (
			revision INTEGER PRIMARY KEY AUTOINCREMENT,
			event_type TEXT NOT NULL,
			details_json TEXT NOT NULL DEFAULT '{}',
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
	if _, err := db.Exec(`ALTER TABLE client_pending ADD COLUMN content_fingerprint TEXT NOT NULL DEFAULT ''`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec(`ALTER TABLE client_pending ADD COLUMN version_id TEXT`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec(`ALTER TABLE client_pending ADD COLUMN version_no INTEGER NOT NULL DEFAULT 0`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec(`ALTER TABLE client_pending ADD COLUMN source_version TEXT NOT NULL DEFAULT ''`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec(`ALTER TABLE client_pending ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}'`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec(`ALTER TABLE client_notifications ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'`); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
		db.Close()
		return nil, err
	}
	store := &Store{db: db, root: filepath.Dir(path)}
	if err := store.initEventQueue(); err != nil {
		db.Close()
		return nil, err
	}
	if err := store.migrateRepeatedGovernanceNotifications(); err != nil {
		db.Close()
		return nil, err
	}
	if err := store.initScanHistory(); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func (store *Store) migrateRepeatedGovernanceNotifications() error {
	const migrationKey = "migration:collapse-repeated-governance-notifications-v1"
	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var completed string
	if err := tx.QueryRow(`SELECT value FROM client_state WHERE key = ?`, migrationKey).Scan(&completed); err == nil {
		return tx.Commit()
	} else if err != sql.ErrNoRows {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM client_notifications
		WHERE event_type = 'skill_governance_detected'
		  AND id NOT IN (
			SELECT MIN(id)
			FROM client_notifications
			WHERE event_type = 'skill_governance_detected'
			GROUP BY agent_type, skill_name, details_json
		  )`); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`INSERT INTO client_state(key,value,updated_at) VALUES(?,?,?)`,
		migrationKey, "1", time.Now().UTC().Format(time.RFC3339Nano),
	); err != nil {
		return err
	}
	return tx.Commit()
}

type ScanProgress struct {
	Stage     string            `json:"stage,omitempty"`
	Analyzers map[string]string `json:"analyzers,omitempty"`
	VersionID string            `json:"version_id,omitempty"`
	UpdatedAt string            `json:"updated_at,omitempty"`
}

type PendingItem struct {
	AutoInstallError string       `json:"auto_install_error,omitempty"`
	Progress         ScanProgress `json:"progress"`
	ID               string       `json:"id"`
	AgentType        string       `json:"agent_type"`
	SkillName        string       `json:"skill_name"`
	OriginalPath     string       `json:"original_path,omitempty"`
	PendingPath      string       `json:"pending_path"`
	Reason           string       `json:"reason"`
	Status           string       `json:"status"`
	SkillID          string       `json:"skill_id,omitempty"`
	VersionID        string       `json:"version_id,omitempty"`
	VersionNo        int          `json:"version_no,omitempty"`
	SourceVersion    string       `json:"source_version,omitempty"`
	Fingerprint      string       `json:"content_fingerprint,omitempty"`
	CreatedAt        string       `json:"created_at"`
	SubmittedAt      string       `json:"submitted_at,omitempty"`
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
		`INSERT INTO client_pending(id, agent_type, skill_name, original_path, pending_path, reason, status, skill_id, version_id, version_no, source_version, content_fingerprint, created_at, submitted_at)
		 VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		 ON CONFLICT(pending_path) DO UPDATE SET
		   original_path=excluded.original_path,
		   reason=excluded.reason,
		   content_fingerprint=CASE
		     WHEN excluded.content_fingerprint <> '' THEN excluded.content_fingerprint
		     ELSE client_pending.content_fingerprint
		   END`,
		item.ID, item.AgentType, item.SkillName, item.OriginalPath, item.PendingPath,
		item.Reason, item.Status, item.SkillID, item.VersionID, item.VersionNo, item.SourceVersion, item.Fingerprint, item.CreatedAt, nullableString(item.SubmittedAt),
	)
	return err
}

func (store *Store) PendingItems() ([]PendingItem, error) {
	rows, err := store.db.Query(
		`SELECT id, agent_type, skill_name, original_path, pending_path, reason, status,
		        COALESCE(skill_id, ''), COALESCE(version_id, ''), version_no, source_version, COALESCE(content_fingerprint, ''), created_at, COALESCE(submitted_at, ''), progress_json,
		        COALESCE((SELECT value FROM client_state WHERE key = 'pending:install-error:' || client_pending.id), '')
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
		var progress string
		if err := rows.Scan(&item.ID, &item.AgentType, &item.SkillName, &item.OriginalPath, &item.PendingPath, &item.Reason, &item.Status, &item.SkillID, &item.VersionID, &item.VersionNo, &item.SourceVersion, &item.Fingerprint, &item.CreatedAt, &item.SubmittedAt, &progress, &item.AutoInstallError); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(progress), &item.Progress); err != nil {
			return nil, err
		}
		version := item.VersionID
		if version == "" {
			version = item.SkillID
		}
		if version == "" || item.Progress.VersionID != version || item.Status != "PENDING" {
			item.Progress = ScanProgress{}
		}
		if _, err := os.Stat(item.PendingPath); err != nil && !(item.Reason == "quarantine_rescan" && item.SkillID != "") {
			continue
		}
		known[canonicalExistingPath(item.PendingPath)] = true
		result = append(result, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	legacyRoots := []string{
		filepath.Join(filepath.Dir(store.root), ".river-security", "agent-manager", "pending"),
		filepath.Join(store.root, "pending"),
	}
	// Retained recovery copies already have a lifecycle record, including after
	// restoration. They must not be rediscovered as untracked pending folders.
	recoveryRows, err := store.db.Query(`SELECT quarantine_path FROM client_quarantine`)
	if err != nil {
		return nil, err
	}
	for recoveryRows.Next() {
		var path string
		if err := recoveryRows.Scan(&path); err != nil {
			recoveryRows.Close()
			return nil, err
		}
		known[canonicalExistingPath(path)] = true
	}
	err = recoveryRows.Err()
	recoveryRows.Close()
	if err != nil {
		return nil, err
	}
	legacy := []string{}
	for _, root := range legacyRoots {
		items, _ := filepath.Glob(filepath.Join(root, "*", "*"))
		legacy = append(legacy, items...)
	}
	for _, path := range legacy {
		info, statErr := os.Stat(path)
		if statErr != nil || !info.IsDir() || known[canonicalExistingPath(path)] {
			continue
		}
		known[canonicalExistingPath(path)] = true
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

func canonicalExistingPath(path string) string {
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return filepath.Clean(resolved)
	}
	return filepath.Clean(path)
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

func (store *Store) MarkPendingSubmitted(item PendingItem, skillID, versionID string) error {
	item.Status = "submitted"
	item.SkillID = skillID
	item.VersionID = versionID
	item.SubmittedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if err := store.SavePending(item); err != nil {
		return err
	}
	query := `UPDATE client_pending SET status = ?, skill_id = ?, version_id = ?, submitted_at = ? WHERE pending_path = ?`
	args := []any{item.Status, item.SkillID, item.VersionID, item.SubmittedAt, item.PendingPath}
	if item.Fingerprint != "" {
		query = `UPDATE client_pending SET status = ?, skill_id = ?, version_id = ?, submitted_at = ? WHERE content_fingerprint = ?`
		args = []any{item.Status, item.SkillID, item.VersionID, item.SubmittedAt, item.Fingerprint}
	}
	_, err := store.db.Exec(query, args...)
	return err
}

func (store *Store) UpdatePendingStatus(skillID, versionID, status string) error {
	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	rows, err := tx.Query(`SELECT id, agent_type, skill_name, status FROM client_pending WHERE skill_id=? AND COALESCE(version_id,'')=?`, skillID, versionID)
	if err != nil {
		return err
	}
	defer rows.Close()
	type pendingChange struct {
		ID        string `json:"pending_id"`
		AgentType string `json:"agent_type"`
		SkillName string `json:"skill_name"`
		Previous  string `json:"previous_status"`
	}
	var changes []pendingChange
	for rows.Next() {
		var change pendingChange
		if err := rows.Scan(&change.ID, &change.AgentType, &change.SkillName, &change.Previous); err != nil {
			return err
		}
		changes = append(changes, change)
	}
	if err := rows.Err(); err != nil {
		return err
	}
	if err := rows.Close(); err != nil {
		return err
	}
	if len(changes) == 0 {
		return fmt.Errorf("%w: %s/%s", ErrPendingNotFound, skillID, versionID)
	}
	changed := make([]pendingChange, 0, len(changes))
	for _, change := range changes {
		if change.Previous != status {
			changed = append(changed, change)
		}
	}
	if len(changed) == 0 {
		return tx.Commit()
	}
	if _, err := tx.Exec(`UPDATE client_pending SET status = ? WHERE skill_id = ? AND COALESCE(version_id, '') = ?`, status, skillID, versionID); err != nil {
		return err
	}
	ids := make([]string, 0, len(changed))
	for _, change := range changed {
		ids = append(ids, change.ID)
		if _, err := tx.Exec(`INSERT INTO client_state(key,value,updated_at) VALUES(?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`, "recovery:pending:"+change.ID, "queued", time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
			return err
		}
	}
	details, _ := json.Marshal(map[string]any{"pending_ids": ids, "skill_id": skillID, "version_id": versionID, "status": status, "changes": changed})
	created := time.Now().UTC().Format(time.RFC3339Nano)
	row, err := tx.Exec(`INSERT INTO client_ui_events(event_type, details_json, created_at) VALUES('pending_status_changed', ?, ?)`, string(details), created)
	if err != nil {
		return err
	}
	revision, err := row.LastInsertId()
	if err != nil {
		return err
	}
	for _, id := range ids {
		if _, err := tx.Exec(`UPDATE client_state SET value=?, updated_at=? WHERE key=?`, fmt.Sprintf("%d", revision), created, "recovery:pending:"+id); err != nil {
			return err
		}
		if status == "APPROVED" {
			// A prior not-yet-certified attempt must not impose the normal
			// retry throttle after the platform has just approved this copy.
			if _, err := tx.Exec(`DELETE FROM client_state WHERE key IN (?, ?)`, "quarantine:auto-restore:"+id, "quarantine:auto-restore:pending:"+id); err != nil {
				return err
			}
			if _, err := tx.Exec(`DELETE FROM client_state WHERE key IN (?, ?)`, "recovery:error:"+id, "recovery:error:pending:"+id); err != nil {
				return err
			}
		}
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	store.LogDiagnostic("info", "scan", "status_changed", map[string]any{"pending_ids": ids, "skill_id": skillID, "version_id": versionID, "status": status, "revision": revision})
	if pendingStatusTerminal(status) {
		store.LogDiagnostic("info", "scan", "pending_terminal_persisted", map[string]any{"pending_ids": ids, "skill_id": skillID, "version_id": versionID, "status": status, "revision": revision})
	}
	if status == "APPROVED" {
		store.LogDiagnostic("info", "recovery", "recovery_queued", map[string]any{"pending_ids": ids, "skill_id": skillID, "version_id": versionID, "revision": revision})
	}
	// The page may have performed this read. Wake the daemon through a durable
	// marker so it cannot miss an APPROVED transition between polls.
	home := filepath.Dir(store.root)
	if err := RequestWorkerWake(home); err != nil {
		return err
	}
	if err := WriteUIStateSignalRevision(home, "pending_status_changed", fmt.Sprintf("%d", revision)); err != nil {
		return err
	}
	store.LogDiagnostic("info", "desktop", "desktop_state_signal_written", map[string]any{"event_type": "pending_status_changed", "revision": revision})
	return nil
}

func (store *Store) PendingStatus(skillID, versionID string) (bool, string, error) {
	rows, err := store.db.Query(`SELECT status FROM client_pending WHERE skill_id=? AND COALESCE(version_id,'')=?`, skillID, versionID)
	if err != nil {
		return false, "", err
	}
	defer rows.Close()
	found := false
	status := ""
	consistent := true
	for rows.Next() {
		var current string
		if err := rows.Scan(&current); err != nil {
			return false, "", err
		}
		if !found {
			status = current
			found = true
		} else if current != status {
			consistent = false
		}
	}
	if err := rows.Err(); err != nil {
		return false, "", err
	}
	if !found {
		return false, "", nil
	}
	if !consistent {
		return true, "", nil
	}
	return true, status, nil
}

// EmitUIStateEvent persists a monotonic local revision before notifying the
// desktop client. The database row is the durable source; the marker file is
// only a wake-up hint and can safely be replayed after a restart.
func (store *Store) EmitUIStateEvent(home, eventType string, details map[string]any) error {
	payload, err := json.Marshal(details)
	if err != nil {
		return err
	}
	created := time.Now().UTC().Format(time.RFC3339Nano)
	result, err := store.db.Exec(`INSERT INTO client_ui_events(event_type, details_json, created_at) VALUES(?, ?, ?)`, eventType, string(payload), created)
	if err != nil {
		return err
	}
	revision, err := result.LastInsertId()
	if err != nil {
		return err
	}
	if err := WriteUIStateSignalRevision(home, eventType, fmt.Sprintf("%d", revision)); err != nil {
		return err
	}
	store.LogDiagnostic("info", "desktop", "desktop_state_signal_written", map[string]any{"event_type": eventType, "revision": revision})
	return nil
}

// ReplayLatestUIEvent bridges an event committed while the desktop process
// was stopped. It is intentionally best-effort: a later snapshot refresh is
// still authoritative if no event exists.
func (store *Store) ReplayLatestUIEvent(home string) error {
	revision, eventType, err := store.LatestUIEvent()
	if err == sql.ErrNoRows {
		return nil
	}
	if err != nil {
		return err
	}
	return WriteUIStateSignalRevision(home, eventType, fmt.Sprintf("%d", revision))
}

func (store *Store) LatestUIEvent() (int64, string, error) {
	var revision int64
	var eventType string
	err := store.db.QueryRow(`SELECT revision, event_type FROM client_ui_events ORDER BY revision DESC LIMIT 1`).Scan(&revision, &eventType)
	return revision, eventType, err
}

func (store *Store) UpdatePendingVersionMetadata(skillID, versionID string, versionNo int, sourceVersion string) error {
	_, err := store.db.Exec(
		`UPDATE client_pending SET version_no = ?, source_version = ? WHERE skill_id = ? AND COALESCE(version_id, '') = ?`,
		versionNo, sourceVersion, skillID, versionID,
	)
	return err
}

const resetPendingSubmissionSQL = `UPDATE client_pending
		 SET status = 'pending', skill_id = NULL, version_id = NULL, version_no = 0, source_version = '', submitted_at = NULL, progress_json = '{}'
		 WHERE id = ?`

func (store *Store) ResetPendingSubmission(id string) error {
	_, err := store.db.Exec(resetPendingSubmissionSQL, id)
	return err
}

func (store *Store) resetPendingForRescan(id string) error {
	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(resetPendingSubmissionSQL, id); err != nil {
		return err
	}
	if _, err := tx.Exec(`INSERT INTO client_state(key,value,updated_at) VALUES(?,'1',?)
		ON CONFLICT(key) DO UPDATE SET value='1',updated_at=excluded.updated_at`,
		"pending:force-rescan:"+id, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
		return err
	}
	return tx.Commit()
}

func (store *Store) UpdatePendingFingerprint(id, fingerprint string) error {
	_, err := store.db.Exec(`UPDATE client_pending SET content_fingerprint = ? WHERE id = ?`, fingerprint, id)
	return err
}

func (store *Store) LinkPendingGroup(fingerprint, status, skillID, versionID string, versionNo int, sourceVersion, submittedAt string) error {
	_, err := store.db.Exec(
		`UPDATE client_pending
		 SET status = ?, skill_id = ?, version_id = ?, version_no = ?, source_version = ?, submitted_at = ?
		 WHERE content_fingerprint = ?`,
		status, skillID, versionID, versionNo, sourceVersion, nullableString(submittedAt), fingerprint,
	)
	return err
}

func (store *Store) RemovePending(id string) error {
	return store.removePending(context.Background(), id)
}

func (store *Store) removePending(ctx context.Context, id string) error {
	home := filepath.Dir(store.root)
	releaseUpload, err := trySubmissionLock(home, "pending:"+id)
	if err != nil {
		if errors.Is(err, ErrAlreadyRunning) {
			return ErrSkillActionBusy
		}
		return err
	}
	defer releaseUpload()
	item, err := store.PendingItem(id)
	if err != nil {
		return err
	}
	_, release, err := withFileLocks(ctx, home, item.PendingPath)
	if err != nil {
		return err
	}
	defer release()
	if err := os.RemoveAll(item.PendingPath); err != nil {
		return err
	}
	_, err = store.db.Exec(`DELETE FROM client_pending WHERE id = ?`, id)
	return err
}

// ResolvePendingForInstall removes disabled-source records superseded by a
// trusted installation at the same Agent path. The path constraint prevents
// one Agent or custom root from clearing another same-name pending Skill.
func (store *Store) ResolvePendingForInstall(agentType, skillName, targetPath string) error {
	return store.resolvePendingForInstall(context.Background(), agentType, skillName, targetPath)
}

func (store *Store) resolvePendingForInstall(ctx context.Context, agentType, skillName, targetPath string) error {
	items, err := store.PendingItems()
	if err != nil {
		return err
	}
	targetPath = filepath.Clean(targetPath)
	for _, item := range items {
		if item.AgentType != agentType || item.SkillName != skillName || filepath.Clean(item.OriginalPath) != targetPath {
			continue
		}
		if err := store.removePending(ctx, item.ID); err != nil {
			return err
		}
	}
	return nil
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
	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(
		`DELETE FROM client_installs
		 WHERE agent_type = ? AND target_path = ? AND skill_id <> ?`,
		install.AgentType,
		install.TargetPath,
		install.SkillID,
	); err != nil {
		return err
	}
	if _, err = tx.Exec(
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
	); err != nil {
		return err
	}
	return tx.Commit()
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
	pendingItems, err := store.PendingItems()
	if err != nil {
		return err
	}
	pendingByID := map[string]PendingItem{}
	for _, item := range pendingItems {
		pendingByID[item.ID] = item
	}
	recovery, recoveryErr := store.QuarantineItems()
	if recoveryErr != nil {
		return recoveryErr
	}
	inventory.Recovery = recovery
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
			observation, observationErr := store.Observation(skill.Path)
			if observationErr != nil {
				return observationErr
			}
			if observation.Signature != "" {
				observation.Scan = nil
				if observation.Signature != skill.Signature {
					observation = classifyObservation(observation, *skill, nil)
					observation.ActionStatus = "pending"
				} else if observation.PendingID == strings.TrimPrefix(observationKey(skill.Path+":"+skill.Signature), "observation:") {
					pending, exists := pendingByID[observation.PendingID]
					if exists && pending.Reason == "observed_scan" && pending.OriginalPath == skill.Path {
						observation.Scan = &SkillScanObservation{Status: pending.Status, SkillID: pending.SkillID, VersionID: pending.VersionID, Progress: pending.Progress}
					} else if !exists {
						observation.PendingID = ""
					}
				}
				skill.Governance = &observation
			}
			install, ok := byPath[filepath.Clean(skill.Path)]
			if !ok {
				continue
			}
			skill.SkillID = install.SkillID
			skill.VersionID = install.Manifest.VersionID
			skill.VersionNo = install.Manifest.VersionNo
			skill.SourceVersion = install.Manifest.SourceVersion
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
	policy := cachedPolicy(store)
	result.Classification = policy.Classification
	if classificationEnabled(policy) {
		result.GovernanceEnabled = true
		result.ManagedSkills = 0
		body, exists, err := store.State("inventory")
		if err != nil {
			return result, err
		}
		if exists {
			var inventory Inventory
			if err := json.Unmarshal([]byte(body), &inventory); err != nil {
				return result, err
			}
			paths := map[string]bool{}
			for _, agent := range inventory.Agents {
				for _, skill := range agent.Skills {
					paths[filepath.Clean(skill.Path)] = true
				}
			}
			result.ManagedSkills = len(paths)
		}
	}
	result.Sync = map[string]SyncStatus{}
	for _, kind := range []string{"heartbeat", "inventory", "tasks", "worker", "scan_progress", "task_reports"} {
		last, _, err := store.State("sync:" + kind + ":success")
		if err != nil {
			return result, err
		}
		detail, _, err := store.State("sync:" + kind + ":error")
		if err != nil {
			return result, err
		}
		result.Sync[kind] = SyncStatus{LastSuccessAt: last, Error: detail}
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
	if body, ok, stateErr := store.State("client:update-versions"); stateErr != nil {
		return result, stateErr
	} else if ok && json.Unmarshal([]byte(body), &result.ClientUpdates) != nil {
		return result, fmt.Errorf("client update version state is invalid")
	}
	return result, nil
}

func (store *Store) RecordNotification(item LocalNotification) error {
	if item.Details == nil {
		item.Details = map[string]string{}
	}
	details, err := json.Marshal(item.Details)
	if err != nil {
		return err
	}
	cutoff := time.Now().UTC().Add(-5 * time.Minute).Format(time.RFC3339Nano)
	var exists int
	if err := store.db.QueryRow(
		`SELECT COUNT(*) FROM client_notifications WHERE event_type = ? AND agent_type = ? AND skill_name = ? AND details_json = ? AND created_at >= ?`,
		item.EventType, item.AgentType, item.SkillName, string(details), cutoff,
	).Scan(&exists); err != nil {
		return err
	}
	if exists > 0 {
		return nil
	}
	_, err = store.db.Exec(
		`INSERT INTO client_notifications(severity, event_type, agent_type, skill_name, title, message, created_at, details_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?)`,
		item.Severity, item.EventType, item.AgentType, item.SkillName, item.Title, item.Message, time.Now().UTC().Format(time.RFC3339Nano), string(details),
	)
	return err
}

func (store *Store) Notifications(limit int) ([]LocalNotification, error) {
	if limit <= 0 || limit > 200 {
		limit = 100
	}
	rows, err := store.db.Query(`SELECT id, severity, event_type, agent_type, skill_name, title, message, created_at, COALESCE(delivered_at, ''), COALESCE(read_at, ''), details_json FROM client_notifications ORDER BY id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []LocalNotification{}
	for rows.Next() {
		var item LocalNotification
		var details string
		if err := rows.Scan(&item.ID, &item.Severity, &item.EventType, &item.AgentType, &item.SkillName, &item.Title, &item.Message, &item.CreatedAt, &item.DeliveredAt, &item.ReadAt, &details); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(details), &item.Details); err != nil {
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
	rows, err := store.db.Query(`SELECT id, severity, event_type, agent_type, skill_name, title, message, created_at, '', COALESCE(read_at, ''), details_json FROM client_notifications WHERE delivered_at IS NULL ORDER BY id LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []LocalNotification{}
	for rows.Next() {
		var item LocalNotification
		var details string
		if err := rows.Scan(&item.ID, &item.Severity, &item.EventType, &item.AgentType, &item.SkillName, &item.Title, &item.Message, &item.CreatedAt, &item.DeliveredAt, &item.ReadAt, &details); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(details), &item.Details); err != nil {
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
	inventory.DiscoveryVersion = InventoryCacheVersion
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
	var previous string
	if key == "policy" {
		previous, _, _ = store.State(key)
	}
	_, err := store.db.Exec(
		`INSERT INTO client_state(key, value, updated_at) VALUES(?, ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`,
		key, value, time.Now().UTC().Format(time.RFC3339Nano),
	)
	if err == nil && key == "policy" && previous != value {
		var before, after Policy
		_ = json.Unmarshal([]byte(previous), &before)
		if json.Unmarshal([]byte(value), &after) == nil {
			if after.Classification != nil && (before.Classification == nil || !reflect.DeepEqual(before.Classification.DesktopMenuVisibility, after.Classification.DesktopMenuVisibility)) {
				if signalErr := store.EmitUIStateEvent(filepath.Dir(store.root), "desktop_menu_visibility_changed", nil); signalErr != nil {
					return signalErr
				}
			}
			fields := map[string]any{"mode": after.Mode, "classification": after.Classification, "full_scan_seconds": after.FullScanSeconds}
			if before.Classification != nil {
				fields["previous_version"] = before.Classification.Version
			}
			store.LogDiagnostic("info", "policy", "updated", fields)
		}
	}
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

func (store *Store) ResetForConnectionChange() error {
	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	now := time.Now().UTC().Format(time.RFC3339Nano)
	if _, err := tx.Exec(
		`INSERT INTO client_state(key, value, updated_at) VALUES('governance_enabled', '1', ?)
		 ON CONFLICT(key) DO UPDATE SET value='1', updated_at=excluded.updated_at`,
		now,
	); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`DELETE FROM client_state
		 WHERE key IN ('policy', 'patrol_findings', 'inventory', 'tasks:poll')
		    OR key LIKE 'patrol:%' OR key LIKE 'sync:%'
		    OR key LIKE 'observation:%' OR key LIKE 'observation-count:%'
		    OR key LIKE 'skill-action-receipt:%' OR key LIKE 'task:reported:%'
		    OR key LIKE 'pending:auto-install:%' OR key LIKE 'backup-restore-request:%'`,
	); err != nil {
		return err
	}
	// Task IDs and installation IDs are allocated by a platform. Keeping them
	// across connections can suppress a new task with the same numeric ID or
	// make a local Skill appear governed by an unrelated registry.
	if _, err := tx.Exec(`DELETE FROM client_tasks`); err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM client_installs`); err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM client_scan_history`); err != nil {
		return err
	}
	// Keep queued evidence bound to its original platform across switching.
	if _, err := tx.Exec(`DELETE FROM client_state WHERE key LIKE 'events:epoch:%'`); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE client_pending
		 SET status = 'pending', skill_id = NULL, version_id = NULL, version_no = 0, source_version = '', submitted_at = NULL, progress_json = '{}'
		 WHERE skill_id IS NOT NULL OR version_id IS NOT NULL`,
	); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`INSERT INTO client_notifications(severity, event_type, agent_type, skill_name, title, message, created_at)
		 VALUES('info', 'connection_changed_state_reset', '', '', ?, ?, ?)`,
		localize.Text("平台连接已变更", "Platform Connection Changed"),
		localize.Text("旧平台的认证、策略和任务关联已清理。本地副本已保留，客户端等待同步新平台策略。", "Previous platform certification, policy, and task associations have been cleared. Local copies are retained while the Client awaits the new platform policy."),
		now,
	); err != nil {
		return err
	}
	return tx.Commit()
}

type QueuedEvent struct {
	ID         int64
	CreatedAt  string
	ClientID   string
	EventType  string
	AgentType  string
	SkillName  string
	Details    map[string]any
	Server     string
	DeliveryID string
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

func (store *Store) StoredTask(taskID int64) (LocalTask, error) {
	rows, err := store.queryTasks(`SELECT task_id, status, COALESCE(error, ''), updated_at, task_json FROM client_tasks WHERE task_id=?`, taskID)
	if err != nil {
		return LocalTask{}, err
	}
	if len(rows) != 1 {
		return LocalTask{}, sql.ErrNoRows
	}
	return rows[0], nil
}

func (store *Store) InterruptAIDRTasks() error {
	_, err := store.db.Exec(`UPDATE client_tasks SET status='failed', error='aidr_desktop_task_interrupted' WHERE status='running' AND json_extract(task_json, '$.task_type')='aidr_plugin_action'`)
	return err
}

func (store *Store) TaskHistory(limit int) ([]LocalTask, error) {
	return store.queryTasks(
		`SELECT task_id, status, COALESCE(error, ''), updated_at, task_json FROM client_tasks ORDER BY updated_at DESC LIMIT ?`,
		limit,
	)
}

func (store *Store) PendingTasks() ([]LocalTask, error) {
	return store.queryTasks(`SELECT task_id, status, COALESCE(error, ''), updated_at, task_json
		FROM client_tasks WHERE status='pending' ORDER BY updated_at, task_id`)
}

func (store *Store) UnreportedTasks() ([]LocalTask, error) {
	return store.queryTasks(`SELECT task_id, status, COALESCE(error, ''), updated_at, task_json
		FROM client_tasks WHERE status IN ('succeeded', 'failed')
		AND NOT EXISTS (SELECT 1 FROM client_state WHERE key='task:reported:' || task_id AND value=status)
		ORDER BY updated_at, task_id`)
}

func (store *Store) queryTasks(query string, args ...any) ([]LocalTask, error) {
	rows, err := store.db.Query(query, args...)
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
	var previousStatus, previousError string
	_ = store.db.QueryRow("SELECT status,error FROM client_tasks WHERE task_id=?", task.ID).Scan(&previousStatus, &previousError)
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
	if err == nil && (previousStatus != status || previousError != taskError) {
		level := "info"
		if taskError != "" {
			level = "error"
		}
		store.LogDiagnostic(level, "tasks", "status_changed", map[string]any{"task_id": task.ID, "task_type": task.TaskType, "previous_status": previousStatus, "status": status, "error": taskError})
	}
	return err
}
