package localstore

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

var testContext = context.Background()

func tempDir(t *testing.T) string {
	t.Helper()
	p, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	if e = os.Chmod(p, 0700); e != nil {
		t.Fatal(e)
	}
	return p
}

func lines(n int) string {
	var b strings.Builder
	for i := 0; i < n; i++ {
		fmt.Fprintf(&b, "{\"type\":\"assistant\",\"timestamp\":\"2026-09-23T01:00:00Z\",\"sessionId\":\"test-session\",\"version\":\"2.1.220\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"call-%d\",\"name\":\"Bash\",\"input\":{\"command\":\"TOKEN=SYNTHETIC_PRIVATE_MARKER /bin/true\"}}]}}\n", i)
	}
	return b.String()
}
func source(t *testing.T, body string) agentlog.Source {
	t.Helper()
	root := tempDir(t)
	p := filepath.Join(root, "log.jsonl")
	if err := os.WriteFile(p, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := agentlog.NewSource("claude", root, p)
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func openStore(t *testing.T, dir string, l Limits) *Store {
	t.Helper()
	s, err := Open(dir, l)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}
func collect(t *testing.T, s *Store, src agentlog.Source) Checkpoint {
	t.Helper()
	c, err := s.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0).UTC())
	if err != nil {
		t.Fatal(err)
	}
	return c
}
func status(t *testing.T, s *Store) Status {
	t.Helper()
	v, e := s.Status(testContext)
	if e != nil {
		t.Fatal(e)
	}
	return v
}

func TestAtomicCheckpointResumeAndPrivacy(t *testing.T) {
	src := source(t, lines(3))
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	c := collect(t, s, src)
	if c.Cursor.Offset != int64(len(lines(3))) {
		t.Fatal(c)
	}
	if e := s.Close(); e != nil {
		t.Fatal(e)
	}
	s = openStore(t, dir, DefaultLimits())
	collect(t, s, src)
	v := status(t, s)
	if v.LogicalEvents != 3 || v.Evidence != 3 || v.RecoveryCode != "" {
		t.Fatal(v)
	}
	p, e := s.Events(testContext, "", 500)
	if e != nil {
		t.Fatal(e)
	}
	raw, _ := json.Marshal(p)
	if len(p.Events) != 3 || strings.Contains(string(raw), "SYNTHETIC_PRIVATE_MARKER") {
		t.Fatal("event projection leaked content")
	}
	s.Close()
	for _, name := range []string{"state.db", "state.db-wal"} {
		data, e := os.ReadFile(filepath.Join(dir, name))
		if e == nil && strings.Contains(string(data), "SYNTHETIC_PRIVATE_MARKER") {
			t.Fatal("database contains source content")
		}
	}
}

func TestContextRepairProgressStaysLocal(t *testing.T) {
	src := source(t, lines(1))
	s := openStore(t, tempDir(t), DefaultLimits())
	c := collect(t, s, src)
	r := c.Cursor
	r.ContextRepair = nil
	r.QoderLinks = []agentlog.QoderLink{{ID: "native-message", Turn: "native-request-set"}}
	r.ContextRepairVersion = 1
	next := c.Cursor
	next.QoderLinks = r.QoderLinks
	next.TraeHooks = map[string]int64{"native-hook": 1793024046944}
	next.TraeInput = "native-hook"
	next.ContextRepair = &r
	next.ContextRepairVersion = 0
	next.ModelContext = &agentlog.ModelContext{Model: "example", Source: "codex.turn_context"}
	next.ModelTurn, next.ModelProvider, next.ModelHeaderRead = "turn", "provider", true
	updated, err := s.Commit(testContext, c, agentlog.ReadBatch{SchemaVersion: 1, Source: src, Cursor: next, Coverage: c.Coverage})
	if err != nil || updated.Cursor.ContextRepair == nil {
		t.Fatal("repair progress not persisted", err)
	}
	var coverageID string
	if err := s.db.QueryRow(`SELECT id FROM coverage_history ORDER BY created_ns DESC LIMIT 1`).Scan(&coverageID); err != nil {
		t.Fatal(err)
	}
	payload := string(coverageJSON(t, s, coverageID))
	if strings.Contains(payload, "context_repair") || strings.Contains(payload, "model_") || strings.Contains(payload, "qoder_links") || strings.Contains(payload, "trae_") {
		t.Fatal("local repair state leaked to upload contract")
	}
}

func TestRepeatedEvidenceAndRotation(t *testing.T) {
	body := lines(1)
	src := source(t, body+strings.Replace(body, "01:00:00", "01:00:01", 1))
	s := openStore(t, tempDir(t), DefaultLimits())
	c := collect(t, s, src)
	v := status(t, s)
	if v.LogicalEvents != 1 || v.Evidence != 2 {
		t.Fatal(v)
	}
	if e := os.Rename(src.Path, src.Path+".old"); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(src.Path, []byte(body), 0600); e != nil {
		t.Fatal(e)
	}
	next := collect(t, s, src)
	v = status(t, s)
	if next.Cursor.Generation != c.Cursor.Generation+1 || next.Coverage.Status != "partial" || v.LogicalEvents != 1 || v.Evidence != 3 {
		t.Fatalf("%+v %+v", next, v)
	}
	collect(t, s, src)
	if status(t, s).Evidence != 3 {
		t.Fatal("poll duplicated evidence")
	}
}

func TestHalfLineSurvivesRestart(t *testing.T) {
	body := lines(1)
	src := source(t, body[:len(body)-1])
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	c := collect(t, s, src)
	if c.Cursor.Offset != 0 || status(t, s).LogicalEvents != 0 {
		t.Fatal(c)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	f, e := os.OpenFile(src.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if e != nil {
		t.Fatal(e)
	}
	_, e = f.WriteString("\n")
	f.Close()
	if e != nil {
		t.Fatal(e)
	}
	c = collect(t, s, src)
	if c.Cursor.Offset != int64(len(body)) || status(t, s).LogicalEvents != 1 {
		t.Fatal(c)
	}
}

func TestStaleCommitAndMalformedBatchRollback(t *testing.T) {
	src := source(t, lines(2))
	s := openStore(t, tempDir(t), DefaultLimits())
	b, e := agentlog.ReadIncremental(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0))
	if e != nil {
		t.Fatal(e)
	}
	c, e := s.Commit(testContext, Checkpoint{}, b)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Commit(testContext, Checkpoint{}, b); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	b.Events[1].SourceID = strings.Repeat("0", 64)
	if _, e = s.Commit(testContext, c, b); !errors.Is(e, ErrInvalid) {
		t.Fatal(e)
	}
	got, e := s.Checkpoint(testContext, src.ID)
	if e != nil || got.Revision != c.Revision || status(t, s).LogicalEvents != 2 {
		t.Fatal(got, e)
	}
}

func TestCapacityPreservesCursorAndExplicitStatus(t *testing.T) {
	l := DefaultLimits()
	l.LogicalEvents = 2
	src := source(t, lines(3))
	s := openStore(t, tempDir(t), l)
	if _, e := s.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0)); !errors.Is(e, ErrCapacity) {
		t.Fatal(e)
	}
	c, e := s.Checkpoint(testContext, src.ID)
	v := status(t, s)
	if e != nil || c.Revision != 0 || v.LogicalEvents != 0 || v.Queued != 0 || v.IntakeCode != "aidr_store_capacity" {
		t.Fatalf("%+v %+v %v", c, v, e)
	}
	if e = os.WriteFile(src.Path, []byte(lines(2)), 0600); e != nil {
		t.Fatal(e)
	}
	collect(t, s, src)
	if status(t, s).IntakeCode != "" {
		t.Fatal("successful intake did not clear pressure")
	}
}

func TestPrepareEmptyThenEnqueue(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	if b, err := s.Prepare(testContext, 500, 1<<20); err != nil || b != nil {
		t.Fatal(b, err)
	}
	ctx, cancel := context.WithCancel(testContext)
	cancel()
	if _, err := s.Prepare(ctx, 500, 1<<20); !errors.Is(err, context.Canceled) {
		t.Fatal("empty queue ignored cancellation", err)
	}
	collect(t, s, source(t, lines(1)))
	b, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || b == nil {
		t.Fatal("new data not ready immediately", err)
	}
	if err = s.Acknowledge(testContext, b.ID, b.Digest); err != nil {
		t.Fatal(err)
	}
	if b, err = s.Prepare(testContext, 500, 1<<20); err != nil || b != nil {
		t.Fatal("acknowledged queue not empty", b, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Prepare(testContext, 500, 1<<20); err == nil {
		t.Fatal("closed database returned empty success")
	}
}

func TestBatchReplayACKAndRetention(t *testing.T) {
	src := source(t, lines(6))
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	c := collect(t, s, src)
	b, e := s.Prepare(testContext, 3, 1<<20)
	if e != nil || b == nil {
		t.Fatal(e)
	}
	if e = s.Acknowledge(testContext, b.ID, strings.Repeat("0", 64)); !errors.Is(e, ErrBatchConflict) {
		t.Fatal(e)
	}
	if n, e := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); e != nil || n != 0 {
		t.Fatal("unacknowledged data removed", n, e)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	again, e := s.Prepare(testContext, 500, 1<<20)
	if e != nil || again.ID != b.ID || string(again.Payload) != string(b.Payload) {
		t.Fatal("batch changed across restart", e)
	}
	if e = s.Acknowledge(testContext, b.ID, b.Digest); e != nil {
		t.Fatal(e)
	}
	if e = s.Acknowledge(testContext, b.ID, b.Digest); e != nil {
		t.Fatal("last receipt not idempotent", e)
	}
	n, e := s.Prune(testContext, time.Now().Add(30*24*time.Hour))
	if e != nil || n != 3 {
		t.Fatal(n, e)
	}
	v := status(t, s)
	if v.LogicalEvents != 3 || v.EvictedPayloads != 0 || v.RetainedPayloads != 3 || v.Queued != 4 {
		t.Fatal(v)
	}
	current, _ := s.Checkpoint(testContext, src.ID)
	if current.Cursor.Offset != c.Cursor.Offset || current.Coverage.Status != c.Coverage.Status {
		t.Fatal("history pruning changed intake coverage")
	}
	// New generation replays acknowledged logical IDs, but no new event upload.
	os.Rename(src.Path, src.Path+".old")
	os.WriteFile(src.Path, []byte(lines(6)), 0600)
	collect(t, s, src)
	v = status(t, s)
	if v.LogicalEvents != 3 || v.Evidence != 6 || v.EvictedPayloads != 0 {
		t.Fatal(v)
	}
}

func TestUnavailableSourceCoverageAndBoundedBatch(t *testing.T) {
	src := source(t, "")
	os.Remove(src.Path)
	s := openStore(t, tempDir(t), DefaultLimits())
	c := collect(t, s, src)
	if c.Coverage.Status != "unavailable" || c.Cursor.SchemaVersion != 0 {
		t.Fatal(c)
	}
	var before, after int64
	if e := s.db.QueryRow(`SELECT total_changes()`).Scan(&before); e != nil {
		t.Fatal(e)
	}
	next := collect(t, s, src)
	if e := s.db.QueryRow(`SELECT total_changes()`).Scan(&after); e != nil {
		t.Fatal(e)
	}
	if next.Revision != c.Revision || before != after {
		t.Fatalf("unchanged collection wrote database: revision %d -> %d, changes %d -> %d", c.Revision, next.Revision, before, after)
	}
	unchanged, err := agentlog.ReadIncremental(testContext, src, c.Cursor, agentlog.DefaultBudget(), time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Commit(testContext, Checkpoint{}, unchanged); !errors.Is(err, ErrConflict) {
		t.Fatal("unchanged batch bypassed revision check", err)
	}
	if _, err = s.db.Exec(`INSERT OR REPLACE INTO metadata(key,value) VALUES('intake_code','aidr_store_capacity')`); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	var failures int
	if err = s.db.QueryRow(`SELECT count(*) FROM metadata WHERE key='intake_code'`).Scan(&failures); err != nil || failures != 0 {
		t.Fatal("successful unchanged collection did not clear intake failure", failures, err)
	}
	if status(t, s).Queued != 1 {
		t.Fatal("unchanged coverage grows outbox")
	}
	b, e := s.Prepare(testContext, 500, 1024)
	if e != nil && e.Error() != "aidr_store_batch_limit" {
		t.Fatal(e)
	}
	if b != nil && len(b.Payload) > 1024 {
		t.Fatal("batch byte limit")
	}
	if e = os.WriteFile(src.Path, []byte(lines(1)), 0600); e != nil {
		t.Fatal(e)
	}
	collect(t, s, src)
	if status(t, s).LogicalEvents != 1 {
		t.Fatal("reappearing source not consumed")
	}
}

func TestTenThousandEventsAndPagination(t *testing.T) {
	src := source(t, lines(10000))
	s := openStore(t, tempDir(t), DefaultLimits())
	for i := 0; i < 100; i++ {
		c := collect(t, s, src)
		if c.Cursor.Offset == int64(len(lines(10000))) {
			break
		}
	}
	v := status(t, s)
	if v.LogicalEvents != 10000 || v.Evidence != 10000 {
		t.Fatal(v)
	}
	seen := map[string]bool{}
	after := ""
	for {
		p, e := s.Events(testContext, after, 137)
		if e != nil {
			t.Fatal(e)
		}
		if len(p.Events) == 0 {
			break
		}
		for _, raw := range p.Events {
			var event agentlog.Event
			json.Unmarshal(raw, &event)
			if seen[event.CallID] {
				t.Fatal("duplicate logical call")
			}
			seen[event.CallID] = true
		}
		after = p.Next
	}
	for i := 0; i < 10000; i++ {
		if !seen[fmt.Sprintf("call-%d", i)] {
			t.Fatal("missing expected call", i)
		}
	}
	uploaded := 0
	for {
		b, e := s.Prepare(testContext, 500, 1<<20)
		if e != nil {
			t.Fatal(e)
		}
		if b == nil {
			break
		}
		if len(b.Payload) > 1<<20 {
			t.Fatal("oversized batch")
		}
		var envelope Envelope
		json.Unmarshal(b.Payload, &envelope)
		if len(envelope.Records) > 500 {
			t.Fatal("too many records")
		}
		for _, r := range envelope.Records {
			if r.Kind == "event" {
				uploaded++
			}
		}
		if e = s.Acknowledge(testContext, b.ID, b.Digest); e != nil {
			t.Fatal(e)
		}
	}
	if uploaded != 10000 || status(t, s).Queued != 0 {
		t.Fatal(uploaded, status(t, s))
	}
}

func TestExclusiveWriterAndPrivateDirectory(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	if other, e := Open(dir, DefaultLimits()); e == nil {
		other.Close()
		t.Fatal("concurrent writer admitted")
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	s.Close()
	if e := os.Chmod(dir, 0755); e != nil {
		t.Fatal(e)
	}
	if other, e := Open(dir, DefaultLimits()); e == nil {
		other.Close()
		t.Fatal("non-private directory accepted")
	}
}

func TestSQLitePageQuotaRollback(t *testing.T) {
	l := DefaultLimits()
	l.DatabaseBytes = 1 << 20
	s := openStore(t, tempDir(t), l)
	src := source(t, lines(500))
	_, e := s.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0))
	if !errors.Is(e, ErrCapacity) {
		t.Fatalf("expected SQLite quota failure, got %v", e)
	}
	c, e := s.Checkpoint(testContext, src.ID)
	if e != nil || c.Revision != 0 {
		t.Fatal(c, e)
	}
	v := status(t, s)
	if v.LogicalEvents != 0 || v.DatabaseBytes > l.DatabaseBytes {
		t.Fatal(v)
	}
	var integrity string
	if e = s.db.QueryRow(`PRAGMA integrity_check`).Scan(&integrity); e != nil || integrity != "ok" {
		t.Fatal(integrity, e)
	}
}

func TestConflictingLogicalContentAndCanceledWrite(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	src := source(t, lines(1))
	b, e := agentlog.ReadIncremental(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0))
	if e != nil {
		t.Fatal(e)
	}
	c, e := s.Commit(testContext, Checkpoint{}, b)
	if e != nil {
		t.Fatal(e)
	}
	b.Events[0].Tool = "DifferentTool"
	if _, e = s.Commit(testContext, c, b); !errors.Is(e, ErrBatchConflict) {
		t.Fatal(e)
	}
	ctx, cancel := context.WithCancel(testContext)
	cancel()
	if _, e = s.Commit(ctx, c, b); e == nil {
		t.Fatal("canceled write committed")
	}
	if status(t, s).LogicalEvents != 1 {
		t.Fatal("rollback failed")
	}
}

func TestLargePositionsPersistWithoutFloatConversion(t *testing.T) {
	src := source(t, lines(1))
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	b, e := agentlog.ReadIncremental(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0))
	if e != nil {
		t.Fatal(e)
	}
	const offset int64 = 9007199254740993
	b.Cursor.Offset = offset
	b.Events[0].RecordOffset = offset
	b.Events[0].SourceSeq = offset
	if _, e = s.Commit(testContext, Checkpoint{}, b); e != nil {
		t.Fatal(e)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	c, e := s.Checkpoint(testContext, src.ID)
	if e != nil || c.Cursor.Offset != offset {
		t.Fatal(c, e)
	}
	p, e := s.Events(testContext, "", 1)
	if e != nil {
		t.Fatal(e)
	}
	if !strings.Contains(string(p.Events[0]), `"record_offset":"9007199254740993"`) {
		t.Fatal("lost integer precision")
	}
}

// A tiny durable receiver simulation, independent of localstore. It applies
// each record ID once and rejects an existing batch ID with different content.
type mockReceiver struct {
	Batches map[string]string `json:"batches"`
	Records map[string]string `json:"records"`
}

func receiveMock(path string, b UploadBatch) (mockReceiver, error) {
	v := mockReceiver{map[string]string{}, map[string]string{}}
	if raw, e := os.ReadFile(path); e == nil {
		if e = json.Unmarshal(raw, &v); e != nil {
			return v, e
		}
	} else if !os.IsNotExist(e) {
		return v, e
	}
	if hash(b.Payload) != b.Digest || b.ID != b.Digest {
		return v, ErrBatchConflict
	}
	if old, ok := v.Batches[b.ID]; ok {
		if old != b.Digest {
			return v, ErrBatchConflict
		}
		return v, nil
	}
	var envelope Envelope
	if e := json.Unmarshal(b.Payload, &envelope); e != nil {
		return v, e
	}
	for _, r := range envelope.Records {
		digest := hash(r.Payload)
		if old, ok := v.Records[r.ID]; ok && old != digest {
			return v, ErrBatchConflict
		}
		v.Records[r.ID] = digest
	}
	v.Batches[b.ID] = b.Digest
	f, e := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if e != nil {
		return v, e
	}
	defer f.Close()
	if e = json.NewEncoder(f).Encode(v); e != nil {
		return v, e
	}
	return v, f.Sync()
}

// Executed only in a child process. The parent SIGKILLs at a named boundary.
func TestCrashWorker(t *testing.T) {
	stage := os.Getenv("AIDR_TEST_CRASH_STAGE")
	if stage == "" {
		return
	}
	dir := os.Getenv("AIDR_TEST_STATE")
	path := os.Getenv("AIDR_TEST_SOURCE")
	s, e := Open(dir, DefaultLimits())
	if e != nil {
		t.Fatal(e)
	}
	src, e := agentlog.NewSource("claude", filepath.Dir(path), path)
	if e != nil {
		t.Fatal(e)
	}
	stop := func() {
		fmt.Println("CRASH_BOUNDARY_READY")
		for {
			time.Sleep(time.Hour)
		}
	}
	s.hook = func(at string) {
		if at == stage {
			stop()
		}
	}
	crawler, e := s.NewCrawler(src.Agent, src.Root)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = crawler.Step(testContext, 64, 1000, time.Second); e != nil {
		t.Fatal(e)
	}
	if _, e = crawler.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0)); e != nil {
		t.Fatal(e)
	}
	if stage == "revalidated_before_flush" {
		if _, e = s.db.Exec(`UPDATE discovery_files SET pending=1,read_ns=0`); e != nil {
			t.Fatal(e)
		}
		if _, e = crawler.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0)); e != nil {
			t.Fatal(e)
		}
		if len(crawler.readProgress) != 1 {
			t.Fatal("unchanged revalidation was not batched")
		}
		stop()
	}
	if stage == "received_before_ack" {
		b, e := s.Prepare(testContext, 500, 1<<20)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = receiveMock(filepath.Join(dir, "receiver-state.json"), *b); e != nil {
			t.Fatal(e)
		}
		// Simulated receiver's durable copy is independent of local SQLite.
		f, e := os.OpenFile(filepath.Join(dir, "receiver.json"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
		if e != nil {
			t.Fatal(e)
		}
		if e = json.NewEncoder(f).Encode(b); e != nil {
			t.Fatal(e)
		}
		if e = f.Sync(); e != nil {
			t.Fatal(e)
		}
		f.Close()
		stop()
	}
	t.Fatal("crash boundary not reached")
}

func TestSIGKILLRecoveryBoundaries(t *testing.T) {
	for _, stage := range []string{"after_read", "before_commit", "after_commit", "received_before_ack", "revalidated_before_flush"} {
		t.Run(stage, func(t *testing.T) {
			dir := tempDir(t)
			src := source(t, lines(12))
			cmd := exec.Command(os.Args[0], "-test.run=^TestCrashWorker$")
			cmd.Env = append(os.Environ(), "AIDR_TEST_CRASH_STAGE="+stage, "AIDR_TEST_STATE="+dir, "AIDR_TEST_SOURCE="+src.Path)
			stdout, e := cmd.StdoutPipe()
			if e != nil {
				t.Fatal(e)
			}
			cmd.Stderr = os.Stderr
			if e = cmd.Start(); e != nil {
				t.Fatal(e)
			}
			defer cmd.Process.Kill()
			ready := make(chan string, 1)
			go func() { line, _ := bufio.NewReader(stdout).ReadString('\n'); ready <- line }()
			select {
			case line := <-ready:
				if strings.TrimSpace(line) != "CRASH_BOUNDARY_READY" {
					cmd.Process.Kill()
					cmd.Wait()
					t.Fatal("worker failed", line)
				}
			case <-time.After(20 * time.Second):
				cmd.Process.Kill()
				cmd.Wait()
				t.Fatal("worker timeout")
			}
			if e = cmd.Process.Kill(); e != nil {
				t.Fatal(e)
			}
			if e = cmd.Wait(); e == nil {
				t.Fatal("expected killed process")
			}
			s := openStore(t, dir, DefaultLimits())
			v := status(t, s)
			if v.RecoveryCode != "aidr_store_unclean_shutdown" {
				t.Fatal(v)
			}
			committed := stage == "after_commit" || stage == "received_before_ack" || stage == "revalidated_before_flush"
			if committed && v.LogicalEvents != 12 || !committed && v.LogicalEvents != 0 {
				t.Fatal(v)
			}
			if stage == "revalidated_before_flush" {
				var pending int
				if e = s.db.QueryRow(`SELECT pending FROM discovery_files WHERE id=?`, src.ID).Scan(&pending); e != nil || pending != 1 {
					t.Fatal("killed revalidation skipped pending work", pending, e)
				}
			}
			collect(t, s, src)
			if status(t, s).LogicalEvents != 12 {
				t.Fatal("recovery lost or duplicated records")
			}
			if stage == "received_before_ack" {
				raw, e := os.ReadFile(filepath.Join(dir, "receiver.json"))
				if e != nil {
					t.Fatal(e)
				}
				var received UploadBatch
				json.Unmarshal(raw, &received)
				retry, e := s.Prepare(testContext, 500, 1<<20)
				if e != nil {
					t.Fatal(e)
				}
				if retry.ID != received.ID || string(retry.Payload) != string(received.Payload) {
					t.Fatal("retry differs from receiver durable copy")
				}
				for n := 0; n < 3; n++ {
					remote, e := receiveMock(filepath.Join(dir, "receiver-state.json"), *retry)
					if e != nil || len(remote.Batches) != 1 || len(remote.Records) != 13 {
						t.Fatal("receiver duplicated or lost records", remote, e)
					}
				}
				if e = s.Acknowledge(testContext, retry.ID, retry.Digest); e != nil {
					t.Fatal(e)
				}
				if status(t, s).AcknowledgedSequence == "0" {
					t.Fatal("ACK not durable")
				}
			}
		})
	}
}

func TestCodexMetadataRepairKeepsOriginalEvidence(t *testing.T) {
	data, err := os.ReadFile("../agentlog/testdata/codex-0.160.1.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	start := strings.IndexByte(string(data), '\n') + 1
	metadata := "{\"timestamp\":\"2026-09-23T01:00:00Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"additional_tools\",\"tools\":[]}}\n"
	body := string(data[:start]) + metadata + string(data[start:])
	file := source(t, body)
	src, err := agentlog.NewSource("codex", file.Root, file.Path)
	if err != nil {
		t.Fatal(err)
	}
	policy := &agentlog.AuditPolicy{MessageSchema: 1, Enabled: true, Version: "2", Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
	batch, err := agentlog.ReadWithPolicy(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0), policy)
	if err != nil {
		t.Fatal(err)
	}
	var old []agentlog.Event
	for _, e := range batch.Events {
		if e.Kind == "tool_call" || e.Kind == "tool_result" {
			e.SessionID = ""
			e.LogicalEventID = hash([]byte("old" + e.LogicalEventID))
			e.LogicalCallID = hash([]byte("old" + e.LogicalCallID))
			old = append(old, e)
		}
	}
	batch.Events = old
	batch.Cursor.Session = ""
	batch.Cursor.ContextRepairVersion = 3
	encoded, _ := json.Marshal(metadata)
	batch.Cursor.RecoveryGaps = []agentlog.Gap{{Start: int64(start), End: int64(start + len(metadata)), Reason: "aidr_log_context_invalidated", EvidenceDigest: hash(append(encoded, 0))}}
	store := openStore(t, tempDir(t), DefaultLimits())
	store.policy = policy
	previous, err := store.Checkpoint(testContext, src.ID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.Commit(testContext, previous, batch); err != nil {
		t.Fatal(err)
	}
	budget := agentlog.DefaultBudget()
	budget.Events = 1
	for i := 0; i < 10; i++ {
		checkpoint, err := store.Collect(testContext, src, budget, time.Unix(0, 0))
		if err != nil {
			t.Fatal(err)
		}
		if checkpoint.Cursor.ContextRepairVersion == 5 {
			break
		}
	}
	var count int
	if err := store.db.QueryRow(`SELECT count(*) FROM logical_events`).Scan(&count); err != nil || count != 7 {
		t.Fatalf("expected 2 original and 5 recovered events: %d %v", count, err)
	}
	for _, e := range old {
		var raw string
		if err := store.db.QueryRow(`SELECT payload FROM logical_events WHERE id=?`, e.LogicalEventID).Scan(&raw); err != nil {
			t.Fatal(err)
		}
		var kept agentlog.Event
		json.Unmarshal([]byte(raw), &kept)
		if kept.SessionID != "" {
			t.Fatal("rewrote original evidence")
		}
	}
	if _, err := store.Collect(testContext, src, budget, time.Unix(0, 0)); err != nil {
		t.Fatal(err)
	}
}

func TestIntakeSinceSurvivesRestartAndNewAcknowledgement(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	start := time.Now().UTC().Add(-72 * time.Hour)
	got, err := s.IntakeSince(testContext, start)
	if err != nil || !got.Equal(start) {
		t.Fatal(got, err)
	}
	if _, err = s.db.Exec(`INSERT INTO metadata(key,value) VALUES('last_ack_at',?)`, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, DefaultLimits())
	got, err = s.IntakeSince(testContext, time.Now().Add(-24*time.Hour))
	if err != nil || !got.Equal(start) {
		t.Fatal("restart moved intake floor", got, err)
	}
	// A file discovered after restart still admits events from the interruption.
	body := strings.ReplaceAll(lines(1), "2026-09-23T01:00:00Z", start.Add(time.Hour).Format(time.RFC3339Nano))
	src := source(t, body)
	if _, err = s.Collect(testContext, src, agentlog.DefaultBudget(), got); err != nil {
		t.Fatal(err)
	}
	var n int
	if err = s.db.QueryRow(`SELECT count(*) FROM logical_events`).Scan(&n); err != nil || n != 1 {
		t.Fatal("lost late-discovered file", n, err)
	}
}
