package managedclient

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	scannerclient "skill-manager/scanner/internal/client"
)

// Snapshot submitted tasks separately from the lifetime of their local copies.
func (store *Store) initScanHistory() error {
	var installed int
	if err := store.db.QueryRow(`SELECT count(*) FROM sqlite_master WHERE (type='table' AND name='client_scan_history') OR (type='trigger' AND name IN ('scan_history_after_insert','scan_history_after_update'))`).Scan(&installed); err != nil {
		return err
	}
	if installed == 3 {
		return nil
	}
	columns := []string{"id", "agent_type", "skill_name", "original_path", "pending_path", "reason", "status", "skill_id", "version_id", "content_fingerprint", "created_at", "submitted_at", "progress_json"}
	pairs := []string{}
	for _, column := range columns {
		if column == "progress_json" {
			pairs = append(pairs, "'progress',json(progress_json)")
		} else {
			pairs = append(pairs, fmt.Sprintf("'%s',%s", column, column))
		}
	}
	snapshot := `INSERT INTO client_scan_history(history_id, item_json) SELECT id || ':' || COALESCE(NULLIF(version_id,''),skill_id) || ':' || COALESCE(submitted_at,''), json_object(` + strings.Join(pairs, ",") + `) FROM client_pending WHERE COALESCE(skill_id,'') <> '' ON CONFLICT(history_id) DO UPDATE SET item_json=excluded.item_json;`
	ctx := context.Background()
	tx, err := store.db.Conn(ctx)
	if err != nil {
		return err
	}
	defer tx.Close()
	if _, err = tx.ExecContext(ctx, `BEGIN IMMEDIATE`); err != nil {
		return err
	}
	defer tx.ExecContext(ctx, `ROLLBACK`)
	if _, err = tx.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS client_scan_history(history_id TEXT PRIMARY KEY, item_json TEXT NOT NULL);`); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, snapshot); err != nil {
		return err
	}
	for _, event := range []string{"INSERT", "UPDATE"} {
		// Capture before the source can be cleaned up, reset or re-submitted.
		if _, err = tx.ExecContext(ctx, `CREATE TRIGGER IF NOT EXISTS scan_history_after_`+strings.ToLower(event)+` AFTER `+event+` ON client_pending BEGIN `+strings.Replace(snapshot, " WHERE COALESCE", " WHERE id=NEW.id AND COALESCE", 1)+` END;`); err != nil {
			return err
		}
	}
	_, err = tx.ExecContext(ctx, `COMMIT`)
	return err
}

func (store *Store) ScanHistory() ([]PendingItem, error) {
	rows, err := store.db.Query(`SELECT history_id,item_json FROM client_scan_history ORDER BY json_extract(item_json,'$.submitted_at') DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []PendingItem{}
	for rows.Next() {
		var id, body string
		var item PendingItem
		if err = rows.Scan(&id, &body); err != nil {
			return nil, err
		}
		if err = json.Unmarshal([]byte(body), &item); err != nil {
			return nil, err
		}
		item.ID = id
		items = append(items, item)
	}
	return items, rows.Err()
}

func RefreshScanHistory(ctx context.Context, server, token string, store *Store) ([]PendingItem, error) {
	items, err := store.ScanHistory()
	if err != nil {
		return nil, err
	}
	api := scannerclient.New(server, token, 30*time.Second)
	for i := range items {
		item := &items[i]
		if pendingStatusTerminal(item.Status) || item.Status == "unavailable" {
			continue
		}
		version := item.VersionID
		if version == "" {
			version = item.SkillID
		}
		result, err := api.GetImport(ctx, version)
		if err != nil {
			if scannerclient.IsNotFound(err) || scannerclient.IsSubmissionNotOwned(err) {
				item.Status = "unavailable"
			} else {
				return nil, err
			}
		} else {
			item.Status = result.Status
			item.Progress = ScanProgress{}
			if result.Status == "PENDING" {
				item.Progress = ScanProgress{Stage: result.ScanProgressStage, Analyzers: result.ScanProgressAnalyzers, VersionID: version, UpdatedAt: time.Now().UTC().Format(time.RFC3339Nano)}
			}
		}
		body, err := json.Marshal(item)
		if err != nil {
			return nil, err
		}
		if _, err = store.db.Exec(`UPDATE client_scan_history SET item_json=? WHERE history_id=?`, string(body), item.ID); err != nil {
			return nil, err
		}
	}
	return items, nil
}
