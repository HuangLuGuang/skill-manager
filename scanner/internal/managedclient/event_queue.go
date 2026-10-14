package managedclient

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const eventInterval = 300 * time.Millisecond // One start per 300ms; burst one, shared across processes.

func eventID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}
func eventServer(root string) string {
	var c Config
	b, err := os.ReadFile(filepath.Join(root, "config.json"))
	if err == nil {
		_ = json.Unmarshal(b, &c)
	}
	return strings.TrimRight(strings.TrimSpace(c.Server), "/")
}
func eventTx(db *sql.DB) (*sql.Tx, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	_, err = tx.Exec(`UPDATE client_events_queue SET id=id WHERE id=-1`)
	if err != nil {
		tx.Rollback()
		return nil, err
	}
	return tx, nil
}

// Only cumulative, content-bound observations qualify. All remaining details
// participate in identity, so new status, failure, task or evidence stays distinct.
func observationIdentity(e QueuedEvent) string {
	if e.EventType != "skill_governance_recorded" && e.EventType != "skill_governance_detected" {
		return ""
	}
	for _, k := range []string{"path", "signature", "policy_version", "trigger", "action"} {
		v, ok := e.Details[k].(string)
		if !ok || v == "" {
			return ""
		}
	}
	if observationCount(e.Details) == 0 {
		return ""
	}
	d := map[string]any{}
	for k, v := range e.Details {
		switch k {
		case "observation_count", "last_seen_at", "first_seen_at", "first_seen_source":
		default:
			d[k] = v
		}
	}
	b, err := json.Marshal([]any{e.Server, e.ClientID, e.EventType, e.AgentType, e.SkillName, d})
	if err != nil {
		return ""
	}
	return fmt.Sprintf("%x", sha256.Sum256(b))
}
func observationCount(d map[string]any) int64 {
	b, _ := json.Marshal(d["observation_count"])
	var n int64
	_ = json.Unmarshal(b, &n)
	if n < 1 {
		return 0
	}
	return n
}
func normalizeEvent(e *QueuedEvent, epoch string) {
	if e.Details == nil {
		e.Details = map[string]any{}
	}
	if e.CreatedAt == "" {
		e.CreatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	source := "queued_observation"
	if eventTime(e.Details["last_seen_at"]).IsZero() {
		e.Details["last_seen_at"] = e.CreatedAt
		source = "queue_created_at"
	}
	if observationIdentity(*e) == "" {
		return
	}
	e.Details["observation_epoch"] = epoch
	if _, ok := e.Details["first_seen_at"]; !ok {
		e.Details["first_seen_at"] = e.Details["last_seen_at"]
		e.Details["first_seen_source"] = source
	}
}
func queueEpoch(tx *sql.Tx, server string) (string, error) {
	key := "events:epoch:" + server
	_, err := tx.Exec(`INSERT OR IGNORE INTO client_state(key,value,updated_at) VALUES(?,?,?)`, key, eventID(), time.Now().UTC().Format(time.RFC3339Nano))
	if err != nil {
		return "", err
	}
	var epoch string
	err = tx.QueryRow(`SELECT value FROM client_state WHERE key=?`, key).Scan(&epoch)
	return epoch, err
}
func mergeObservation(old, next map[string]any) map[string]any {
	first := old["first_seen_at"]
	source := old["first_seen_source"]
	if eventTime(next["first_seen_at"]).Before(eventTime(first)) {
		first = next["first_seen_at"]
		source = next["first_seen_source"]
	}
	count := observationCount(old)
	if n := observationCount(next); n > count {
		count = n
	}
	result := old
	if eventTime(next["last_seen_at"]).After(eventTime(old["last_seen_at"])) {
		result = next
	}
	result["first_seen_at"], result["first_seen_source"], result["observation_count"] = first, source, count
	return result
}
func eventTime(v any) time.Time {
	s, _ := v.(string)
	t, _ := time.Parse(time.RFC3339Nano, s)
	return t
}
func insertEvent(tx *sql.Tx, e QueuedEvent) error {
	key := observationIdentity(e)
	if key != "" {
		var id int64
		var body string
		err := tx.QueryRow(`SELECT id,details_json FROM client_events_queue WHERE server=? AND aggregate_key=? AND sealed=0`, e.Server, key).Scan(&id, &body)
		if err == nil {
			var old map[string]any
			if err = json.Unmarshal([]byte(body), &old); err != nil {
				return err
			}
			b, _ := json.Marshal(mergeObservation(old, e.Details))
			_, err = tx.Exec(`UPDATE client_events_queue SET details_json=? WHERE id=?`, string(b), id)
			return err
		} else if err != sql.ErrNoRows {
			return err
		}
	}
	b, err := json.Marshal(e.Details)
	if err != nil {
		return err
	}
	if e.DeliveryID == "" {
		e.DeliveryID = eventID()
	}
	_, err = tx.Exec(`INSERT INTO client_events_queue(client_id,event_type,agent_type,skill_name,details_json,created_at,server,aggregate_key,delivery_id) VALUES(?,?,?,?,?,?,?,?,?)`, e.ClientID, e.EventType, e.AgentType, e.SkillName, string(b), e.CreatedAt, e.Server, key, e.DeliveryID)
	return err
}

func (s *Store) initEventQueue() error {
	tx, err := eventTx(s.db)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, col := range []string{"server TEXT NOT NULL DEFAULT ''", "aggregate_key TEXT NOT NULL DEFAULT ''", "delivery_id TEXT NOT NULL DEFAULT ''", "sealed INTEGER NOT NULL DEFAULT 0"} {
		if _, err = tx.Exec(`ALTER TABLE client_events_queue ADD COLUMN ` + col); err != nil && !strings.Contains(strings.ToLower(err.Error()), "duplicate column") {
			return err
		}
	}
	if _, err = tx.Exec(`CREATE UNIQUE INDEX IF NOT EXISTS client_events_pending_identity ON client_events_queue(server,aggregate_key) WHERE sealed=0 AND aggregate_key<>'';
 CREATE INDEX IF NOT EXISTS client_events_server_order ON client_events_queue(server,id);
 CREATE INDEX IF NOT EXISTS client_events_legacy_pending ON client_events_queue(id) WHERE delivery_id='';
 CREATE TABLE IF NOT EXISTS client_event_sender(server TEXT PRIMARY KEY,next_send INTEGER NOT NULL DEFAULT 0,retry_at INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,owner TEXT NOT NULL DEFAULT '',lease_until INTEGER NOT NULL DEFAULT 0,turn INTEGER NOT NULL DEFAULT 0)`); err != nil {
		return err
	}
	// Legacy records have never had a platform field. The active configuration is
	// the available binding evidence; unknown bindings remain held, never guessed.
	server := eventServer(s.root)
	epoch, err := queueEpoch(tx, server)
	if err != nil {
		return err
	}
	for {
		rows, err := tx.Query(`SELECT id,client_id,event_type,COALESCE(agent_type,''),COALESCE(skill_name,''),substr(details_json,1,262145),created_at FROM client_events_queue WHERE delivery_id='' ORDER BY id LIMIT 1`)
		if err != nil {
			return err
		}
		batch := []QueuedEvent{}
		for rows.Next() {
			var e QueuedEvent
			var b string
			if err = rows.Scan(&e.ID, &e.ClientID, &e.EventType, &e.AgentType, &e.SkillName, &b, &e.CreatedAt); err != nil {
				rows.Close()
				return err
			}
			if len(b) > 256*1024 || eventTime(e.CreatedAt).IsZero() || json.Unmarshal([]byte(b), &e.Details) != nil {
				// Preserve unsupported legacy evidence verbatim and keep it held.
				rows.Close()
				if _, err = tx.Exec(`UPDATE client_events_queue SET server=?,delivery_id=?,sealed=-1 WHERE id=?`, server, eventID(), e.ID); err != nil {
					return err
				}
				batch = append(batch, QueuedEvent{ID: -1})
				break
			}
			batch = append(batch, e)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
		if len(batch) == 0 {
			break
		}
		for _, e := range batch {
			if e.ID < 0 {
				continue
			}
			e.Server = server
			normalizeEvent(&e, epoch)
			if _, err = tx.Exec(`DELETE FROM client_events_queue WHERE id=?`, e.ID); err != nil {
				return err
			}
			if err = insertEvent(tx, e); err != nil {
				return err
			}
		}
	}
	return tx.Commit()
}
func (s *Store) QueueEvent(e QueuedEvent) error {
	b, err := json.Marshal(e.Details)
	if err != nil {
		return err
	}
	if len(b) > 256*1024 {
		return fmt.Errorf("client_events_details_too_large")
	}
	// Copy details so aggregation never mutates a caller-owned observation.
	if err := json.Unmarshal(b, &e.Details); err != nil {
		return err
	}
	tx, err := eventTx(s.db)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	epoch, err := queueEpoch(tx, e.Server)
	if err != nil {
		return err
	}
	normalizeEvent(&e, epoch)
	if err = insertEvent(tx, e); err != nil {
		return err
	}
	return tx.Commit()
}
func scanQueued(rows *sql.Rows) ([]QueuedEvent, error) {
	defer rows.Close()
	out := []QueuedEvent{}
	for rows.Next() {
		var e QueuedEvent
		var b string
		if err := rows.Scan(&e.ID, &e.ClientID, &e.EventType, &e.AgentType, &e.SkillName, &b, &e.CreatedAt, &e.Server, &e.DeliveryID); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(b), &e.Details); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

const queuedColumns = `id,client_id,event_type,COALESCE(agent_type,''),COALESCE(skill_name,''),details_json,created_at,server,delivery_id`

func (s *Store) QueuedEvents() ([]QueuedEvent, error) {
	rows, err := s.db.Query(`SELECT ` + queuedColumns + ` FROM client_events_queue ORDER BY id LIMIT 500`)
	if err != nil {
		return nil, err
	}
	return scanQueued(rows)
}
func (s *Store) DeleteQueuedEvent(id int64) error {
	_, err := s.db.Exec(`DELETE FROM client_events_queue WHERE id=?`, id)
	return err
}

func flushEventsLimit(ctx context.Context, api API, s *Store, limit int) (resultErr error) {
	confirmed := 0
	defer func() {
		if resultErr != nil && !errors.Is(resultErr, errEventDeferred) {
			syncError(s, "events", resultErr)
		} else if confirmed > 0 {
			syncError(s, "events", nil)
		}
	}()
	parent := ctx
	ctx, cancel := context.WithTimeout(ctx, 6*time.Second)
	defer cancel()
	api.eventsStore = s
	if cachedPolicy(s).OrdinaryEventsProtocol < 1 {
		return fmt.Errorf("client_events_server_upgrade_required")
	}
	server := api.server
	owner := eventID()
	now := time.Now().UnixMilli()
	_, err := s.db.Exec(`INSERT OR IGNORE INTO client_event_sender(server) VALUES(?)`, server)
	if err != nil {
		return err
	}
	r, err := s.db.Exec(`UPDATE client_event_sender SET owner=?,lease_until=? WHERE server=? AND lease_until<=? AND retry_at<=?`, owner, now+30000, server, now, now)
	if err != nil {
		return err
	}
	n, _ := r.RowsAffected()
	if n == 0 {
		return nil
	}
	defer s.db.Exec(`UPDATE client_event_sender SET owner='',lease_until=0 WHERE server=? AND owner=?`, server, owner)
	for i := 0; i < limit; i++ {
		if ctx.Err() != nil {
			if parent.Err() == nil {
				return nil
			}
			return parent.Err()
		}
		tx, err := eventTx(s.db)
		if err != nil {
			return err
		}
		r, err = tx.Exec(`UPDATE client_event_sender SET lease_until=?,turn=turn+1 WHERE server=? AND owner=?`, time.Now().UnixMilli()+30000, server, owner)
		if err != nil {
			tx.Rollback()
			return err
		}
		n, _ = r.RowsAffected()
		if n == 0 {
			tx.Rollback()
			return nil
		}
		var turn int
		if err = tx.QueryRow(`SELECT turn FROM client_event_sender WHERE server=?`, server).Scan(&turn); err != nil {
			tx.Rollback()
			return err
		}
		// Alternate oldest evidence and FIFO arrivals in the last 30 seconds.
		extra := ""
		if turn%2 == 1 {
			extra = ` AND created_at>=?`
		}
		args := []any{server}
		if extra != "" {
			args = append(args, time.Now().UTC().Add(-30*time.Second).Format(time.RFC3339Nano))
		}
		rows, err := tx.Query(`SELECT `+queuedColumns+` FROM client_events_queue WHERE server=? AND sealed>=0`+extra+` ORDER BY id LIMIT 1`, args...)
		if err != nil {
			tx.Rollback()
			return err
		}
		items, err := scanQueued(rows)
		if err != nil {
			tx.Rollback()
			return err
		}
		if len(items) == 0 && extra != "" {
			rows, err = tx.Query(`SELECT `+queuedColumns+` FROM client_events_queue WHERE server=? AND sealed>=0 ORDER BY id LIMIT 1`, server)
			if err == nil {
				items, err = scanQueued(rows)
			}
		}
		if err != nil {
			tx.Rollback()
			return err
		}
		if len(items) == 0 {
			tx.Rollback()
			return nil
		}
		e := items[0]
		_, err = tx.Exec(`UPDATE client_events_queue SET sealed=1 WHERE id=?`, e.ID)
		if err != nil {
			tx.Rollback()
			return err
		}
		if err = tx.Commit(); err != nil {
			return err
		}
		if err = api.sendOrdinaryEvent(ctx, e); err != nil {
			var waiting eventWaitError
			if errors.As(err, &waiting) && errors.Is(err, context.DeadlineExceeded) && parent.Err() == nil {
				return nil
			}
			return err
		}
		// New observations use a separate unsealed row; only this immutable delivery
		// is removed. A crash here replays the same id after lease expiry.
		if _, err = s.db.Exec(`DELETE FROM client_events_queue WHERE id=? AND delivery_id=? AND sealed=1`, e.ID, e.DeliveryID); err != nil {
			return err
		}
		confirmed++
	}
	return nil
}
