package localstore

import (
	"bytes"
	"errors"
	"os"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"testing"
	"time"
)

func acknowledgeAll(t *testing.T, s *Store) {
	t.Helper()
	for {
		b, err := s.Prepare(testContext, 500, 1<<20)
		if err != nil {
			t.Fatal(err)
		}
		if b == nil {
			return
		}
		if err = s.Acknowledge(testContext, b.ID, b.Digest); err != nil {
			t.Fatal(err)
		}
	}
}
func timedLines(n int, at time.Time) string {
	return strings.ReplaceAll(lines(n), "2026-09-23T01:00:00Z", at.UTC().Format(time.RFC3339Nano))
}

func TestRetirementRecoversAllIdentityBudgetsAndSurvivesRestart(t *testing.T) {
	limits := DefaultLimits()
	limits.LogicalEvents = 2
	limits.Evidence = 4
	limits.Sources = 1
	dir := tempDir(t)
	s := openStore(t, dir, limits)
	oldTime := time.Now().Add(-24 * time.Hour).UTC()
	original := timedLines(2, oldTime)
	src := source(t, original)
	old := collect(t, s, src)
	extra := strings.ReplaceAll(timedLines(1, oldTime.Add(time.Hour)), "call-0", "extra-call")
	if err := os.WriteFile(src.Path, []byte(original+extra), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0)); !errors.Is(err, ErrCapacity) {
		t.Fatal("quota not enforced", err)
	}
	before, _ := s.Checkpoint(testContext, src.ID)
	if before.Revision != old.Revision || before.Cursor.Offset != old.Cursor.Offset {
		t.Fatal("failed intake advanced", before)
	}
	if err := os.WriteFile(src.Path, []byte(original), 0600); err != nil {
		t.Fatal(err)
	}
	acknowledgeAll(t, s)
	if n, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil || n != 2 {
		t.Fatal(n, err)
	}
	v := status(t, s)
	if v.LogicalEvents != 0 || v.Evidence != 0 || v.Sources != 0 || v.RetiredThrough == "" {
		t.Fatal(v)
	}
	s.Close()
	s = openStore(t, dir, limits)
	// Rediscovery/rewind to the original bytes must produce a visible gap, no event.
	c := collect(t, s, src)
	if c.Coverage.Filtered != 2 || c.Coverage.Status != "partial" || !strings.Contains(strings.Join(c.Coverage.Reasons, ","), retirementReason) {
		t.Fatal(c)
	}
	stable := collect(t, s, src)
	if stable.Coverage.Status != "partial" || !strings.Contains(strings.Join(stable.Cursor.Gaps, ","), retirementReason) {
		t.Fatal("retirement gap forgotten", stable)
	}
	c = stable
	if c.Revision <= old.Revision || status(t, s).LogicalEvents != 0 {
		t.Fatal(c, status(t, s))
	}
	if _, err := s.Commit(testContext, old, agentlog.ReadBatch{SchemaVersion: 1, Source: src, Cursor: old.Cursor, Coverage: old.Coverage}); !errors.Is(err, ErrConflict) {
		t.Fatal("stale cursor admitted", err)
	}
	// Rotation mixes historical bytes and new current-window events.
	if err := os.Rename(src.Path, src.Path+".old"); err != nil {
		t.Fatal(err)
	}
	fresh := strings.ReplaceAll(timedLines(1, oldTime.Add(time.Hour)), "call-0", "new-call")
	if err := os.WriteFile(src.Path, []byte(original+fresh), 0600); err != nil {
		t.Fatal(err)
	}
	c = collect(t, s, src)
	if c.Coverage.Filtered != 2 || status(t, s).LogicalEvents != 1 || status(t, s).Evidence != 1 {
		t.Fatal(c, status(t, s))
	}
	acknowledgeAll(t, s)
	// A new source can reuse the finite source slot once the previous one is idle.
	if _, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil {
		t.Fatal(err)
	}
	other := source(t, timedLines(1, oldTime.Add(2*time.Hour)))
	collect(t, s, other)
	if status(t, s).LogicalEvents != 1 {
		t.Fatal(status(t, s))
	}
}

func TestRetirementKeepsPendingFrozenAndConflictingIdentities(t *testing.T) {
	limits := DefaultLimits()
	limits.LogicalEvents = 2
	limits.Evidence = 2
	s := openStore(t, tempDir(t), limits)
	src := source(t, lines(2))
	c := collect(t, s, src)
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if n, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil || n != 0 {
		t.Fatal(n, err)
	}
	again, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || !bytes.Equal(again.Payload, frozen.Payload) {
		t.Fatal("pending frozen changed", err)
	}
	batch, err := agentlog.ReadIncremental(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	batch.Cursor = c.Cursor
	batch.Events = batch.Events[:1]
	batch.Events[0].Tool = "ChangedTool"
	if _, err = s.Commit(testContext, c, batch); !errors.Is(err, ErrBatchConflict) {
		t.Fatal("pending collision accepted", err)
	}
	if status(t, s).LogicalEvents != 2 {
		t.Fatal(status(t, s))
	}
	if err = s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Commit(testContext, c, batch); !errors.Is(err, ErrBatchConflict) {
		t.Fatal("ACK identity mutated", err)
	}
}

func TestRetirementRepeatedCyclesKeepSQLiteReusable(t *testing.T) {
	limits := DefaultLimits()
	limits.DatabaseBytes = 1 << 20
	limits.LogicalEvents = 2
	limits.Evidence = 2
	limits.Sources = 1
	s := openStore(t, tempDir(t), limits)
	src := source(t, "")
	at := time.Now().Add(-24 * time.Hour)
	for i := 0; i < 40; i++ {
		at = at.Add(time.Minute)
		if err := os.WriteFile(src.Path, []byte(timedLines(2, at)), 0600); err != nil {
			t.Fatal(err)
		}
		collect(t, s, src)
		acknowledgeAll(t, s)
		if n, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil || n != 2 {
			t.Fatal(i, n, err)
		}
	}
	if v := status(t, s); v.DatabaseBytes >= limits.DatabaseBytes || v.LogicalEvents != 0 || v.Evidence != 0 {
		t.Fatal(v)
	}
}

func TestRetirementClampsAbnormalTimeAndPreservesRecentLateArrival(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	now := time.Now().UTC()
	// Simulate a legacy already-ACKed event whose observation time is recent,
	// despite an old ACK timestamp. It must not move admission close to now.
	abnormal := source(t, timedLines(1, now.Add(3*time.Minute)))
	collect(t, s, abnormal)
	first, err := s.Prepare(testContext, 1, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Acknowledge(testContext, first.ID, first.Digest); err != nil {
		t.Fatal(err)
	}
	if _, err = s.db.Exec(`UPDATE logical_events SET acked_ns=?`, now.Add(-30*24*time.Hour).UnixNano()); err != nil {
		t.Fatal(err)
	}
	pending := source(t, timedLines(1, now.Add(-40*24*time.Hour)))
	collect(t, s, pending)
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if n, err := s.Prune(testContext, now); err != nil || n != 1 {
		t.Fatal(n, err)
	}
	v := status(t, s)
	boundary, err := time.Parse(time.RFC3339Nano, v.RetiredThrough)
	if err != nil || boundary.After(now.Add(-s.limits.Retention)) || v.LogicalEvents != 1 {
		t.Fatal(v, err)
	}
	same, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || !bytes.Equal(frozen.Payload, same.Payload) {
		t.Fatal("pending data changed", err)
	}
	recent := source(t, timedLines(1, now.Add(-time.Hour)))
	c := collect(t, s, recent)
	if c.Coverage.Filtered != 0 || status(t, s).LogicalEvents != 2 {
		t.Fatal("normal recent late arrival rejected", c, status(t, s))
	}
	future := source(t, timedLines(1, now.Add(time.Hour)))
	c = collect(t, s, future)
	if c.Coverage.Filtered != 1 || !strings.Contains(strings.Join(c.Cursor.Gaps, ","), futureReason) || status(t, s).LogicalEvents != 2 {
		t.Fatal("future timestamp admitted", c, status(t, s))
	}
}

func TestRetiredSourceRediscoveryReachesStableCheckpoint(t *testing.T) {
	limits := DefaultLimits()
	limits.LogicalEvents = 1
	limits.Evidence = 4
	limits.Sources = 1
	s := openStore(t, tempDir(t), limits)
	src := source(t, lines(1))
	collect(t, s, src)
	acknowledgeAll(t, s)
	if _, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	collect(t, s, src) // Carry the durable gap into parser-generated coverage.
	before := status(t, s)
	for i := 0; i < 100; i++ {
		c := collect(t, s, src)
		if c.Cursor.Offset != int64(len(lines(1))) || c.Coverage.Status != "partial" {
			t.Fatal("checkpoint regressed", i, c)
		}
	}
	after := status(t, s)
	if after.Queued != before.Queued || after.CoverageRecords != before.CoverageRecords || after.Sources != 1 || after.LogicalEvents != 0 {
		t.Fatal(before, after)
	}
	acknowledgeAll(t, s)
	if _, err := s.Prune(testContext, time.Now()); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	if status(t, s).Queued != 0 {
		t.Fatal("stable acknowledged checkpoint requeued", status(t, s))
	}
}

func TestRetirementReclaimsMissingDiscoveryCatalogue(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	src := source(t, lines(1))
	collect(t, s, src)
	acknowledgeAll(t, s)
	if _, err := s.db.Exec(`INSERT INTO discovery_files(id,root_key,agent,root,path,mtime_ns,size,reason) VALUES(?,?,?,?,?,0,0,'aidr_log_source_missing')`, src.ID, "root", src.Agent, src.Root, src.Path); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`INSERT INTO discovery_dirs(root_key,path,reason) VALUES('root',?,'')`, src.Root); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`INSERT INTO discovery_dirs(root_key,path,reason) VALUES('root',?,'aidr_log_source_missing')`, src.Root+"/gone"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil {
		t.Fatal(err)
	}
	var files, dirs int
	if err := s.db.QueryRow(`SELECT (SELECT count(*) FROM discovery_files),(SELECT count(*) FROM discovery_dirs)`).Scan(&files, &dirs); err != nil || files != 0 || dirs != 1 {
		t.Fatal(files, dirs, err)
	}
}
