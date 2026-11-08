package hooks

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	products "skill-manager/scanner/internal/aidr/catalog"
	"skill-manager/scanner/internal/aidr/localstore"
	"skill-manager/scanner/internal/aidr/privatefs"
)

// Store owns a separate hook state directory. The existing P1 directory guard
// supplies single-writer locking and immutable destination binding; P1 log data
// and P2 runtime queues are not migrated or rewritten.
type Store struct {
	directory                 string
	guard                     *localstore.Store
	db                        *sql.DB
	mu                        sync.Mutex
	key                       []byte
	stream, device            string
	platform                  string
	instance                  string
	controlKey                []byte
	controlMode               string
	bridgeIntercept           atomic.Bool
	controlPolicy             *ToolPolicy
	compatiblePolicyRevisions map[string]bool
	controlPayload            []byte
	policy                    agentlog.AuditPolicy
	capacity                  int
	runtimeCollection         *runtimeCollection
}

type Record struct {
	EventID          string         `json:"event_id"`
	Sequence         string         `json:"source_seq"`
	User             string         `json:"user_scope"`
	ReceivedAt       string         `json:"received_at"`
	Event            Event          `json:"event"`
	ReceiverInstance string         `json:"receiver_instance,omitempty"`
	BridgeProcess    *BridgeProcess `json:"bridge_process,omitempty"`
}
type Batch struct {
	Payload []byte
	Digest  string
	Count   int
}

var eventID = regexp.MustCompile(`^[0-9a-f]{32}$`)

func OpenStore(directory, platform, device string, capacity int) (*Store, error) {
	if capacity < 1 || capacity > 100000 || !validID(device, true) {
		return nil, code("aidr_hook_store_config_invalid")
	}
	u, err := url.Parse(platform)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, code("aidr_hook_destination_invalid")
	}
	g, err := localstore.Open(directory, localstore.DefaultLimits())
	if err != nil {
		return nil, err
	}
	fail := func(e error) (*Store, error) { g.Close(); return nil, e }
	identity, _ := json.Marshal([]string{"hooks/1", platform, device})
	if err = g.BindDestination(context.Background(), string(identity)); err != nil {
		return fail(err)
	}
	for _, name := range []string{"hooks.db", "hooks.db-wal", "hooks.db-shm"} {
		if info, e := os.Lstat(filepath.Join(directory, name)); e == nil {
			if !info.Mode().IsRegular() || privatefs.Check(filepath.Join(directory, name)) != nil {
				return fail(code("aidr_hook_store_invalid"))
			}
		} else if !os.IsNotExist(e) {
			return fail(e)
		}
	}
	file := filepath.Join(directory, "hooks.db")
	f, err := os.OpenFile(file, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return fail(err)
	}
	f.Close()
	db, err := sql.Open("sqlite", privatefs.SQLiteURI(file, ""))
	if err != nil {
		return fail(err)
	}
	db.SetMaxOpenConns(1)
	// SQLite's busy handler can outlive Go context cancellation. Keep each
	// writer wait below the receiver's one-second work budget.
	_, err = db.Exec(`PRAGMA busy_timeout=250; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA wal_autocheckpoint=256; PRAGMA journal_size_limit=1048576; PRAGMA max_page_count=65536;
CREATE TABLE IF NOT EXISTS hook_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO hook_meta VALUES('schema','1');
CREATE TABLE IF NOT EXISTS hook_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,input_hash TEXT NOT NULL,payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS hook_receipts(event_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,seq INTEGER NOT NULL,user_scope TEXT NOT NULL,received_at TEXT NOT NULL,acked_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS hook_receipts_expiry ON hook_receipts(acked_at);
CREATE TABLE IF NOT EXISTS hook_suppressed_receipts(event_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,seen_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS hook_suppressed_expiry ON hook_suppressed_receipts(seen_at);
CREATE TABLE IF NOT EXISTS hook_grants(id TEXT PRIMARY KEY,nonce TEXT UNIQUE NOT NULL,scope TEXT NOT NULL,revision INTEGER NOT NULL,decision TEXT NOT NULL,consumed INTEGER NOT NULL DEFAULT 0,payload BLOB NOT NULL,digest TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS hook_grant_used_attempt ON hook_grants(json_extract(scope,'$.attempt_nonce')) WHERE consumed=1;
CREATE TABLE IF NOT EXISTS hook_attempts(event_id TEXT PRIMARY KEY,receiver TEXT NOT NULL,user_scope TEXT NOT NULL,scope TEXT NOT NULL,expires_at INTEGER NOT NULL,approval_id TEXT NOT NULL DEFAULT '',last_try INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending',code TEXT NOT NULL DEFAULT 'aidr_hook_approval_pending');
CREATE TABLE IF NOT EXISTS hook_attempt_reports(event_id TEXT PRIMARY KEY,payload BLOB NOT NULL,digest TEXT NOT NULL,acked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS hook_frozen(singleton INTEGER PRIMARY KEY CHECK(singleton=1),through_seq INTEGER NOT NULL,count INTEGER NOT NULL,digest TEXT NOT NULL,payload BLOB NOT NULL);`)
	if err != nil {
		db.Close()
		return fail(err)
	}
	s := &Store{directory: directory, guard: g, db: db, device: device, platform: platform, capacity: capacity}
	instanceBytes := make([]byte, 16)
	if _, err = rand.Read(instanceBytes); err != nil {
		s.Close()
		return nil, err
	}
	s.instance = hex.EncodeToString(instanceBytes)
	// A receiver restart invalidates every previous single-use authority. Audit
	// events and upload receipts keep their own independent retention semantics.
	if _, err = db.Exec(`DELETE FROM hook_grants; UPDATE hook_attempts SET state='denied',code='aidr_hook_receiver_restarted' WHERE state='pending'`); err != nil {
		s.Close()
		return nil, err
	}
	var schema string
	if err = db.QueryRow(`SELECT value FROM hook_meta WHERE key='schema'`).Scan(&schema); err != nil || schema != "1" {
		s.Close()
		return nil, code("aidr_hook_store_version")
	}
	for _, item := range []struct {
		name string
		size int
	}{{"digest_key", 32}, {"stream", 16}} {
		var v string
		err = db.QueryRow(`SELECT value FROM hook_meta WHERE key=?`, item.name).Scan(&v)
		if errors.Is(err, sql.ErrNoRows) {
			b := make([]byte, item.size)
			_, err = rand.Read(b)
			if err == nil {
				v = hex.EncodeToString(b)
				_, err = db.Exec(`INSERT INTO hook_meta VALUES(?,?)`, item.name, v)
			}
		}
		decoded, e := hex.DecodeString(v)
		if err != nil || e != nil || len(decoded) != item.size {
			s.Close()
			return nil, code("aidr_hook_store_identity_invalid")
		}
		if item.name == "digest_key" {
			s.key = decoded
		} else {
			s.stream = v
		}
	}
	if err = g.LoadPolicy(context.Background()); err != nil {
		s.Close()
		return nil, err
	}
	s.policy = *g.Policy()
	var rawPolicy string
	err = db.QueryRow(`SELECT value FROM hook_meta WHERE key='audit_policy'`).Scan(&rawPolicy)
	if err == nil {
		if json.Unmarshal([]byte(rawPolicy), &s.policy) != nil || !s.policy.Valid() {
			s.Close()
			return nil, code("aidr_hook_policy_invalid")
		}
	} else if !errors.Is(err, sql.ErrNoRows) {
		s.Close()
		return nil, err
	}
	if err = s.loadRuntimeCollection(context.Background()); err != nil {
		s.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) Close() error { return errors.Join(s.db.Close(), s.guard.Close()) }
func (s *Store) SetPolicy(ctx context.Context, p agentlog.AuditPolicy) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !p.Valid() {
		return code("aidr_hook_policy_invalid")
	}
	if p.Equal(s.policy) {
		return nil
	}
	if p.Receipt == s.policy.Receipt {
		return code("aidr_hook_policy_invalid")
	}
	raw, _ := json.Marshal(p)
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	_, err = tx.ExecContext(ctx, `INSERT INTO hook_meta VALUES('audit_policy',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, string(raw))
	if err == nil {
		_, err = tx.ExecContext(ctx, `INSERT INTO hook_meta VALUES('audit_policy_after',(SELECT CAST(COALESCE((SELECT seq FROM sqlite_sequence WHERE name='hook_events'),0) AS TEXT))) ON CONFLICT(key) DO UPDATE SET value=excluded.value`)
	}
	if err == nil {
		err = tx.Commit()
	}
	if err == nil {
		s.policy = p
	}
	return err
}

type StoreStatus struct {
	Stream             string               `json:"stream_id"`
	Device             string               `json:"client_id"`
	Queued             int                  `json:"queued_records"`
	LastSequence       string               `json:"last_sequence"`
	AppliedAfter       string               `json:"applied_after"`
	Policy             agentlog.AuditPolicy `json:"policy"`
	ReceiverInstance   string               `json:"receiver_instance"`
	ControlMode        string               `json:"control_mode"`
	ControlRevision    string               `json:"control_revision,omitempty"`
	ControlCode        string               `json:"control_code"`
	LastAcknowledgedAt string               `json:"last_event_ack_at,omitempty"`
	Suppressed         int                  `json:"audit_suppressed_recent"`
	RuntimeEnabled     *bool                `json:"runtime_collection_enabled,omitempty"`
	RuntimeVersion     string               `json:"runtime_policy_version,omitempty"`
	PendingUploads     int                  `json:"pending_upload_records"`
}

func (s *Store) Destination() (string, string) { return s.platform, s.device }

func (s *Store) BridgeControlMode() string {
	if s.bridgeIntercept.Load() {
		return "plugin_pre_tool"
	}
	return "audit"
}

// Socket deadlines cannot cancel sync.Mutex.Lock; queueing must share the
// request budget so a busy store still leaves time to send a framed response.
func (s *Store) lockContext(ctx context.Context) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		if s.mu.TryLock() {
			return nil
		}
		timer := time.NewTimer(5 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

func (s *Store) bridgeControlModeContext(ctx context.Context) (string, error) {
	if err := s.lockContext(ctx); err != nil {
		return "", err
	}
	defer s.mu.Unlock()
	if s.controlMode == "intercept" {
		return "plugin_pre_tool", nil
	}
	return "audit", nil
}

func (s *Store) Status(ctx context.Context) (StoreStatus, error) {
	if err := s.lockContext(ctx); err != nil {
		return StoreStatus{}, err
	}
	defer s.mu.Unlock()
	status := StoreStatus{Stream: s.stream, Device: s.device, Policy: s.policy, ReceiverInstance: s.instance}
	if s.runtimeCollection != nil {
		enabled := s.runtimeCollection.Enabled
		status.RuntimeEnabled, status.RuntimeVersion = &enabled, s.runtimeCollection.Version
	}
	status.ControlMode = "audit"
	status.ControlCode = "aidr_hook_audit_only"
	if s.controlMode == "intercept" {
		status.ControlMode = "plugin_pre_tool"
		status.ControlCode = "aidr_hook_policy_missing"
		if s.controlPolicy != nil {
			status.ControlRevision = s.controlPolicy.Revision
			status.ControlCode = "aidr_hook_policy_ready"
		}
	}
	var pendingAttempts int
	err := s.db.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM hook_events),CAST(COALESCE((SELECT seq FROM sqlite_sequence WHERE name='hook_events'),0) AS TEXT),COALESCE((SELECT value FROM hook_meta WHERE key='audit_policy_after'),'0'),COALESCE((SELECT value FROM hook_meta WHERE key='last_event_ack_at'),''),(SELECT count(*) FROM hook_suppressed_receipts WHERE seen_at>=?),(SELECT count(*) FROM hook_attempt_reports WHERE acked=0)+(SELECT count(*) FROM hook_attempts WHERE state='pending')`, time.Now().Add(-48*time.Hour).Unix()).Scan(&status.Queued, &status.LastSequence, &status.AppliedAfter, &status.LastAcknowledgedAt, &status.Suppressed, &pendingAttempts)
	status.PendingUploads = status.Queued + pendingAttempts
	return status, err
}

// Receive takes user identity from the authenticated IPC peer, not the JSON.
// The transport's event ID stays constant on retries. Duplicates retain the
// original projection even if the platform redaction policy has since changed.
func (s *Store) Receive(ctx context.Context, id, user, agent, hook string, raw []byte) (Record, error) {
	return s.receiveWithBridge(ctx, id, user, agent, hook, raw, nil)
}

func (s *Store) receiveWithBridge(ctx context.Context, id, user, agent, hook string, raw []byte, bridge *BridgeProcess) (Record, error) {
	if err := s.lockContext(ctx); err != nil {
		return Record{}, err
	}
	defer s.mu.Unlock()
	var r Record
	if !eventID.MatchString(id) || !validID(user, true) {
		return r, code("aidr_hook_identity_invalid")
	}
	if len(raw) > MaxRecordBytes {
		return r, code("aidr_hook_record_oversized")
	}
	identity, _ := json.Marshal([]string{user, agent, hook, string(raw)})
	hash := digest(s.key, "hook-receipt/1", identity)
	var oldHash string
	var old []byte
	err := s.db.QueryRowContext(ctx, `SELECT input_hash,payload FROM hook_events WHERE event_id=?`, id).Scan(&oldHash, &old)
	if err == nil {
		if oldHash != hash {
			return r, code("aidr_hook_event_conflict")
		}
		err = json.Unmarshal(old, &r)
		return r, err
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return r, err
	}
	var oldSeq int64
	err = s.db.QueryRowContext(ctx, `SELECT input_hash,seq,user_scope,received_at FROM hook_receipts WHERE event_id=?`, id).Scan(&oldHash, &oldSeq, &r.User, &r.ReceivedAt)
	if err == nil {
		if oldHash != hash {
			return Record{}, code("aidr_hook_event_conflict")
		}
		r.EventID, r.Sequence = id, strconv.FormatInt(oldSeq, 10)
		return r, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return r, err
	}
	if s.runtimeCollection != nil && !s.runtimeCollection.Enabled {
		return r, code("aidr_hook_collection_disabled")
	}
	if !freshEventID(id, time.Now()) {
		return r, code("aidr_hook_event_expired")
	}
	err = s.db.QueryRowContext(ctx, `SELECT input_hash FROM hook_suppressed_receipts WHERE event_id=?`, id).Scan(&oldHash)
	if err == nil {
		if oldHash != hash {
			return r, code("aidr_hook_event_conflict")
		}
		return Record{EventID: id}, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return r, err
	}
	e, err := Normalize(agent, hook, raw, s.policy, s.key)
	if err != nil {
		return r, err
	}
	if s.controlPolicy != nil {
		e.CommandMatch = s.controlPolicy.observeCommand(e, raw)
	}
	if e.Kind == "tool.pre" {
		e.ControlMode = "audit"
		if s.controlMode == "intercept" {
			e.ControlMode = "plugin_pre_tool"
		}
	}
	// Pin the control decision to the same policy and immutable event before
	// uploads can observe it. IPC returns this decision to the host.
	if e.Kind == "tool.pre" && s.controlMode == "intercept" {
		d := s.evaluateToolLocked(e, time.Now())
		product, _ := products.Get(agent)
		if d.Decision == "ask" && !product.Approval {
			d.Decision, d.Code = "deny", "aidr_hook_approval_unsupported"
		}
		if d.Decision == "ask" && !s.policy.CollectionEnabled() {
			d.Decision, d.Code = "deny", "aidr_hook_audit_disabled_requires_evidence"
		}
		e.ControlDecision = &d
	}
	if !s.policy.CollectionEnabled() {
		// Keep live control evaluation separate from audit persistence. An ask
		// decision needs durable evidence and is handled explicitly by IPC.
		if _, err = s.db.ExecContext(ctx, `DELETE FROM hook_suppressed_receipts WHERE event_id IN (SELECT event_id FROM hook_suppressed_receipts WHERE seen_at<? ORDER BY seen_at,event_id LIMIT 500)`, time.Now().Add(-48*time.Hour).Unix()); err != nil {
			return r, err
		}
		var suppressed int
		if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM hook_suppressed_receipts`).Scan(&suppressed); err != nil {
			return r, err
		}
		if suppressed >= 1000000 {
			return r, code("aidr_hook_suppressed_capacity")
		}
		if _, err = s.db.ExecContext(ctx, `INSERT INTO hook_suppressed_receipts VALUES(?,?,?)`, id, hash, time.Now().Unix()); err != nil {
			return r, err
		}
		return Record{EventID: id, User: user, ReceivedAt: time.Now().UTC().Format(time.RFC3339Nano), Event: e, ReceiverInstance: s.instance, BridgeProcess: bridge}, nil
	}
	var count int
	if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM hook_events`).Scan(&count); err != nil {
		return r, err
	}
	if count >= s.capacity {
		return r, code("aidr_hook_outbox_full")
	}
	// Pending records never expire. Only receipts for already confirmed uploads
	// are removed; expired IDs cannot become new events after this pruning.
	if _, err = s.db.ExecContext(ctx, `DELETE FROM hook_receipts WHERE acked_at<?`, time.Now().Add(-48*time.Hour).Unix()); err != nil {
		return r, err
	}
	var receipts int
	if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM hook_receipts`).Scan(&receipts); err != nil {
		return r, err
	}
	if receipts+count >= 1000000 {
		return r, code("aidr_hook_receipt_capacity")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return r, err
	}
	defer tx.Rollback()
	result, err := tx.ExecContext(ctx, `INSERT INTO hook_events(event_id,input_hash,payload) VALUES(?,?,?)`, id, hash, []byte{})
	if err != nil {
		return r, err
	}
	seq, err := result.LastInsertId()
	if err != nil {
		return r, err
	}
	r = Record{EventID: id, Sequence: strconv.FormatInt(seq, 10), User: user, ReceivedAt: time.Now().UTC().Format(time.RFC3339Nano), Event: e, ReceiverInstance: s.instance, BridgeProcess: bridge}
	payload, err := json.Marshal(r)
	if err != nil {
		return r, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE hook_events SET payload=? WHERE seq=?`, payload, seq); err != nil {
		return r, err
	}
	err = tx.Commit()
	return r, err
}

func (s *Store) Prepare(ctx context.Context) (*Batch, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b := &Batch{}
	var frozen bool
	err := s.db.QueryRowContext(ctx, `SELECT 1 AS frozen,count,digest,payload FROM hook_frozen WHERE singleton=1
 UNION ALL SELECT 0,0,'',X'' WHERE EXISTS(SELECT 1 FROM hook_events)
 ORDER BY frozen DESC LIMIT 1`).Scan(&frozen, &b.Count, &b.Digest, &b.Payload)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if frozen {
		return b, nil
	}
	rows, err := s.db.QueryContext(ctx, `SELECT seq,payload FROM hook_events ORDER BY seq LIMIT 100`)
	if err != nil {
		return nil, err
	}
	var records []json.RawMessage
	var through int64
	size := 0
	for rows.Next() {
		var seq int64
		var raw []byte
		if err = rows.Scan(&seq, &raw); err != nil {
			rows.Close()
			return nil, err
		}
		if size+len(raw) > 900000 {
			break
		}
		records = append(records, json.RawMessage(raw))
		size += len(raw)
		through = seq
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
		Schema  int               `json:"schema_version"`
		Device  string            `json:"client_id"`
		Stream  string            `json:"stream_id"`
		Records []json.RawMessage `json:"records"`
	}{1, s.device, s.stream, records})
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(b.Payload)
	b.Digest = hex.EncodeToString(sum[:])
	_, err = s.db.ExecContext(ctx, `INSERT INTO hook_frozen VALUES(1,?,?,?,?)`, through, b.Count, b.Digest, b.Payload)
	return b, err
}

func (s *Store) Acknowledge(ctx context.Context, device, stream, hash string, count int, durable bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !durable || device != s.device || stream != s.stream {
		return code("aidr_hook_ack_invalid")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var through int64
	var n int
	var expected string
	if err = tx.QueryRowContext(ctx, `SELECT through_seq,count,digest FROM hook_frozen WHERE singleton=1`).Scan(&through, &n, &expected); err != nil {
		return err
	}
	if count != n || hash != expected {
		return code("aidr_hook_ack_invalid")
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO hook_meta VALUES('last_event_ack_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO hook_receipts(event_id,input_hash,seq,user_scope,received_at,acked_at)
SELECT event_id,input_hash,seq,json_extract(payload,'$.user_scope'),json_extract(payload,'$.received_at'),? FROM hook_events WHERE seq<=?`, time.Now().Unix(), through); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM hook_events WHERE seq<=?`, through); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM hook_frozen WHERE singleton=1`); err != nil {
		return err
	}
	return tx.Commit()
}
