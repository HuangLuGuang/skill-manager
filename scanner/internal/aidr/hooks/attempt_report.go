package hooks

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strconv"
	"time"
)

// AttemptReport is client evidence of a local terminal decision, not proof of
// tool execution. ReportedAt is when this immutable report was frozen.
type AttemptReport struct {
	Schema     int    `json:"schema_version"`
	Device     string `json:"client_id"`
	Stream     string `json:"stream_id"`
	Event      string `json:"event_id"`
	Receiver   string `json:"receiver_instance"`
	Approval   string `json:"approval_id"`
	State      string `json:"state"`
	Code       string `json:"code"`
	ReportedAt string `json:"reported_at"`
}

type FrozenAttemptReport struct {
	Event   string
	Payload []byte
	Digest  string
}

func (s *Store) PrepareAttemptReport(ctx context.Context) (*FrozenAttemptReport, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	f := new(FrozenAttemptReport)
	err := s.db.QueryRowContext(ctx, `SELECT event_id,payload,digest FROM hook_attempt_reports WHERE acked=0 ORDER BY event_id LIMIT 1`).Scan(&f.Event, &f.Payload, &f.Digest)
	if err == nil {
		return f, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	r := AttemptReport{Schema: 1, Device: s.device, Stream: s.stream, ReportedAt: strconv.FormatInt(time.Now().Unix(), 10)}
	err = s.db.QueryRowContext(ctx, `SELECT event_id,receiver,approval_id,state,code FROM hook_attempts WHERE state!='pending' AND event_id NOT IN (SELECT event_id FROM hook_attempt_reports) ORDER BY event_id LIMIT 1`).Scan(&r.Event, &r.Receiver, &r.Approval, &r.State, &r.Code)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	f.Event = r.Event
	f.Payload, err = json.Marshal(r)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(f.Payload)
	f.Digest = hex.EncodeToString(sum[:])
	_, err = s.db.ExecContext(ctx, `INSERT INTO hook_attempt_reports(event_id,payload,digest) VALUES(?,?,?)`, f.Event, f.Payload, f.Digest)
	return f, err
}

func (s *Store) AcknowledgeAttemptReport(ctx context.Context, device, stream, event, digest string, durable bool) error {
	if device != s.device || stream != s.stream || !durable {
		return code("aidr_hook_attempt_ack_invalid")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	var expected string
	if err := s.db.QueryRowContext(ctx, `SELECT digest FROM hook_attempt_reports WHERE event_id=?`, event).Scan(&expected); err != nil {
		return code("aidr_hook_attempt_ack_invalid")
	}
	if expected != digest {
		return code("aidr_hook_attempt_ack_invalid")
	}
	_, err := s.db.ExecContext(ctx, `UPDATE hook_attempt_reports SET acked=1 WHERE event_id=?`, event)
	return err
}
