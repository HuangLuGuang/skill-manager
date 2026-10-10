package localstore

import (
	"context"
	"database/sql"
	"errors"
	"strconv"
	"time"
)

// SetRuntimeCollection persists only the scheduling boundary. Audit scope and
// redaction remain the independently authenticated policy. Frozen bytes, source
// cursors and previous events are not changed by a runtime switch.
func (s *Store) SetRuntimeCollection(ctx context.Context, enabled bool) error {
	return s.SetRuntimeTarget(ctx, enabled, "")
}

// The applied version is recorded in the same transaction as the intake gate.
func (s *Store) SetRuntimeTarget(ctx context.Context, enabled bool, version string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	var previous, resumeText string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='runtime_collection_enabled'`).Scan(&previous)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if err == nil && previous != "true" && previous != "false" {
		return ErrInvalid
	}
	err = s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='runtime_collection_resume_at'`).Scan(&resumeText)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	var resume time.Time
	if err == nil {
		resume, err = time.Parse(time.RFC3339Nano, resumeText)
		if err != nil {
			return ErrInvalid
		}
	}
	var previousVersion string
	err = s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='runtime_policy_version'`).Scan(&previousVersion)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if previous == strconv.FormatBool(enabled) && previousVersion == version {
		s.runtimeResumeAt = resume
		return nil
	}
	if previous == "false" && enabled {
		resume = time.Now().UTC()
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('runtime_collection_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, strconv.FormatBool(enabled)); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('runtime_policy_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, version); err != nil {
		return err
	}
	if !resume.IsZero() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('runtime_collection_resume_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, resume.Format(time.RFC3339Nano)); err != nil {
			return err
		}
	}
	if err = tx.Commit(); err == nil {
		s.runtimeResumeAt = resume
	}
	return err
}
