// Package localstore owns the durable, local Agent log ingestion checkpoint.
// Transport authentication and remote ACK verification belong to the uploader.
package localstore

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"time"

	_ "modernc.org/sqlite"
	"skill-manager/scanner/internal/aidr/agentlog"
)

var (
	ErrCapacity      = errors.New("aidr_store_capacity")
	ErrConflict      = errors.New("aidr_store_checkpoint_conflict")
	ErrBatchConflict = errors.New("aidr_store_batch_conflict")
	ErrInvalid       = errors.New("aidr_store_invalid")
)

type Limits struct {
	DatabaseBytes int64
	LogicalEvents int
	Evidence      int
	Sources       int
	Retention     time.Duration
}

func DefaultLimits() Limits { return Limits{1 << 30, 100000, 200000, 4096, 7 * 24 * time.Hour} }
func (l Limits) valid() bool {
	return l.DatabaseBytes >= 1<<20 && l.DatabaseBytes <= 4<<30 && l.LogicalEvents > 0 && l.LogicalEvents <= 1000000 && l.Evidence > 0 && l.Evidence <= 2000000 && l.Sources > 0 && l.Sources <= 16384 && l.Retention > 0 && l.Retention <= 365*24*time.Hour
}

type Store struct {
	skillObserver      *agentlog.SkillObserver
	policy             *agentlog.AuditPolicy
	collectionResumeAt time.Time
	runtimeResumeAt    time.Time
	pruneMu            sync.Mutex
	lastIntakePrune    time.Time
	mu                 sync.Mutex
	db                 *sql.DB
	lock               *os.File
	limits             Limits
	closed             bool
	// Test-only crash injection at durable boundaries; never configured by CLI.
	hook func(string)
}

const schema = `
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_dirs(root_key TEXT NOT NULL,path TEXT NOT NULL,visited_ns INTEGER NOT NULL DEFAULT 0,probe_ns INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',PRIMARY KEY(root_key,path));
CREATE TABLE IF NOT EXISTS discovery_files(id TEXT PRIMARY KEY,root_key TEXT NOT NULL,agent TEXT NOT NULL,root TEXT NOT NULL,path TEXT NOT NULL,mtime_ns INTEGER NOT NULL,size INTEGER NOT NULL,probe_ns INTEGER NOT NULL DEFAULT 0,read_ns INTEGER NOT NULL DEFAULT 0,pending INTEGER NOT NULL DEFAULT 1,reason TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS discovery_files_schedule ON discovery_files(root_key,pending,read_ns);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, cursor TEXT NOT NULL, coverage TEXT NOT NULL,
 revision INTEGER NOT NULL, updated_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS logical_events(
 id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, payload TEXT,
 created_ns INTEGER NOT NULL, acked_ns INTEGER, source_id TEXT, observed_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence(
 id TEXT PRIMARY KEY, logical_id TEXT NOT NULL REFERENCES logical_events(id),
 content_hash TEXT NOT NULL, payload TEXT, created_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS event_turn_links(
 id TEXT PRIMARY KEY REFERENCES logical_events(id) ON DELETE CASCADE, turn_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_logical ON evidence(logical_id);
CREATE TABLE IF NOT EXISTS coverage_history(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, payload TEXT NOT NULL,
 created_ns INTEGER NOT NULL, acked_ns INTEGER, payload_encoding TEXT NOT NULL DEFAULT 'json'
);
CREATE TABLE IF NOT EXISTS outbox(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
 record_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
 created_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS active_batch(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL,
 digest TEXT NOT NULL, payload BLOB NOT NULL, through_seq INTEGER NOT NULL
);
PRAGMA user_version=1;
`

// Open requires a private directory dedicated to this store. The OS lock is
// released on process death, so crash recovery never depends on stale lock PIDs.
func Open(dir string, limits Limits) (*Store, error) {
	if !limits.valid() || !filepath.IsAbs(dir) {
		return nil, ErrInvalid
	}
	dir = filepath.Clean(dir)
	for p := dir; ; p = filepath.Dir(p) {
		i, err := os.Lstat(p)
		if (err != nil && !os.IsNotExist(err)) || (err == nil && (!i.IsDir() || i.Mode()&os.ModeSymlink != 0)) {
			return nil, errors.New("aidr_store_path_invalid")
		}
		if filepath.Dir(p) == p {
			break
		}
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	if err := privateDirectory(dir); err != nil {
		return nil, err
	}
	for _, name := range []string{"state.db", "state.db-wal", "state.db-shm", "writer.lock"} {
		i, err := os.Lstat(filepath.Join(dir, name))
		if err == nil && (!i.Mode().IsRegular() || i.Mode().Perm()&0077 != 0) {
			return nil, errors.New("aidr_store_path_invalid")
		}
		if err != nil && !os.IsNotExist(err) {
			return nil, err
		}
	}
	lock, err := lockDirectory(filepath.Join(dir, "writer.lock"))
	if err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "state.db")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		lock.Close()
		return nil, err
	}
	f.Close()
	db, err := sql.Open("sqlite", (&url.URL{Scheme: "file", Path: filepath.ToSlash(path)}).String())
	if err != nil {
		lock.Close()
		return nil, err
	}
	s := &Store{db: db, lock: lock, limits: limits, skillObserver: agentlog.NewSkillObserver()}
	fail := func(e error) (*Store, error) { db.Close(); lock.Close(); return nil, e }
	db.SetMaxOpenConns(1)
	if _, err = db.Exec(`PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA wal_autocheckpoint=256; PRAGMA journal_size_limit=1048576;`); err != nil {
		return fail(err)
	}
	var version, pageSize int
	if err = db.QueryRow(`PRAGMA user_version`).Scan(&version); err != nil {
		return fail(err)
	}
	if version != 0 && version != 1 {
		return fail(errors.New("aidr_store_schema_unsupported"))
	}
	if err = db.QueryRow(`PRAGMA page_size`).Scan(&pageSize); err != nil {
		return fail(err)
	}
	var autoVacuum int
	if err = db.QueryRow(`PRAGMA auto_vacuum`).Scan(&autoVacuum); err != nil {
		return fail(err)
	}
	if autoVacuum == 0 {
		// Upgrade existing databases in place; no identity or queue is discarded.
		if _, err = db.Exec(`PRAGMA auto_vacuum=INCREMENTAL; VACUUM;`); err != nil {
			return fail(storageError(err))
		}
	}
	var pages int64
	if err = db.QueryRow(fmt.Sprintf(`PRAGMA max_page_count=%d`, limits.DatabaseBytes/int64(pageSize))).Scan(&pages); err != nil {
		return fail(err)
	}
	if pages*int64(pageSize) > limits.DatabaseBytes {
		return fail(ErrCapacity)
	}
	if _, err = db.Exec(schema); err != nil {
		return fail(err)
	}
	if err = s.compactCoverageHistory(context.Background()); err != nil {
		return fail(storageError(err))
	}
	if err = s.initializeACKRelease(context.Background()); err != nil {
		return fail(storageError(err))
	}
	tx, err := db.Begin()
	if err != nil {
		return fail(err)
	}
	defer tx.Rollback()
	failTx := func(e error) (*Store, error) { tx.Rollback(); return fail(e) }
	var clean string
	err = tx.QueryRow(`SELECT value FROM metadata WHERE key='clean_shutdown'`).Scan(&clean)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return failTx(err)
	}
	if clean == "0" {
		if _, err = tx.Exec(`INSERT INTO metadata(key,value) VALUES('recovery_code','aidr_store_unclean_shutdown') ON CONFLICT(key) DO UPDATE SET value=excluded.value`); err != nil {
			return failTx(err)
		}
	}
	if _, err = tx.Exec(`INSERT INTO metadata(key,value) VALUES('clean_shutdown','0') ON CONFLICT(key) DO UPDATE SET value='0'`); err != nil {
		return failTx(err)
	}
	if err = tx.Commit(); err != nil {
		return fail(err)
	}
	return s, nil
}

func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	_, err := s.db.Exec(`UPDATE metadata SET value='1' WHERE key='clean_shutdown'`)
	_, checkpointErr := s.db.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`)
	return errors.Join(err, checkpointErr, s.db.Close(), s.lock.Close())
}

type Checkpoint struct {
	Revision int64             `json:"revision,string"`
	Cursor   agentlog.Cursor   `json:"cursor"`
	Coverage agentlog.Coverage `json:"coverage"`
}

func (s *Store) Checkpoint(ctx context.Context, sourceID string) (Checkpoint, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var c Checkpoint
	var cursor, coverage string
	err := s.db.QueryRowContext(ctx, `SELECT revision,cursor,coverage FROM sources WHERE id=?`, sourceID).Scan(&c.Revision, &cursor, &coverage)
	if errors.Is(err, sql.ErrNoRows) {
		return c, nil
	}
	if err != nil {
		return c, err
	}
	if json.Unmarshal([]byte(cursor), &c.Cursor) != nil || json.Unmarshal([]byte(coverage), &c.Coverage) != nil {
		return c, errors.New("aidr_store_corrupt")
	}
	return c, nil
}
func hash(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }
func canonicalEvent(e agentlog.Event) []byte {
	e.ReceivedAt = time.Time{}
	b, _ := json.Marshal(e)
	return b
}

// Commit uses optimistic revision comparison and one transaction for events,
// coverage, source generation, checkpoint and outbox. It never advances on error.
func (s *Store) Commit(ctx context.Context, previous Checkpoint, b agentlog.ReadBatch) (result Checkpoint, resultErr error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	defer func() {
		resultErr = storageError(resultErr)
		if resultErr != nil {
			code := "aidr_store_write_failed"
			if errors.Is(resultErr, ErrCapacity) {
				code = ErrCapacity.Error()
			}
			// Best effort when the medium itself is full; the caller always gets
			// the failure and the checkpoint transaction remains rolled back.
			s.db.Exec(`INSERT INTO metadata(key,value) VALUES('intake_code',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, code)
		}
	}()
	var zero Checkpoint
	expected, err := agentlog.NewSource(b.Source.Agent, b.Source.Root, b.Source.Path)
	if err != nil || expected.ID != b.Source.ID || b.SchemaVersion != 1 || len(b.Events) > 4096 {
		return zero, ErrInvalid
	}
	if len(b.TurnLinks) > 128 || (len(b.TurnLinks) > 0 && b.Source.Agent != "teleagent" && b.Source.Agent != "doubaowork") {
		return zero, ErrInvalid
	}
	if b.Cursor.SchemaVersion != 0 {
		if agentlog.ValidateCursor(b.Cursor, b.Source) != nil {
			return zero, ErrInvalid
		}
	} else if len(b.Events) != 0 || b.Coverage.Status != "unavailable" {
		return zero, ErrInvalid
	}
	if b.Coverage.Status != "complete" && b.Coverage.Status != "partial" && b.Coverage.Status != "unavailable" {
		return zero, ErrInvalid
	}
	coverage, _ := json.Marshal(b.Coverage)
	cursor, _ := json.Marshal(b.Cursor)
	if len(coverage) > 16384 || len(cursor) > 512<<10 {
		return zero, ErrInvalid
	}
	for _, e := range b.Events {
		if agentlog.ValidateEvent(e) != nil || e.SourceID != b.Source.ID {
			return zero, ErrInvalid
		}
	}
	for _, link := range b.TurnLinks {
		if !agentlog.ValidateTurnLink(link) {
			return zero, ErrInvalid
		}
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return zero, err
	}
	defer tx.Rollback()
	var rev int64
	var oldCursor string
	err = tx.QueryRowContext(ctx, `SELECT revision,cursor FROM sources WHERE id=?`, b.Source.ID).Scan(&rev, &oldCursor)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return zero, err
	}
	prevJSON, _ := json.Marshal(previous.Cursor)
	if rev != previous.Revision || (rev != 0 && oldCursor != string(prevJSON)) {
		return zero, ErrConflict
	}
	if previous.Cursor.SchemaVersion != 0 && (b.Cursor.Generation < previous.Cursor.Generation || (b.Cursor.Generation == previous.Cursor.Generation && b.Cursor.Offset < previous.Cursor.Offset)) {
		return zero, ErrConflict
	}
	if rev == 0 {
		var n int
		if err = tx.QueryRow(`SELECT count(*) FROM sources`).Scan(&n); err != nil {
			return zero, err
		}
		if n >= s.limits.Sources {
			return zero, ErrCapacity
		}
	}
	now := time.Now().UnixNano()
	b.Events, b.Coverage, err = retireFilter(tx, b.Events, b.Coverage)
	if err != nil {
		return zero, err
	}
	for _, reason := range b.Coverage.Reasons {
		if reason == retirementReason || reason == futureReason {
			found := false
			for _, gap := range b.Cursor.Gaps {
				if gap == reason {
					found = true
					break
				}
			}
			if !found {
				b.Cursor.Gaps = append(b.Cursor.Gaps, reason)
			}
		}
	}
	coverage, _ = json.Marshal(b.Coverage)
	cursor, _ = json.Marshal(b.Cursor)
	if len(coverage) > 16384 || len(cursor) > 512<<10 {
		return zero, ErrInvalid
	}
	var nextRevision int64
	if err = tx.QueryRow(`SELECT max(coalesce((SELECT CAST(value AS INTEGER) FROM metadata WHERE key='source_revision'),0),coalesce((SELECT max(revision) FROM sources),0))+1`).Scan(&nextRevision); err != nil {
		return zero, err
	}
	for _, e := range b.Events {
		payload, _ := json.Marshal(e)
		if len(payload) > 16384 {
			return zero, ErrInvalid
		}
		// Only fields used in the parser's logical identity belong here. A
		// repeated call can have a different timestamp, raw layout or version.
		logical, _ := json.Marshal([]string{e.SourceID, e.Agent, e.SessionID, e.TurnID, e.CallID, e.LogicalCallID, e.Kind, e.Tool, e.Outcome, e.ContentDigest})
		if e.SchemaVersion == 2 {
			projected, _ := json.Marshal(e.Behavior)
			logical = append(logical, projected...)
		}
		if e.Message != nil {
			projected, _ := json.Marshal(e.Message)
			logical = append(logical, projected...)
		}
		contentHash := hash(logical)
		res, err := tx.ExecContext(ctx, `INSERT INTO logical_events(id,content_hash,payload,created_ns,source_id,observed_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING`, e.LogicalEventID, contentHash, string(payload), now, e.SourceID, e.ObservedAt.UTC().Format(time.RFC3339Nano))
		if err != nil {
			return zero, err
		}
		inserted, _ := res.RowsAffected()
		var storedHash string
		if err = tx.QueryRow(`SELECT content_hash FROM logical_events WHERE id=?`, e.LogicalEventID).Scan(&storedHash); err != nil {
			return zero, err
		}
		if storedHash != contentHash {
			return zero, ErrBatchConflict
		}
		if inserted == 1 {
			if _, err = tx.Exec(`INSERT INTO outbox(kind,record_id,payload,created_ns) VALUES('event',?,?,?)`, e.LogicalEventID, string(payload), now); err != nil {
				return zero, err
			}
		}
		evidenceHash := hash(canonicalEvent(e))
		if _, err = tx.Exec(`INSERT INTO evidence(id,logical_id,content_hash,payload,created_ns) VALUES(?,?,?,CASE WHEN (SELECT acked_ns FROM logical_events WHERE id=?) IS NULL THEN ? ELSE NULL END,?) ON CONFLICT(id) DO NOTHING`, e.EventID, e.LogicalEventID, evidenceHash, e.LogicalEventID, string(payload), now); err != nil {
			return zero, err
		}
		if err = tx.QueryRow(`SELECT content_hash FROM evidence WHERE id=?`, e.EventID).Scan(&storedHash); err != nil {
			return zero, err
		}
		if storedHash != evidenceHash {
			return zero, ErrBatchConflict
		}
	}
	var logicalCount, evidenceCount int
	if err = tx.QueryRow(`SELECT (SELECT count(*) FROM logical_events),(SELECT count(*) FROM evidence)`).Scan(&logicalCount, &evidenceCount); err != nil {
		return zero, err
	}
	if logicalCount > s.limits.LogicalEvents || evidenceCount > s.limits.Evidence {
		return zero, ErrCapacity
	}
	// Unchanged polls don't grow the queue. Coverage changes are durable records
	// even when a missing/unreadable source has no initialized file cursor.
	var oldCoverage string
	err = tx.QueryRow(`SELECT coverage FROM sources WHERE id=?`, b.Source.ID).Scan(&oldCoverage)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return zero, err
	}
	var newLinks []agentlog.TurnLink
	for _, link := range b.TurnLinks {
		res, err := tx.ExecContext(ctx, `INSERT INTO event_turn_links(id,turn_id) SELECT id,? FROM logical_events WHERE id=? AND source_id=? ON CONFLICT(id) DO NOTHING`, link.TurnID, link.LogicalEventID, b.Source.ID)
		if err != nil {
			return zero, err
		}
		var turn string
		err = tx.QueryRowContext(ctx, `SELECT turn_id FROM event_turn_links WHERE id=?`, link.LogicalEventID).Scan(&turn)
		if errors.Is(err, sql.ErrNoRows) {
			continue
		}
		if err != nil {
			return zero, err
		}
		if turn != link.TurnID {
			return zero, ErrBatchConflict
		}
		if count, _ := res.RowsAffected(); count == 1 {
			newLinks = append(newLinks, link)
		}
	}
	if oldCoverage != string(coverage) || oldCursor != string(cursor) || len(newLinks) > 0 {
		// Repair progress is local scheduling state, not part of the wire cursor.
		wireCursor := b.Cursor
		wireCursor.DoubaoMessages = false
		wireCursor.DoubaoTurns = ""
		wireCursor.ContextRepair = nil
		wireCursor.ContextRepairVersion = 0
		wireCursor.CompletionSchema = 0
		// Call bindings are parser resume state; events carry their own call/turn IDs.
		wireCursor.CallTurns = nil
		wireCursor.QoderLinks = nil
		wireCursor.ModelContext = nil
		wireCursor.ModelProvider = ""
		wireCursor.ModelTurn = ""
		wireCursor.ModelHeaderRead = false
		envelope, _ := json.Marshal(struct {
			SourceID  string              `json:"source_id"`
			Revision  int64               `json:"revision,string"`
			Cursor    agentlog.Cursor     `json:"cursor"`
			Coverage  agentlog.Coverage   `json:"coverage"`
			TurnLinks []agentlog.TurnLink `json:"turn_links,omitempty"`
		}{b.Source.ID, nextRevision, wireCursor, b.Coverage, newLinks})
		coverageID := fmt.Sprintf("%s:%d", b.Source.ID, nextRevision)
		stored, encoding, err := encodeCoverage(envelope)
		if err != nil {
			return zero, err
		}
		if _, err = tx.Exec(`INSERT INTO coverage_history(id,source_id,payload,created_ns,payload_encoding) VALUES(?,?,?,?,?)`, coverageID, b.Source.ID, stored, now, encoding); err != nil {
			return zero, err
		}
		if _, err = tx.Exec(`INSERT INTO outbox(kind,record_id,payload,created_ns) VALUES('coverage',?,?,?)`, coverageID, string(envelope), now); err != nil {
			return zero, err
		}
	}
	// Count coverage-only traffic as well as events against the finite queue.
	var queueCount int
	if err = tx.QueryRow(`SELECT count(*) FROM outbox`).Scan(&queueCount); err != nil {
		return zero, err
	}
	if queueCount > s.limits.Evidence+s.limits.Sources {
		return zero, ErrCapacity
	}
	var histories int
	if err = tx.QueryRow(`SELECT count(*) FROM coverage_history`).Scan(&histories); err != nil {
		return zero, err
	}
	if histories > s.limits.Evidence {
		return zero, ErrCapacity
	}
	if _, err = tx.Exec(`INSERT INTO sources(id,cursor,coverage,revision,updated_ns) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET cursor=excluded.cursor,coverage=excluded.coverage,revision=excluded.revision,updated_ns=excluded.updated_ns`, b.Source.ID, string(cursor), string(coverage), nextRevision, now); err != nil {
		return zero, err
	}
	if _, err = tx.Exec(`INSERT INTO metadata(key,value) VALUES('source_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, nextRevision); err != nil {
		return zero, err
	}
	if s.hook != nil {
		s.hook("before_commit")
	}
	if _, err = tx.Exec(`DELETE FROM metadata WHERE key='intake_code'`); err != nil {
		return zero, err
	}
	if err = tx.Commit(); err != nil {
		return zero, err
	}
	if s.hook != nil {
		s.hook("after_commit")
	}
	return Checkpoint{nextRevision, b.Cursor, b.Coverage}, nil
}

func storageError(err error) error {
	var coded interface{ Code() int }
	if errors.As(err, &coded) && coded.Code()&255 == 13 {
		return ErrCapacity
	}
	return err
}

// Collect reads using the durable cursor, then atomically saves the proposal.
func (s *Store) Collect(ctx context.Context, source agentlog.Source, budget agentlog.Budget, since time.Time) (Checkpoint, error) {
	if err := s.pruneForIntake(ctx); err != nil {
		return Checkpoint{}, storageError(err)
	}
	c, err := s.Checkpoint(ctx, source.ID)
	if err != nil {
		return c, err
	}
	budget.CollectionResumeAt = s.collectionResumeAt
	if s.runtimeResumeAt.After(budget.CollectionResumeAt) {
		budget.CollectionResumeAt = s.runtimeResumeAt
	}
	b, err := agentlog.ReadWithPolicy(ctx, source, c.Cursor, budget, since, s.policy, s.skillObserver)
	if err != nil {
		return c, err
	}
	if s.hook != nil {
		s.hook("after_read")
	}
	if s.policy != nil {
		b.Events, err = s.preserveProjection(ctx, b.Events)
		if err != nil {
			return c, err
		}
	}
	return s.Commit(ctx, c, b)
}

// Retention is periodic maintenance, independent of the number of sources.
// Explicit Prune callers still run immediately (for maintenance and acceptance).
func (s *Store) pruneForIntake(ctx context.Context) error {
	s.pruneMu.Lock()
	defer s.pruneMu.Unlock()
	now := time.Now()
	if !s.lastIntakePrune.IsZero() && now.Sub(s.lastIntakePrune) < time.Minute {
		return nil
	}
	if _, err := s.Prune(ctx, now); err != nil {
		return err
	}
	s.lastIntakePrune = now
	return nil
}
