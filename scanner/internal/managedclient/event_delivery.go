package managedclient

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"
)

var errEventDeferred = errors.New("client_events_backoff")

type eventWaitError struct{ error }

func (e eventWaitError) Unwrap() error { return e.error }

type eventPacer struct {
	gate chan struct{}
	next time.Time
}

var ordinaryEventPacers sync.Map

// Serialize dispatch through the receipt, then leave a full interval before
// the next send. A delayed sender cannot consume an expired reservation and
// create a catch-up burst. The file lock also covers other local processes;
// no SQLite transaction is held while waiting or performing network I/O.
func acquireEventSlot(ctx context.Context, api API) (func(), error) {
	var release func()
	var at time.Time
	if api.eventsStore != nil {
		hash := sha256.Sum256([]byte(api.server))
		f, err := os.OpenFile(filepath.Join(api.eventsStore.root, fmt.Sprintf("event-send-%x.lock", hash[:12])), os.O_CREATE|os.O_RDWR, 0600)
		if err != nil {
			return nil, err
		}
		for {
			err = lockClientFile(f)
			if err == nil {
				break
			}
			if !errors.Is(err, ErrAlreadyRunning) {
				f.Close()
				return nil, err
			}
			select {
			case <-ctx.Done():
				f.Close()
				return nil, ctx.Err()
			case <-time.After(10 * time.Millisecond):
			}
		}
		release = func() { _ = unlockClientFile(f); _ = f.Close() }
		_, err = api.eventsStore.db.ExecContext(ctx, `INSERT OR IGNORE INTO client_event_sender(server) VALUES(?)`, api.server)
		var next, retry int64
		if err == nil {
			err = api.eventsStore.db.QueryRowContext(ctx, `SELECT next_send,retry_at FROM client_event_sender WHERE server=?`, api.server).Scan(&next, &retry)
		}
		if err != nil {
			release()
			return nil, err
		}
		if retry > time.Now().UnixMilli() {
			release()
			return nil, errEventDeferred
		}
		at = time.UnixMilli(next)
	} else {
		value, _ := ordinaryEventPacers.LoadOrStore(api.server, &eventPacer{gate: make(chan struct{}, 1)})
		p := value.(*eventPacer)
		select {
		case p.gate <- struct{}{}:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
		at = p.next
		release = func() { p.next = time.Now().Add(eventInterval); <-p.gate }
	}
	timer := time.NewTimer(time.Until(at))
	defer timer.Stop()
	select {
	case <-ctx.Done():
		release()
		return nil, ctx.Err()
	case <-timer.C:
	}
	return func() {
		if api.eventsStore != nil {
			// Persist before releasing the OS lock, including after failed sends.
			_, _ = api.eventsStore.db.Exec(`UPDATE client_event_sender SET next_send=? WHERE server=?`, time.Now().Add(eventInterval).UnixMilli()+1, api.server)
		}
		release()
	}, nil
}
func eventRetry(api API, failed bool, after time.Duration) {
	if api.eventsStore == nil {
		return
	}
	if !failed {
		_, _ = api.eventsStore.db.Exec(`UPDATE client_event_sender SET failures=0,retry_at=0 WHERE server=?`, api.server)
		return
	}
	tx, err := eventTx(api.eventsStore.db)
	if err != nil {
		return
	}
	defer tx.Rollback()
	var failures int
	if err = tx.QueryRow(`SELECT failures FROM client_event_sender WHERE server=?`, api.server).Scan(&failures); err != nil {
		return
	}
	if failures < 6 {
		failures++
	}
	delay := time.Second * time.Duration(1<<failures)
	if delay > time.Minute {
		delay = time.Minute
	}
	if after > delay {
		delay = after
	}
	if delay > time.Minute {
		delay = time.Minute
	}
	_, err = tx.Exec(`UPDATE client_event_sender SET failures=?,retry_at=? WHERE server=?`, failures, time.Now().Add(delay).UnixMilli(), api.server)
	if err == nil {
		_ = tx.Commit()
	}
}
func (api API) sendOrdinaryEvent(ctx context.Context, e QueuedEvent) (err error) {
	if e.Details == nil {
		e.Details = map[string]any{}
	}
	release, err := acquireEventSlot(ctx, api)
	if err != nil {
		return eventWaitError{err}
	}
	defer release()
	after := time.Duration(0)
	defer func() { eventRetry(api, err != nil, after) }()
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	count := e.Details["observation_count"]
	if count == nil {
		count = 1
	}
	payload := map[string]any{"event_type": e.EventType, "agent_type": e.AgentType, "skill_name": e.SkillName, "details": e.Details, "observation_count": count, "observed_at": e.Details["last_seen_at"]}
	if e.DeliveryID != "" {
		payload["delivery_id"] = e.DeliveryID
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := api.request(ctx, http.MethodPost, "/api/v1/clients/"+e.ClientID+"/events", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := api.do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		if seconds, parseErr := strconv.Atoi(resp.Header.Get("Retry-After")); parseErr == nil && seconds > 0 {
			if seconds > 60 {
				seconds = 60
			}
			after = time.Duration(seconds) * time.Second
		} else if t, parseErr := http.ParseTime(resp.Header.Get("Retry-After")); parseErr == nil {
			after = time.Until(t)
		}
		failure := fmt.Errorf("client_events_http_%d", resp.StatusCode)
		if api.eventsStore != nil {
			return reportedDiagnosticError{failure}
		}
		return failure
	}
	var ack struct {
		OK         bool   `json:"ok"`
		EventID    int64  `json:"event_id"`
		DeliveryID string `json:"delivery_id"`
		Durable    bool   `json:"durable"`
	}
	if err = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&ack); err != nil {
		return err
	}
	if !ack.OK || ack.EventID < 1 {
		return errors.New("client_events_receipt_invalid")
	}
	if e.DeliveryID != "" && (!ack.Durable || ack.DeliveryID != e.DeliveryID) {
		return errors.New("client_events_server_upgrade_required")
	}
	return nil
}
