package managedclient

import (
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"
)

const diagnosticErrorRate = 100
const diagnosticGroupLimit = 1000
const diagnosticGroupWindow = 5 * time.Minute

func diagnosticAllowance(tx *sql.Tx, scope string, requested int, now time.Time) (int, error) {
	if requested == 0 {
		return 0, nil
	}
	if _, err := tx.Exec(`INSERT OR IGNORE INTO error_rates VALUES (?, ?, 0)`, scope, now.Unix()); err != nil {
		return 0, err
	}
	var started int64
	var used int
	if err := tx.QueryRow(`SELECT started,used FROM error_rates WHERE scope=?`, scope).Scan(&started, &used); err != nil {
		return 0, err
	}
	if now.Unix()-started >= 60 {
		started = now.Unix()
		used = 0
	}
	allowed := min(requested, max(0, diagnosticErrorRate-used))
	_, err := tx.Exec(`UPDATE error_rates SET started=?,used=? WHERE scope=?`, started, used+allowed, scope)
	return allowed, err
}

func diagnosticLoss(tx *sql.Tx, destination string, count int) error {
	_, err := tx.Exec(`UPDATE losses SET count=count+? WHERE destination=?`, count, destination)
	return err
}

func queueDiagnostic(tx *sql.Tx, destination, id string, body []byte, priority int, now time.Time) error {
	if len(body) > 64*1024 {
		return diagnosticLoss(tx, destination, 1)
	}
	if _, err := tx.Exec(`INSERT INTO records VALUES (?,?,?,?,?)`, id, destination, priority, body, now.UnixNano()); err != nil {
		return err
	}
	var count int
	if err := tx.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&count); err != nil {
		return err
	}
	if count <= diagnosticQueueLimit {
		return nil
	}
	var droppedID, droppedDestination string
	if err := tx.QueryRow(`SELECT id,destination FROM records ORDER BY priority,created LIMIT 1`).Scan(&droppedID, &droppedDestination); err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM records WHERE id=?`, droppedID); err != nil {
		return err
	}
	return diagnosticLoss(tx, droppedDestination, 1)
}

func aggregateDiagnostic(tx *sql.Tx, destination string, body []byte, record DiagnosticRecord, now time.Time) (bool, error) {
	var content any = record.Fields
	if value, ok := record.Fields["error"]; ok {
		content = value
	} else if value, ok := record.Fields["message"]; ok {
		content = value
	}
	identity, err := json.Marshal([]any{record.Module, record.Event, record.Version, record.Fields["incident_id"], content})
	if err != nil {
		return false, err
	}
	fingerprint := fmt.Sprintf("%x", sha256.Sum256(identity))
	result, err := tx.Exec(`UPDATE error_groups SET first_at=CASE WHEN repeats=0 THEN ? ELSE first_at END,repeats=repeats+1,last_at=? WHERE destination=? AND fingerprint=?`, record.Time, record.Time, destination, fingerprint)
	if err != nil {
		return false, err
	}
	if count, _ := result.RowsAffected(); count > 0 {
		return false, nil
	}
	allowed, err := diagnosticAllowance(tx, "capture:"+destination, 1, now)
	if err != nil {
		return false, err
	}
	if allowed == 0 {
		return false, diagnosticLoss(tx, destination, 1)
	}
	var count int
	if err = tx.QueryRow(`SELECT COUNT(*) FROM error_groups`).Scan(&count); err != nil {
		return false, err
	}
	if count >= diagnosticGroupLimit {
		var oldestDestination, oldestFingerprint string
		var repeats int
		if err = tx.QueryRow(`SELECT destination,fingerprint,repeats FROM error_groups ORDER BY due LIMIT 1`).Scan(&oldestDestination, &oldestFingerprint, &repeats); err != nil {
			return false, err
		}
		if _, err = tx.Exec(`DELETE FROM error_groups WHERE destination=? AND fingerprint=?`, oldestDestination, oldestFingerprint); err != nil {
			return false, err
		}
		if repeats > 0 {
			if err = diagnosticLoss(tx, oldestDestination, repeats); err != nil {
				return false, err
			}
		}
	}
	_, err = tx.Exec(`INSERT INTO error_groups VALUES (?,?,?,?,?,0,?)`, destination, fingerprint, body, record.Time, record.Time, now.Add(diagnosticGroupWindow).Unix())
	return true, err
}

func flushDiagnosticGroups(db *sql.DB, destination string, now time.Time) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.Exec(`DELETE FROM error_groups WHERE due<=? AND repeats=0`, now.Unix()); err != nil {
		return err
	}
	rows, err := tx.Query(`SELECT fingerprint,body,first_at,last_at,repeats FROM error_groups WHERE destination=? AND due<=? ORDER BY due LIMIT 100`, destination, now.Unix())
	if err != nil {
		return err
	}
	type group struct {
		fingerprint string
		body        []byte
		first, last string
		repeats     int
	}
	groups := []group{}
	for rows.Next() {
		var g group
		if err = rows.Scan(&g.fingerprint, &g.body, &g.first, &g.last, &g.repeats); err != nil {
			rows.Close()
			return err
		}
		groups = append(groups, g)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, g := range groups {
		var record uploadedDiagnostic
		if err = json.Unmarshal(g.body, &record); err != nil {
			return err
		}
		record.ID, err = diagnosticID()
		if err != nil {
			return err
		}
		record.Time = g.last
		record.Aggregation = &diagnosticAggregation{RepeatedCount: g.repeats, FirstAt: g.first, LastAt: g.last}
		body, err := json.Marshal(record)
		if err != nil {
			return err
		}
		if err = queueDiagnostic(tx, destination, record.ID, body, 40, now); err != nil {
			return err
		}
		if _, err = tx.Exec(`UPDATE error_groups SET repeats=0,due=? WHERE destination=? AND fingerprint=?`, now.Add(diagnosticGroupWindow).Unix(), destination, g.fingerprint); err != nil {
			return err
		}
	}
	return tx.Commit()
}
