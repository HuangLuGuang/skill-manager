package managedclient

import (
	"bytes"
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"
)

const diagnosticQueueLimit = 2000 // At most 125 MiB of records, independent of the local log rotation.

type diagnosticUploadConfig struct {
	EffectiveLevel string `json:"effective_level"`
	Destination    string `json:"destination"`
	ExpiresAt      string `json:"expires_at,omitempty"`
}

func (config diagnosticUploadConfig) minimum(now time.Time) int {
	if config.EffectiveLevel == "DEBUG" || config.EffectiveLevel == "INFO" {
		if expiry, err := time.Parse(time.RFC3339Nano, config.ExpiresAt); err == nil && !now.Before(expiry) {
			return diagnosticLevel("ERROR")
		}
	}
	return diagnosticLevel(config.EffectiveLevel)
}

type uploadedDiagnostic struct {
	ID string `json:"id"`
	DiagnosticRecord
	Aggregation *diagnosticAggregation `json:"aggregation,omitempty"`
}

type diagnosticAggregation struct {
	RepeatedCount int    `json:"repeated_count"`
	FirstAt       string `json:"first_at"`
	LastAt        string `json:"last_at"`
}

func diagnosticLevel(level string) int {
	switch strings.ToUpper(level) {
	case "DEBUG":
		return 10
	case "INFO":
		return 20
	case "WARN", "WARNING":
		return 30
	case "ERROR":
		return 40
	}
	return 0
}

func diagnosticOutbox(root string) (*sql.DB, error) {
	dir := filepath.Join(root, "diagnostic-upload")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", filepath.Join(dir, "queue.db"))
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	_, err = db.Exec(`PRAGMA busy_timeout=1000;
 PRAGMA journal_mode=WAL;
 CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, destination TEXT NOT NULL, priority INTEGER NOT NULL, body BLOB NOT NULL, created INTEGER NOT NULL);
 CREATE INDEX IF NOT EXISTS records_priority ON records(priority,created);
 CREATE TABLE IF NOT EXISTS losses (destination TEXT PRIMARY KEY, count INTEGER NOT NULL, reported INTEGER NOT NULL, epoch TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS error_groups (destination TEXT NOT NULL, fingerprint TEXT NOT NULL, body BLOB NOT NULL, first_at TEXT NOT NULL, last_at TEXT NOT NULL, repeats INTEGER NOT NULL, due INTEGER NOT NULL, PRIMARY KEY(destination,fingerprint));
 CREATE INDEX IF NOT EXISTS error_groups_due ON error_groups(due);
 CREATE TABLE IF NOT EXISTS error_rates (scope TEXT PRIMARY KEY, started INTEGER NOT NULL, used INTEGER NOT NULL);`)
	if err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

func diagnosticID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func enqueueDiagnostic(root string, record DiagnosticRecord) error {
	data, err := os.ReadFile(filepath.Join(root, "diagnostic-upload", "config.json"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	var config diagnosticUploadConfig
	if err = json.Unmarshal(data, &config); err != nil {
		return err
	}
	now := time.Now()
	minimum := config.minimum(now)
	priority := diagnosticLevel(record.Level)
	if diagnosticRecovery(record) {
		priority = 40
	}
	if minimum == 0 || priority < minimum || config.Destination == "" {
		return nil
	}
	record.Level = strings.ToUpper(record.Level)
	if record.Level == "WARNING" {
		record.Level = "WARN"
	}
	id, err := diagnosticID()
	if err != nil {
		return err
	}
	body, err := json.Marshal(uploadedDiagnostic{ID: id, DiagnosticRecord: record})
	if err != nil {
		return err
	}
	db, err := diagnosticOutbox(root)
	if err != nil {
		return err
	}
	defer db.Close()
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.Exec(`INSERT OR IGNORE INTO losses VALUES (?,0,0,?)`, config.Destination, id); err != nil {
		return err
	}
	if len(body) > 64*1024 || utf8.RuneCountInString(record.Module) > 1024 || utf8.RuneCountInString(record.Event) > 256 || utf8.RuneCountInString(record.Version) > 128 {
		if _, err = tx.Exec(`UPDATE losses SET count=count+1 WHERE destination=?`, config.Destination); err != nil {
			return err
		}
	} else {
		accept := true
		if record.Level == "ERROR" {
			accept, err = aggregateDiagnostic(tx, config.Destination, body, record, now)
		}
		if err != nil {
			return err
		}
		if accept {
			if diagnosticRecovery(record) {
				// The recovery includes the final failure count; don't emit a later repeat summary.
				_, err = tx.Exec(`DELETE FROM error_groups WHERE destination=? AND json_extract(body,'$.fields.incident_id')=?`, config.Destination, record.Fields["incident_id"])
				if err != nil {
					return err
				}
			}
			err = queueDiagnostic(tx, config.Destination, id, body, priority, now)
		}
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

func uploadDiagnostics(ctx context.Context, api API, root, clientID string) error {
	// Upload requests must not create more upload diagnostics.
	api.eventsStore = nil
	path := "/api/v1/clients/" + clientID + "/diagnostics/"
	var config diagnosticUploadConfig
	if err := api.getJSON(ctx, path+"config", &config); err != nil {
		return err
	}
	config.Destination = api.server + "|" + clientID
	db, err := diagnosticOutbox(root)
	if err != nil {
		return err
	}
	defer db.Close()
	body, err := json.Marshal(config)
	if err != nil {
		return err
	}
	configPath := filepath.Join(root, "diagnostic-upload", "config.json")
	previous, readErr := os.ReadFile(configPath)
	if readErr != nil || !bytes.Equal(previous, body) {
		if err = os.WriteFile(configPath+".tmp", body, 0600); err != nil {
			return err
		}
		if err = os.Rename(configPath+".tmp", configPath); err != nil {
			return err
		}
	}
	minimum := config.minimum(time.Now())
	if minimum == 0 {
		return nil
	}
	if err = flushDiagnosticGroups(db, config.Destination, time.Now()); err != nil {
		return err
	}
	rows, err := db.QueryContext(ctx, `SELECT body FROM records WHERE destination=? AND priority>=? ORDER BY created LIMIT 100`, config.Destination, minimum)
	if err != nil {
		return err
	}
	records := []uploadedDiagnostic{}
	size := 0
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			rows.Close()
			return err
		}
		if size+len(raw) > 512*1024 {
			break
		}
		var record uploadedDiagnostic
		if err = json.Unmarshal(raw, &record); err != nil {
			rows.Close()
			return err
		}
		records = append(records, record)
		size += len(raw)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	var lost, reported int64
	var epoch string
	err = db.QueryRowContext(ctx, `SELECT count,reported,epoch FROM losses WHERE destination=?`, config.Destination).Scan(&lost, &reported, &epoch)
	if err != nil && err != sql.ErrNoRows {
		return err
	}
	lossID := ""
	if lost > reported && len(records) < 100 {
		lossID = fmt.Sprintf("%s-%d", epoch, lost)
		records = append(records, uploadedDiagnostic{ID: lossID, DiagnosticRecord: DiagnosticRecord{Time: time.Now().Format(time.RFC3339Nano), Level: "ERROR", Module: "diagnostics", Event: "upload_records_dropped", Version: Version, PID: os.Getpid(), Fields: map[string]any{"total_dropped": lost}}})
	}
	if len(records) == 0 {
		return nil
	}
	// Charge transmission attempts as well as successes; a failed request retains its stable IDs.
	rateTx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	errorCount := 0
	for _, record := range records {
		if record.Level == "ERROR" || diagnosticRecovery(record.DiagnosticRecord) {
			errorCount++
		}
	}
	allowed, err := diagnosticAllowance(rateTx, "send:"+config.Destination, errorCount, time.Now())
	if err != nil {
		rateTx.Rollback()
		return err
	}
	if err = rateTx.Commit(); err != nil {
		return err
	}
	filtered := records[:0]
	for _, record := range records {
		if record.Level == "ERROR" || diagnosticRecovery(record.DiagnosticRecord) {
			if allowed == 0 {
				continue
			}
			allowed--
		}
		filtered = append(filtered, record)
	}
	records = filtered
	if len(records) == 0 {
		return nil
	}
	var result struct {
		Acknowledged []string `json:"acknowledged"`
	}
	if err = api.postJSON(ctx, path+"batch", map[string]any{"records": records}, &result); err != nil {
		return err
	}
	sent := map[string]bool{}
	for _, record := range records {
		sent[record.ID] = true
	}
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, id := range result.Acknowledged {
		if !sent[id] {
			continue
		}
		if id == lossID {
			_, err = tx.Exec(`UPDATE losses SET reported=? WHERE destination=?`, lost, config.Destination)
		} else {
			_, err = tx.Exec(`DELETE FROM records WHERE id=? AND destination=?`, id, config.Destination)
		}
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}
