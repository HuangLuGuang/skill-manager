-- Schema from 319f92d1af12a2e2cf946d99737170ae5f75e8ea scanner/internal/managedclient/store.go
BEGIN TRANSACTION;
CREATE TABLE client_events_queue (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			client_id TEXT NOT NULL,
			event_type TEXT NOT NULL,
			agent_type TEXT,
			skill_name TEXT,
			details_json TEXT NOT NULL,
			created_at TEXT NOT NULL
		);
CREATE TABLE client_exclusions (
			path TEXT PRIMARY KEY,
			created_at TEXT NOT NULL
		);
CREATE TABLE client_installs (
			agent_type TEXT NOT NULL,
			managed_agent_id TEXT NOT NULL,
			skill_id TEXT NOT NULL,
			skill_name TEXT NOT NULL,
			target_path TEXT NOT NULL,
			manifest_json TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(agent_type, skill_id)
		);
CREATE TABLE client_notifications (
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
CREATE TABLE client_pending (
			id TEXT PRIMARY KEY,
			agent_type TEXT NOT NULL,
			skill_name TEXT NOT NULL,
			original_path TEXT NOT NULL,
			pending_path TEXT NOT NULL UNIQUE,
			reason TEXT NOT NULL,
			status TEXT NOT NULL,
			skill_id TEXT,
			version_id TEXT,
			content_fingerprint TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL,
			submitted_at TEXT
		);
CREATE TABLE client_quarantine (
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
CREATE TABLE client_state (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
CREATE TABLE client_tasks (
			task_id INTEGER PRIMARY KEY,
			status TEXT NOT NULL,
			error TEXT,
			updated_at TEXT NOT NULL
		, task_json TEXT NOT NULL DEFAULT '{}');
DELETE FROM "sqlite_sequence";
COMMIT;
