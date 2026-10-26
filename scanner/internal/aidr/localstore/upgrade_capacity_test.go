package localstore

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestFullLegacyUpgradePreservesPendingBatch(t *testing.T) {
	for _, confirmed := range []bool{true, false} {
		t.Run(fmt.Sprint("confirmed_history=", confirmed), func(t *testing.T) {
			dir := tempDir(t)
			limits := DefaultLimits()
			limits.DatabaseBytes = 2 << 20
			s := openStore(t, dir, limits)
			src := source(t, lines(1))
			cp := collect(t, s, src)
			// Its ACK frees room to freeze subsequent batches in the full queue.
			if _, err := s.db.Exec(`INSERT INTO outbox(kind,record_id,payload,created_ns) VALUES('event','pending-large',?,0)`, `{"data":"`+strings.Repeat("p", 32768)+`"}`); err != nil {
				t.Fatal(err)
			}
			frozen, err := s.Prepare(testContext, 500, 1<<20)
			if err != nil || frozen == nil {
				t.Fatal(frozen, err)
			}
			for _, name := range []string{"sources_revision", "sources_discovery", "logical_events_release", "coverage_release", "evidence_release", "logical_events_retention", "logical_events_retention_source", "coverage_source", "coverage_retention"} {
				if _, err = s.db.Exec("DROP INDEX " + name); err != nil {
					t.Fatal(err)
				}
			}
			raw := `{"source_id":"history","observed_at":"2026-10-25T00:00:00Z","data":"` + strings.Repeat("x", 8192) + `"}`
			count := 0
			for ; count < 10000; count++ {
				if confirmed {
					_, err = s.db.Exec(`INSERT INTO logical_events(id,content_hash,payload,created_ns,acked_ns) VALUES(?,?,?,0,?)`, fmt.Sprint(count), "hash", raw, time.Now().UnixNano())
				} else {
					_, err = s.db.Exec(`INSERT INTO outbox(kind,record_id,payload,created_ns) VALUES('event',?,?,0)`, fmt.Sprint(count), raw)
				}
				if err != nil {
					break
				}
			}
			if !errors.Is(storageError(err), ErrCapacity) || count == 0 {
				t.Fatal("fixture not full", count, err)
			}
			if err = s.Close(); err != nil {
				t.Fatal(err)
			}
			s = openStore(t, dir, limits)
			if confirmed && !s.maintenanceIndexed {
				t.Fatal("released space did not permit indexes")
			}
			if !confirmed && s.maintenanceIndexed {
				t.Fatal("fixture did not exercise index deferral")
			}
			again, err := s.Prepare(testContext, 500, 1<<20)
			if err != nil || again == nil || again.ID != frozen.ID || !bytes.Equal(again.Payload, frozen.Payload) {
				t.Fatal("frozen batch changed", err)
			}
			restored, err := s.Checkpoint(testContext, src.ID)
			a, _ := json.Marshal(cp)
			b, _ := json.Marshal(restored)
			if err != nil || !bytes.Equal(a, b) {
				t.Fatal("checkpoint changed", err)
			}
			if err = s.Acknowledge(testContext, frozen.ID, "wrong"); err == nil {
				t.Fatal("invalid ACK accepted")
			}
			if err = s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil {
				t.Fatal("cannot drain frozen batch", err)
			}
			if !confirmed {
				acknowledgeAll(t, s)
			}
			state := status(t, s)
			if state.Queued != 0 {
				t.Fatal("queue did not drain", state.Queued)
			}
			crawler, err := s.NewCrawler(src.Agent, src.Root)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = crawler.Step(testContext, 64, 1000, time.Second); err != nil {
				crawler.Close()
				t.Fatal("discovery requires deferred indexes", err)
			}
			crawler.Close()
			if err = s.Close(); err != nil {
				t.Fatal(err)
			}
			s = openStore(t, dir, limits)
			if !s.maintenanceIndexed {
				t.Fatal("indexes not retried after space recovered")
			}
			if state = status(t, s); state.Queued != 0 {
				t.Fatal("ACK lost across restart", state.Queued)
			}
		})
	}
}
