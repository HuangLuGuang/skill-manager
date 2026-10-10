package localstore

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"
	"time"
)

func TestACKReleasesOnlyConfirmedBodiesAndPreservesResume(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	src := source(t, timedLines(2, time.Now().Add(-time.Hour)))
	cp := collect(t, s, src)
	b, err := s.Prepare(testContext, 1, 1<<20)
	if err != nil || b == nil {
		t.Fatal(err)
	}
	if err = s.Acknowledge(testContext, b.ID, "invalid"); err == nil {
		t.Fatal("invalid ACK accepted")
	}
	if status(t, s).RetainedPayloads != 2 {
		t.Fatal("invalid ACK released payload")
	}
	// A failure after body release must roll back the entire ACK transaction.
	if _, err = s.db.Exec(`CREATE TRIGGER fail_ack BEFORE INSERT ON metadata WHEN NEW.key='last_ack_id' BEGIN SELECT RAISE(ABORT,'test ACK failure'); END`); err != nil {
		t.Fatal(err)
	}
	if err = s.Acknowledge(testContext, b.ID, b.Digest); err == nil || status(t, s).RetainedPayloads != 2 {
		t.Fatal("failed ACK transaction released bodies", err)
	}
	retry, err := s.Prepare(testContext, 1, 1<<20)
	if err != nil || !bytes.Equal(retry.Payload, b.Payload) {
		t.Fatal("failed ACK changed frozen upload", err)
	}
	if _, err = s.db.Exec(`DROP TRIGGER fail_ack`); err != nil {
		t.Fatal(err)
	}
	if err = s.Acknowledge(testContext, b.ID, b.Digest); err != nil {
		t.Fatal(err)
	}
	v := status(t, s)
	if v.LogicalEvents != 2 || v.RetainedPayloads != 1 || v.EvictedPayloads != 1 || v.Queued != 2 {
		t.Fatal(v)
	}
	var count int
	if err = s.db.QueryRow(`SELECT count(*) FROM evidence WHERE payload IS NOT NULL`).Scan(&count); err != nil || count != 1 {
		t.Fatal("unconfirmed evidence lost", count, err)
	}
	pending, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	again, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || !bytes.Equal(pending.Payload, again.Payload) || pending.Digest != again.Digest {
		t.Fatal("pending batch changed after restart", err)
	}
	restored, err := s.Checkpoint(testContext, src.ID)
	a, _ := json.Marshal(cp)
	c, _ := json.Marshal(restored)
	if err != nil || !bytes.Equal(a, c) {
		t.Fatal("ACK changed parser checkpoint", err)
	}
	acknowledgeAll(t, s)
	if status(t, s).RetainedPayloads != 0 || status(t, s).LogicalEvents != 2 {
		t.Fatal("confirmed bodies retained or identities lost")
	}
	// Rotating an already-confirmed source cannot resurrect its body or upload it again.
	raw, _ := os.ReadFile(src.Path)
	os.Rename(src.Path, src.Path+".old")
	os.WriteFile(src.Path, raw, 0600)
	collect(t, s, src)
	if status(t, s).LogicalEvents != 2 || status(t, s).RetainedPayloads != 0 {
		t.Fatal("rotation resurrected confirmed events")
	}
	if n, err := s.Prune(testContext, time.Now().Add(30*24*time.Hour)); err != nil || n != 2 {
		t.Fatal("identity retirement failed", n, err)
	}
}

func TestLegacyACKReleasePreservesObservationMetadata(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	at := time.Now().Add(-time.Hour).UTC().Truncate(time.Second)
	src := source(t, timedLines(1, at))
	cp := collect(t, s, src)
	// Recreate a pre-upgrade ACK: only the confirmed archive remains locally.
	if _, err := s.db.Exec(`UPDATE logical_events SET acked_ns=?; UPDATE coverage_history SET acked_ns=?; DELETE FROM outbox; DELETE FROM metadata WHERE key='ack_payload_release_version'; ALTER TABLE logical_events DROP COLUMN source_id; ALTER TABLE logical_events DROP COLUMN observed_at`, time.Now().UnixNano(), time.Now().UnixNano()); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	var sourceID, observed string
	if err := s.db.QueryRow(`SELECT source_id,observed_at FROM logical_events`).Scan(&sourceID, &observed); err != nil || sourceID != src.ID || observed != at.Format(time.RFC3339Nano) {
		t.Fatal(sourceID, observed, err)
	}
	if status(t, s).RetainedPayloads != 0 || status(t, s).LogicalEvents != 1 {
		t.Fatal(status(t, s))
	}
	got, _ := s.Checkpoint(testContext, src.ID)
	if got.Cursor.Offset != cp.Cursor.Offset || got.Revision != cp.Revision {
		t.Fatal("migration changed checkpoint")
	}
}
