package managedclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"sync"
	"time"
)

var errEventDeferred = errors.New("client_events_backoff")
var ordinaryEventPacer struct {
	sync.Mutex
	next time.Time
}

func waitEventSlot(ctx context.Context, api API) error {
	var at time.Time
	if api.eventsStore != nil {
		tx, err := eventTx(api.eventsStore.db)
		if err != nil {
			return err
		}
		defer tx.Rollback()
		_, err = tx.Exec(`INSERT OR IGNORE INTO client_event_sender(server) VALUES(?)`, api.server)
		if err != nil {
			return err
		}
		var next, retry int64
		if err = tx.QueryRow(`SELECT next_send,retry_at FROM client_event_sender WHERE server=?`, api.server).Scan(&next, &retry); err != nil {
			return err
		}
		now := time.Now()
		if retry > now.UnixMilli() {
			return errEventDeferred
		}
		at = now
		if next > now.UnixMilli() {
			at = time.UnixMilli(next)
		}
		_, err = tx.Exec(`UPDATE client_event_sender SET next_send=? WHERE server=?`, (at.Add(eventInterval).UnixNano()+int64(time.Millisecond)-1)/int64(time.Millisecond), api.server)
		if err != nil {
			return err
		}
		if err = tx.Commit(); err != nil {
			return err
		}
	} else {
		ordinaryEventPacer.Lock()
		at = time.Now()
		if ordinaryEventPacer.next.After(at) {
			at = ordinaryEventPacer.next
		}
		ordinaryEventPacer.next = at.Add(eventInterval)
		ordinaryEventPacer.Unlock()
	}
	timer := time.NewTimer(time.Until(at))
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
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
	if err = waitEventSlot(ctx, api); err != nil {
		return err
	}
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
	resp, err := api.http.Do(req)
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
		return fmt.Errorf("client_events_http_%d", resp.StatusCode)
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
