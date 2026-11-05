package hooks

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/localstore"
	"skill-manager/scanner/internal/aidr/privatefs"
	"strconv"
	"strings"
	"time"
)

type runtimeCollection struct {
	Enabled bool   `json:"enabled"`
	Version string `json:"policy_version"`
}

// The intake gate is independent of audit scope, control policy and upload.
// Its transaction never changes events, receipts or a frozen batch.
func (s *Store) SetRuntimeCollection(ctx context.Context, enabled bool, version string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.runtimeCollection != nil && s.runtimeCollection.Enabled == enabled && s.runtimeCollection.Version == version {
		return nil
	}
	if !validCollectionVersion(version) {
		return code("aidr_hook_runtime_target_invalid")
	}
	raw, _ := json.Marshal(runtimeCollection{enabled, version})
	if _, err := s.db.ExecContext(ctx, `INSERT INTO hook_meta(key,value) VALUES('runtime_collection',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, string(raw)); err != nil {
		return err
	}
	s.runtimeCollection = &runtimeCollection{enabled, version}
	return nil
}

// PendingUploads reads counts only, without acquiring the single-writer lock,
// creating files or opening event payloads. The receiver still verifies the
// immutable platform/device binding when it acquires the store.
func PendingUploads(ctx context.Context, directory string) (int, error) {
	info, err := os.Lstat(directory)
	if os.IsNotExist(err) {
		return 0, nil
	}
	real, resolved := filepath.EvalSymlinks(directory)
	if err != nil || resolved != nil || real != directory || !info.IsDir() || privatefs.Check(directory) != nil {
		return 0, code("aidr_hook_store_invalid")
	}
	path := filepath.Join(directory, "hooks.db")
	info, err = os.Lstat(path)
	if os.IsNotExist(err) {
		return 0, nil
	}
	if err != nil || !info.Mode().IsRegular() || privatefs.Check(path) != nil {
		return 0, code("aidr_hook_store_invalid")
	}
	q := url.Values{"mode": {"ro"}, "_pragma": {"busy_timeout(1000)"}}
	db, err := sql.Open("sqlite", localstore.SQLiteURI(path, q.Encode()))
	if err != nil {
		return 0, code("aidr_hook_storage_failed")
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	bounded, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	var pending int
	err = db.QueryRowContext(bounded, `SELECT (SELECT count(*) FROM hook_events)+(SELECT count(*) FROM hook_attempt_reports WHERE acked=0)+(SELECT count(*) FROM hook_attempts WHERE state='pending')`).Scan(&pending)
	if err != nil {
		return 0, code("aidr_hook_storage_failed")
	}
	return pending, nil
}

func (s *Store) loadRuntimeCollection(ctx context.Context) error {
	var raw string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM hook_meta WHERE key='runtime_collection'`).Scan(&raw)
	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}
	var gate runtimeCollection
	if err != nil || json.Unmarshal([]byte(raw), &gate) != nil || !validCollectionVersion(gate.Version) {
		return code("aidr_hook_runtime_target_invalid")
	}
	s.runtimeCollection = &gate
	return nil
}

func validCollectionVersion(version string) bool {
	if version == "" {
		return true
	} // Existing local-only receivers have no platform revision.
	if len(version) > 40 {
		return false
	}
	parts := strings.Split(version, ":")
	if len(parts) > 2 {
		return false
	}
	for _, part := range parts {
		if part == "" {
			return false
		}
		for _, c := range part {
			if c < '0' || c > '9' {
				return false
			}
		}
		if _, err := strconv.ParseUint(part, 10, 64); err != nil {
			return false
		}
	}
	return true
}
