package enforcement

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"sync"

	"skill-manager/scanner/internal/aidr/localstore"
)

// The shared directory guard provides single-writer locking and immutable
// platform/device binding. Runtime records use their own additive SQLite file.
type Store struct {
	Guard    *localstore.Store
	db       *sql.DB
	mu       sync.Mutex
	capacity int
}
type Batch struct {
	Through int64
	Count   int
	Payload []byte
	Digest  string
}

func OpenStore(directory string, capacity int) (*Store, error) {
	if capacity < 1 || capacity > 100000 {
		return nil, errors.New("aidr_enforcement_capacity_invalid")
	}
	guard, err := localstore.Open(directory, localstore.DefaultLimits())
	if err != nil {
		return nil, err
	}
	fail := func(e error) (*Store, error) { guard.Close(); return nil, e }
	for _, name := range []string{"runtime.db", "runtime.db-wal", "runtime.db-shm"} {
		if info, e := os.Lstat(filepath.Join(directory, name)); e == nil {
			if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
				return fail(errors.New("aidr_enforcement_store_invalid"))
			}
		} else if !os.IsNotExist(e) {
			return fail(e)
		}
	}
	file := filepath.Join(directory, "runtime.db")
	f, err := os.OpenFile(file, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return fail(err)
	}
	f.Close()
	db, err := sql.Open("sqlite", (&url.URL{Scheme: "file", Path: file}).String())
	if err != nil {
		return fail(err)
	}
	db.SetMaxOpenConns(1)
	_, err = db.Exec(`PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA wal_autocheckpoint=256; PRAGMA journal_size_limit=1048576; PRAGMA max_page_count=65536;
CREATE TABLE IF NOT EXISTS runtime_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,monitor TEXT NOT NULL,sequence TEXT NOT NULL,payload BLOB NOT NULL,UNIQUE(monitor,sequence));
CREATE TABLE IF NOT EXISTS runtime_frozen(singleton INTEGER PRIMARY KEY CHECK(singleton=1),through_id INTEGER NOT NULL,count INTEGER NOT NULL,payload BLOB NOT NULL,digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runtime_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO runtime_meta VALUES('schema','1');`)
	if err != nil {
		db.Close()
		return fail(err)
	}
	var schema string
	err = db.QueryRow(`SELECT value FROM runtime_meta WHERE key='schema'`).Scan(&schema)
	if err != nil || schema != "1" {
		db.Close()
		return fail(errors.New("aidr_enforcement_store_version"))
	}
	return &Store{Guard: guard, db: db, capacity: capacity}, nil
}
func (s *Store) Close() error { return errors.Join(s.db.Close(), s.Guard.Close()) }

// Pending counts durable records without creating or changing a frozen batch.
func (s *Store) Pending(ctx context.Context) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var count int
	err := s.db.QueryRowContext(ctx, `SELECT count(*) FROM runtime_queue`).Scan(&count)
	return count, err
}

func (s *Store) Append(ctx context.Context, r Record) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	var count int
	if err := s.db.QueryRowContext(ctx, `SELECT count(*) FROM runtime_queue`).Scan(&count); err != nil {
		return err
	}
	payload := r.Bytes()
	var old []byte
	err := s.db.QueryRowContext(ctx, `SELECT payload FROM runtime_queue WHERE monitor=? AND sequence=?`, r.Monitor, r.Sequence).Scan(&old)
	if err == nil {
		if string(old) != string(payload) {
			return errors.New("aidr_enforcement_record_conflict")
		}
		return nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if count >= s.capacity {
		return errors.New("aidr_enforcement_outbox_full")
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO runtime_queue(monitor,sequence,payload) VALUES(?,?,?)`, r.Monitor, r.Sequence, payload)
	return err
}
func (s *Store) Prepare(ctx context.Context) (*Batch, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b := &Batch{}
	err := s.db.QueryRowContext(ctx, `SELECT through_id,count,payload,digest FROM runtime_frozen WHERE singleton=1`).Scan(&b.Through, &b.Count, &b.Payload, &b.Digest)
	if err == nil {
		return b, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	rows, err := s.db.QueryContext(ctx, `SELECT id,payload FROM runtime_queue ORDER BY id LIMIT 128`)
	if err != nil {
		return nil, err
	}
	var records []json.RawMessage
	size := 0
	for rows.Next() {
		var id int64
		var raw []byte
		if err = rows.Scan(&id, &raw); err != nil {
			rows.Close()
			return nil, err
		}
		if size+len(raw) > 900000 {
			break
		}
		records = append(records, json.RawMessage(raw))
		size += len(raw)
		b.Through = id
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if len(records) == 0 {
		return nil, nil
	}
	b.Count = len(records)
	b.Payload, err = json.Marshal(struct {
		Records []json.RawMessage `json:"records"`
	}{records})
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(b.Payload)
	b.Digest = hex.EncodeToString(sum[:])
	_, err = s.db.ExecContext(ctx, `INSERT INTO runtime_frozen VALUES(1,?,?,?,?)`, b.Through, b.Count, b.Payload, b.Digest)
	return b, err
}
func (s *Store) Acknowledge(ctx context.Context, digest string, count int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var id int64
	var expected string
	var n int
	if err = tx.QueryRowContext(ctx, `SELECT through_id,count,digest FROM runtime_frozen WHERE singleton=1`).Scan(&id, &n, &expected); err != nil {
		return err
	}
	if digest != expected || count != n {
		return errors.New("aidr_enforcement_ack_invalid")
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM runtime_queue WHERE id<=?`, id); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM runtime_frozen WHERE singleton=1`); err != nil {
		return err
	}
	return tx.Commit()
}
