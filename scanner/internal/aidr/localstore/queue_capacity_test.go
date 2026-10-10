package localstore

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func TestNearlyFullStoreFreezesSmallerBatchAndKeepsACKContract(t *testing.T) {
	s, err := Open(tempDir(t), DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	raw, _ := json.Marshal(map[string]string{"synthetic": strings.Repeat("x", 16000)})
	for i := 0; i < 20; i++ {
		if _, err := s.db.Exec(`INSERT INTO outbox(kind,record_id,payload,created_ns) VALUES('event',?,?,0)`, fmt.Sprint(i), string(raw)); err != nil {
			t.Fatal(err)
		}
	}
	var pages, maximum int
	if err := s.db.QueryRow(`PRAGMA page_count`).Scan(&pages); err != nil {
		t.Fatal(err)
	}
	if err := s.db.QueryRow(fmt.Sprintf(`PRAGMA max_page_count=%d`, pages+10)).Scan(&maximum); err != nil {
		t.Fatal(err)
	}
	b, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	var envelope Envelope
	if err := json.Unmarshal(b.Payload, &envelope); err != nil {
		t.Fatal(err)
	}
	if len(envelope.Records) == 0 || len(envelope.Records) >= 20 {
		t.Fatal("expected a smaller durable batch")
	}
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || frozen.ID != b.ID || string(frozen.Payload) != string(b.Payload) {
		t.Fatal("frozen batch changed", err)
	}
	if err := s.Acknowledge(testContext, b.ID, "wrong"); err == nil {
		t.Fatal("accepted wrong ACK")
	}
	var n int
	if err := s.db.QueryRow(`SELECT count(*) FROM outbox`).Scan(&n); err != nil || n != 20 {
		t.Fatal("data removed before valid ACK")
	}
	if _, err := s.db.Exec(`CREATE TRIGGER fail_ack BEFORE INSERT ON metadata WHEN NEW.key='last_ack_id' BEGIN SELECT RAISE(ABORT, 'synthetic ACK write failure'); END`); err != nil {
		t.Fatal(err)
	}
	if err := s.Acknowledge(testContext, b.ID, b.Digest); err == nil {
		t.Fatal("expected ACK rollback")
	}
	frozen, err = s.Prepare(testContext, 500, 1<<20)
	if err != nil || frozen.ID != b.ID || string(frozen.Payload) != string(b.Payload) {
		t.Fatal("failed ACK lost frozen batch", err)
	}
	if _, err := s.db.Exec(`DROP TRIGGER fail_ack`); err != nil {
		t.Fatal(err)
	}
	if err := s.Acknowledge(testContext, b.ID, b.Digest); err != nil {
		t.Fatal(err)
	}
	if err := s.db.QueryRow(`SELECT count(*) FROM outbox`).Scan(&n); err != nil || n != 20-len(envelope.Records) {
		t.Fatal("wrong ACK boundary")
	}
}
