package localstore

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"skill-manager/scanner/internal/aidr/agentlog"
	"time"
)

type Record struct {
	Sequence int64           `json:"sequence,string"`
	Kind     string          `json:"kind"`
	ID       string          `json:"record_id"`
	Payload  json.RawMessage `json:"payload"`
}
type Envelope struct {
	SchemaVersion int      `json:"schema_version"`
	Records       []Record `json:"records"`
}
type UploadBatch struct {
	ID      string          `json:"batch_id"`
	Digest  string          `json:"digest"`
	Payload json.RawMessage `json:"payload"`
}

// Prepare returns exactly the same durable payload until acknowledged. This is
// a local transport-neutral contract, not authorization to send it anywhere.
func (s *Store) Prepare(ctx context.Context, maxRecords, maxBytes int) (*UploadBatch, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if maxRecords < 1 || maxRecords > 500 || maxBytes < 1024 || maxBytes > 1<<20 {
		return nil, ErrInvalid
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	var b UploadBatch
	err = tx.QueryRow(`SELECT id,digest,payload FROM active_batch WHERE singleton=1`).Scan(&b.ID, &b.Digest, &b.Payload)
	if err == nil {
		var frozen Envelope
		if json.Unmarshal(b.Payload, &frozen) != nil {
			return nil, errors.New("aidr_store_corrupt")
		}
		if len(b.Payload) > maxBytes || len(frozen.Records) > maxRecords {
			return nil, errors.New("aidr_store_batch_limit")
		}
		return &b, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	rows, err := tx.Query(`SELECT seq,kind,record_id,payload FROM outbox ORDER BY seq LIMIT ?`, maxRecords)
	if err != nil {
		return nil, err
	}
	e := Envelope{SchemaVersion: 1, Records: []Record{}}
	empty, _ := json.Marshal(e)
	encodedBytes := len(empty)
	var through int64
	for rows.Next() {
		var r Record
		var raw string
		if err = rows.Scan(&r.Sequence, &r.Kind, &r.ID, &raw); err != nil {
			rows.Close()
			return nil, err
		}
		r.Payload = json.RawMessage(raw)
		encoded, err := json.Marshal(r)
		if err != nil {
			rows.Close()
			return nil, err
		}
		nextBytes := encodedBytes + len(encoded)
		if len(e.Records) > 0 {
			nextBytes++
		}
		if nextBytes > maxBytes {
			break
		}
		e.Records = append(e.Records, r)
		encodedBytes = nextBytes
		through = r.Sequence
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if len(e.Records) == 0 {
		var n int
		if err = tx.QueryRow(`SELECT count(*) FROM outbox`).Scan(&n); err != nil {
			return nil, err
		}
		if n > 0 {
			return nil, errors.New("aidr_store_batch_limit")
		}
		return nil, nil
	}
	b.Payload, err = json.Marshal(e)
	if err != nil {
		return nil, err
	}
	b.Digest = hash(b.Payload)
	b.ID = b.Digest
	if _, err = tx.Exec(`INSERT INTO active_batch(singleton,id,digest,payload,through_seq) VALUES(1,?,?,?,?)`, b.ID, b.Digest, []byte(b.Payload), through); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &b, nil
}

// Acknowledge must only be called after the future uploader validates an
// authenticated durable server receipt. No network behavior exists here.
func (s *Store) Acknowledge(ctx context.Context, id, digest string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var existingID, existingDigest string
	var through int64
	err = tx.QueryRow(`SELECT id,digest,through_seq FROM active_batch WHERE singleton=1`).Scan(&existingID, &existingDigest, &through)
	if errors.Is(err, sql.ErrNoRows) || (err == nil && existingID != id) {
		var previous string
		if e := tx.QueryRow(`SELECT value FROM metadata WHERE key='last_ack_id'`).Scan(&previous); e == nil && previous == id && id == digest {
			return nil
		}
		return ErrBatchConflict
	}
	if err != nil {
		return err
	}
	if existingID != id || existingDigest != digest {
		return ErrBatchConflict
	}
	now := time.Now().UnixNano()
	if _, err = tx.Exec(`UPDATE logical_events SET acked_ns=? WHERE id IN (SELECT record_id FROM outbox WHERE seq<=? AND kind='event')`, now, through); err != nil {
		return err
	}
	if _, err = tx.Exec(`UPDATE coverage_history SET acked_ns=? WHERE id IN (SELECT record_id FROM outbox WHERE seq<=? AND kind='coverage')`, now, through); err != nil {
		return err
	}
	if _, err = tx.Exec(`DELETE FROM outbox WHERE seq<=?`, through); err != nil {
		return err
	}
	if _, err = tx.Exec(`DELETE FROM active_batch WHERE singleton=1`); err != nil {
		return err
	}
	for key, value := range map[string]any{"last_ack_id": id, "last_ack_seq": through, "last_ack_at": time.Unix(0, now).UTC().Format(time.RFC3339Nano)} {
		if _, err = tx.Exec(`INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, key, value); err != nil {
			return err
		}
	}
	return tx.Commit()
}

type Status struct {
	RuntimeCollectionEnabled *bool  `json:"runtime_collection_enabled,omitempty"`
	RuntimePolicyVersion     string `json:"runtime_policy_version,omitempty"`
	Sources                  int    `json:"sources"`
	LogicalEvents            int    `json:"logical_events"`
	Evidence                 int    `json:"evidence"`
	CoverageRecords          int    `json:"coverage_records"`
	Queued                   int    `json:"queued_records"`
	RetainedPayloads         int    `json:"retained_event_payloads"`
	EvictedPayloads          int    `json:"evicted_event_payloads"`
	AcknowledgedSequence     string `json:"acknowledged_sequence"`
	LastAcknowledgedAt       string `json:"last_ack_at,omitempty"`
	RecoveryCode             string `json:"recovery_code,omitempty"`
	CapacityCode             string `json:"capacity_code,omitempty"`
	IntakeCode               string `json:"intake_code,omitempty"`
	UploadCode               string `json:"upload_code,omitempty"`
	RetiredThrough           string `json:"retired_through,omitempty"`
	CapacityWarning          string `json:"capacity_warning,omitempty"`
	DatabaseBytes            int64  `json:"database_bytes"`
}

func (s *Store) Status(ctx context.Context) (Status, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var v Status
	err := s.db.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM sources),(SELECT count(*) FROM logical_events),(SELECT count(*) FROM evidence),(SELECT count(*) FROM outbox),(SELECT count(*) FROM logical_events WHERE payload IS NOT NULL),(SELECT count(*) FROM logical_events WHERE payload IS NULL)`).Scan(&v.Sources, &v.LogicalEvents, &v.Evidence, &v.Queued, &v.RetainedPayloads, &v.EvictedPayloads)
	if err != nil {
		return v, err
	}
	if err = s.db.QueryRow(`SELECT count(*) FROM coverage_history`).Scan(&v.CoverageRecords); err != nil {
		return v, err
	}
	v.AcknowledgedSequence = "0"
	for key, dst := range map[string]*string{"retired_through": &v.RetiredThrough, "runtime_policy_version": &v.RuntimePolicyVersion, "last_ack_seq": &v.AcknowledgedSequence, "last_ack_at": &v.LastAcknowledgedAt, "recovery_code": &v.RecoveryCode, "intake_code": &v.IntakeCode, "upload_code": &v.UploadCode} {
		err = s.db.QueryRow(`SELECT value FROM metadata WHERE key=?`, key).Scan(dst)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return v, err
		}
	}
	var runtimeEnabled string
	err = s.db.QueryRow(`SELECT value FROM metadata WHERE key='runtime_collection_enabled'`).Scan(&runtimeEnabled)
	if err == nil {
		if runtimeEnabled != "true" && runtimeEnabled != "false" {
			return v, ErrInvalid
		}
		enabled := runtimeEnabled == "true"
		v.RuntimeCollectionEnabled = &enabled
	} else if !errors.Is(err, sql.ErrNoRows) {
		return v, err
	}
	var pages, size int64
	if err = s.db.QueryRow(`PRAGMA page_count`).Scan(&pages); err != nil {
		return v, err
	}
	if err = s.db.QueryRow(`PRAGMA page_size`).Scan(&size); err != nil {
		return v, err
	}
	v.DatabaseBytes = pages * size
	if v.LogicalEvents >= s.limits.LogicalEvents || v.Evidence >= s.limits.Evidence || v.CoverageRecords >= s.limits.Evidence || v.Sources >= s.limits.Sources || v.Queued >= s.limits.Evidence+s.limits.Sources || v.DatabaseBytes >= s.limits.DatabaseBytes {
		v.CapacityCode = "aidr_store_capacity"
	}
	if v.LogicalEvents*5 >= s.limits.LogicalEvents*4 || v.Evidence*5 >= s.limits.Evidence*4 || v.Sources*5 >= s.limits.Sources*4 || v.DatabaseBytes*5 >= s.limits.DatabaseBytes*4 {
		v.CapacityWarning = "aidr_store_capacity_warning"
	}
	return v, nil
}

// Prune retires acknowledged identities behind a durable observation watermark.
// The platform remains the authority for identities outside this local window.
func (s *Store) Prune(ctx context.Context, now time.Time) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	retention := s.limits.Retention
	if s.policy != nil && s.policy.Lifecycle != nil {
		retention = time.Duration(s.policy.Lifecycle.RetentionDays) * 24 * time.Hour
	}
	cutoff := now.Add(-retention).UnixNano()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	// Payload-free legacy tombstones have no retained event time. Their conservative
	// admission boundary is the retention cutoff; the server preserves their hash.
	var boundary time.Time
	var ids []string
	rows, err := tx.QueryContext(ctx, `SELECT id,payload FROM logical_events WHERE acked_ns IS NOT NULL AND acked_ns<?`, cutoff)
	if err != nil {
		return 0, err
	}
	for rows.Next() {
		var id string
		var raw sql.NullString
		if err = rows.Scan(&id, &raw); err != nil {
			rows.Close()
			return 0, err
		}
		at := time.Unix(0, cutoff).UTC()
		if raw.Valid {
			var e agentlog.Event
			if json.Unmarshal([]byte(raw.String), &e) != nil {
				rows.Close()
				return 0, ErrInvalid
			}
			at = e.ObservedAt
		}
		// Retirement cannot exclude observations inside the current window.
		if at.After(time.Unix(0, cutoff)) {
			at = time.Unix(0, cutoff).UTC()
		}
		ids = append(ids, id)
		if at.After(boundary) {
			boundary = at
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return 0, err
	}
	old, err := retiredThrough(tx)
	if err != nil {
		return 0, err
	}
	if boundary.After(old) {
		if _, err = tx.Exec(`INSERT INTO metadata(key,value) VALUES('retired_through',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, boundary.UTC().Format(time.RFC3339Nano)); err != nil {
			return 0, err
		}
	}
	for _, id := range ids {
		if _, err = tx.Exec(`DELETE FROM evidence WHERE logical_id=?`, id); err != nil {
			return 0, err
		}
		if _, err = tx.Exec(`DELETE FROM logical_events WHERE id=?`, id); err != nil {
			return 0, err
		}
	}
	if _, err = tx.Exec(`DELETE FROM coverage_history WHERE acked_ns IS NOT NULL AND acked_ns<?`, cutoff); err != nil {
		return 0, err
	}
	// Idle sources can be rediscovered. Global revisions survive their removal so
	// coverage IDs remain unique within the existing upload stream.
	if _, err = tx.Exec(`INSERT INTO metadata(key,value) VALUES('source_revision',coalesce((SELECT max(revision) FROM sources),0)) ON CONFLICT(key) DO UPDATE SET value=max(CAST(value AS INTEGER),CAST(excluded.value AS INTEGER))`); err != nil {
		return 0, err
	}
	if _, err = tx.Exec(`DELETE FROM sources WHERE NOT EXISTS(SELECT 1 FROM coverage_history WHERE source_id=sources.id) AND NOT EXISTS(SELECT 1 FROM logical_events WHERE json_extract(payload,'$.source_id')=sources.id)`); err != nil {
		return 0, err
	}
	if _, err = tx.Exec(`DELETE FROM discovery_files WHERE reason='aidr_log_source_missing' AND NOT EXISTS(SELECT 1 FROM sources WHERE sources.id=discovery_files.id)`); err != nil {
		return 0, err
	}
	if _, err = tx.Exec(`DELETE FROM discovery_dirs AS retired WHERE reason='aidr_log_source_missing' AND EXISTS(SELECT 1 FROM discovery_dirs AS parent WHERE parent.root_key=retired.root_key AND length(parent.path)<length(retired.path) AND substr(retired.path,1,length(parent.path)+1)=parent.path||'/')`); err != nil {
		return 0, err
	}
	if err = tx.Commit(); err != nil {
		return 0, err
	}
	// Reuse free SQLite pages, and release WAL growth after retirement.
	if len(ids) > 0 {
		if _, err = s.db.Exec(`PRAGMA incremental_vacuum(1024); PRAGMA wal_checkpoint(TRUNCATE)`); err != nil {
			return int64(len(ids)), err
		}
	}
	return int64(len(ids)), nil
}

type EventPage struct {
	Events []json.RawMessage `json:"events"`
	Next   string            `json:"next_after"`
}

func (s *Store) Events(ctx context.Context, after string, limit int) (EventPage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p := EventPage{Events: []json.RawMessage{}}
	if limit < 1 || limit > 500 {
		return p, ErrInvalid
	}
	rows, err := s.db.QueryContext(ctx, `SELECT id,payload FROM logical_events WHERE id>? AND payload IS NOT NULL ORDER BY id LIMIT ?`, after, limit)
	if err != nil {
		return p, err
	}
	defer rows.Close()
	for rows.Next() {
		var raw string
		if err = rows.Scan(&p.Next, &raw); err != nil {
			return p, err
		}
		p.Events = append(p.Events, json.RawMessage(raw))
	}
	return p, rows.Err()
}
