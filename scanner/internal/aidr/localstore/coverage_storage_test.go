package localstore

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"
)

func coverageJSON(t *testing.T, s *Store, id string) []byte {
	t.Helper()
	var raw []byte
	var encoding string
	if err := s.db.QueryRow(`SELECT payload,payload_encoding FROM coverage_history WHERE id=?`, id).Scan(&raw, &encoding); err != nil {
		t.Fatal(err)
	}
	if encoding == "json" {
		return raw
	}
	if encoding != "gzip" {
		t.Fatal(encoding)
	}
	r, err := gzip.NewReader(bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	decoded, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	return decoded
}

func TestFullLegacyCoverageArchiveReleasesConfirmedBodiesAndKeepsFrozenUpload(t *testing.T) {
	dir := tempDir(t)
	limits := DefaultLimits()
	limits.DatabaseBytes = 2 << 20
	s := openStore(t, dir, limits)
	src := source(t, lines(2))
	cp := collect(t, s, src)
	b, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || b == nil {
		t.Fatal(err)
	}
	var pendingID string
	if err := s.db.QueryRow(`SELECT id FROM coverage_history LIMIT 1`).Scan(&pendingID); err != nil {
		t.Fatal(err)
	}
	pending := coverageJSON(t, s, pendingID)
	if _, err := s.db.Exec(`UPDATE coverage_history SET payload=?,payload_encoding='json' WHERE id=?`, string(pending), pendingID); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`DROP INDEX coverage_release; ALTER TABLE coverage_history DROP COLUMN payload_encoding`); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(map[string]string{"synthetic": strings.Repeat("cursor-binding-", 3000)})
	var ids []string
	for i := 0; i < 100; i++ {
		id := fmt.Sprintf("legacy-%03d", i)
		_, err := s.db.Exec(`INSERT INTO coverage_history(id,source_id,payload,created_ns,acked_ns) VALUES(?,?,?,?,?)`, id, src.ID, string(raw), time.Now().UnixNano(), time.Now().UnixNano())
		if err != nil {
			if storageError(err) != ErrCapacity {
				t.Fatal(err)
			}
			break
		}
		ids = append(ids, id)
	}
	if len(ids) == 0 || len(ids) == 100 {
		t.Fatal("fixture did not exhaust storage")
	}
	before := status(t, s)
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, limits)
	after := status(t, s)
	if before.CoverageRecords != after.CoverageRecords || before.LogicalEvents != after.LogicalEvents || before.Evidence != after.Evidence || before.Queued != after.Queued || after.DatabaseBytes >= before.DatabaseBytes/2 {
		t.Fatal("migration lost history or failed to reclaim pages", before, after)
	}
	for _, id := range ids {
		var payload, encoding string
		if err := s.db.QueryRow(`SELECT payload,payload_encoding FROM coverage_history WHERE id=?`, id).Scan(&payload, &encoding); err != nil || payload != "" || encoding != "released" {
			t.Fatal("confirmed body not released", id, err)
		}
	}
	restored, err := s.Checkpoint(testContext, src.ID)
	a, _ := json.Marshal(cp)
	c, _ := json.Marshal(restored)
	if err != nil || !bytes.Equal(a, c) {
		t.Fatal("checkpoint changed", err)
	}
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || frozen == nil || !bytes.Equal(frozen.Payload, b.Payload) || frozen.Digest != b.Digest {
		t.Fatal("upload changed", err)
	}
	if err := s.Acknowledge(testContext, b.ID, "wrong"); err == nil {
		t.Fatal("invalid ACK accepted")
	}
	if err := s.Acknowledge(testContext, b.ID, b.Digest); err != nil {
		t.Fatal(err)
	}
	collect(t, s, source(t, lines(3)))
	if status(t, s).Queued == 0 {
		t.Fatal("intake did not resume")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, limits)
	for _, id := range ids {
		var payload, encoding string
		if err := s.db.QueryRow(`SELECT payload,payload_encoding FROM coverage_history WHERE id=?`, id).Scan(&payload, &encoding); err != nil || payload != "" || encoding != "released" {
			t.Fatal("repeat migration restored body", err)
		}
	}
}

func TestNewCoverageArchiveKeepsWireAndParserStateSeparate(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	src := source(t, lines(30))
	cp := collect(t, s, src)
	if len(cp.Cursor.CallTurns) == 0 {
		t.Fatal("parser call bindings were lost")
	}
	b, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	var envelope Envelope
	if err := json.Unmarshal(b.Payload, &envelope); err != nil {
		t.Fatal(err)
	}
	var checked bool
	for _, r := range envelope.Records {
		if r.Kind != "coverage" {
			continue
		}
		checked = true
		if bytes.Contains(r.Payload, []byte("call_turns")) {
			t.Fatal("parser cache leaked into coverage upload")
		}
		if !bytes.Equal(coverageJSON(t, s, r.ID), r.Payload) {
			t.Fatal("archive and upload differ")
		}
	}
	if !checked {
		t.Fatal("no coverage uploaded")
	}
}
