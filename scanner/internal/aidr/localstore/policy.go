package localstore

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"skill-manager/scanner/internal/aidr/agentlog"
	"time"
)

// Policy cache shares the outbox's platform and device binding.
func (s *Store) LoadPolicy(ctx context.Context) error {
	var raw string
	p := agentlog.DefaultAuditPolicy()
	err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='audit_policy'`).Scan(&raw)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if err == nil && (json.Unmarshal([]byte(raw), &p) != nil || !p.Valid()) {
		return ErrInvalid
	}
	var resumeRaw string
	err = s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='audit_collection_resume_at'`).Scan(&resumeRaw)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	var resume time.Time
	if err == nil {
		resume, err = time.Parse(time.RFC3339Nano, resumeRaw)
		if err != nil {
			return ErrInvalid
		}
	}
	s.collectionResumeAt = resume
	s.policy = &p
	return nil
}
func (s *Store) Policy() *agentlog.AuditPolicy { return s.policy }

// Configure before starting intake; source paths remain unchanged in events.
func (s *Store) SetSkillPathResolver(resolve func(string) (string, error)) {
	s.skillObserver.ResolvePath = resolve
}
func (s *Store) SavePolicy(ctx context.Context, p agentlog.AuditPolicy) error {
	if !p.Valid() {
		return ErrInvalid
	}
	n, err := s.LastSequence(ctx)
	if err != nil {
		return err
	}
	if s.policy != nil && s.policy.Receipt == p.Receipt {
		if p.Equal(*s.policy) {
			return nil
		}
		// Metadata protocol negotiation does not change the receipt's capture scope.
		previous := *s.policy
		previous.ModelContextSchema = p.ModelContextSchema
		previous.CompletionSchema = p.CompletionSchema
		previous.MessageLinkSchema = p.MessageLinkSchema
		if !p.Equal(previous) {
			return ErrInvalid
		}
	}
	raw, _ := json.Marshal(p)
	resume := s.collectionResumeAt
	if s.policy != nil && !s.policy.CollectionEnabled() && p.CollectionEnabled() {
		resume = time.Now().UTC()
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	_, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('audit_policy',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, string(raw))
	if err == nil {
		_, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('audit_policy_after',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, n)
	}
	if err == nil {
		if !resume.IsZero() {
			_, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('audit_collection_resume_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, resume.Format(time.RFC3339Nano))
		}
	}
	if err == nil {
		if p.CompletionSchema > 0 && (s.policy == nil || s.policy.CompletionSchema < p.CompletionSchema) {
			_, err = tx.ExecContext(ctx, `UPDATE discovery_files SET pending=1 WHERE agent='codex'`)
		}
	}
	if err == nil {
		if p.MessageLinkSchema > 0 && (s.policy == nil || s.policy.MessageLinkSchema < p.MessageLinkSchema) {
			_, err = tx.ExecContext(ctx, `UPDATE discovery_files SET pending=1 WHERE agent='doubaowork'`)
		}
	}
	if err == nil {
		err = tx.Commit()
	}
	if err == nil {
		s.policy = &p
		s.collectionResumeAt = resume
	}
	return err
}
func (s *Store) LastSequence(ctx context.Context) (int64, error) {
	var n int64
	err := s.db.QueryRowContext(ctx, `SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='outbox'),0)`).Scan(&n)
	return n, err
}

// Replays keep the original projection while retaining new physical evidence.
// Evicted payloads stay evicted; a tombstone never authorizes restoring raw history.
func (s *Store) preserveProjection(ctx context.Context, events []agentlog.Event) ([]agentlog.Event, error) {
	out := events[:0]
	for _, e := range events {
		evicted := false
		for _, id := range append([]string{e.LogicalEventID}, e.PreviousLogicalIDs...) {
			var payload sql.NullString
			err := s.db.QueryRowContext(ctx, `SELECT payload FROM logical_events WHERE id=?`, id).Scan(&payload)
			if errors.Is(err, sql.ErrNoRows) {
				continue
			}
			if err != nil {
				return nil, err
			}
			if !payload.Valid {
				evicted = true
				break
			}
			var original agentlog.Event
			if json.Unmarshal([]byte(payload.String), &original) != nil {
				return nil, ErrInvalid
			}
			e.LogicalEventID = original.LogicalEventID
			e.Behavior = original.Behavior
			e.Message = original.Message
			e.SchemaVersion = original.SchemaVersion
			break
		}
		if !evicted {
			out = append(out, e)
		}
	}
	return out, nil
}

func (s *Store) PolicyAppliedAfter(ctx context.Context) (string, error) {
	var value string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='audit_policy_after'`).Scan(&value)
	if errors.Is(err, sql.ErrNoRows) {
		return "0", nil
	}
	return value, err
}

// IntakeSince survives ACKs and restarts; retention supplies the advancing floor.
func (s *Store) IntakeSince(ctx context.Context, proposed time.Time) (time.Time, error) {
	if proposed.IsZero() {
		return time.Time{}, ErrInvalid
	}
	if _, err := s.db.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('intake_since',?) ON CONFLICT(key) DO NOTHING`, proposed.UTC().Format(time.RFC3339Nano)); err != nil {
		return time.Time{}, err
	}
	var raw string
	if err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='intake_since'`).Scan(&raw); err != nil {
		return time.Time{}, err
	}
	since, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		return time.Time{}, ErrInvalid
	}
	if proposed.Before(since) {
		if _, err := s.db.ExecContext(ctx, `UPDATE metadata SET value=? WHERE key='intake_since'`, proposed.UTC().Format(time.RFC3339Nano)); err != nil {
			return time.Time{}, err
		}
		since = proposed
	}
	return since, nil
}
