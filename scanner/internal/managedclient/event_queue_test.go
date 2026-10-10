package managedclient

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func ordinaryFixture(t *testing.T) *Store {
	t.Helper()
	s, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	enableOrdinary(t, s)
	return s
}
func enableOrdinary(t *testing.T, s *Store) {
	t.Helper()
	if err := s.SetState("policy", `{"ordinary_events_protocol":1}`); err != nil {
		t.Fatal(err)
	}
}
func stableEvent(server string, n int) QueuedEvent {
	return QueuedEvent{Server: server, ClientID: "device", EventType: "skill_governance_recorded", AgentType: "codex", SkillName: "shared", Details: map[string]any{"path": "/skills/shared", "signature": "sha256-content", "policy_version": "6:4", "trigger": "unverified", "action": "record_only", "action_status": "completed", "observation_count": n, "last_seen_at": time.Date(2026, 10, 1, 0, 0, n, 0, time.UTC).Format(time.RFC3339Nano)}}
}
func eventAck(w http.ResponseWriter, d map[string]any) {
	json.NewEncoder(w).Encode(map[string]any{"ok": true, "event_id": 1, "delivery_id": d["delivery_id"], "durable": true})
}
func queueTotal(t *testing.T, s *Store) int {
	t.Helper()
	var n int
	if err := s.db.QueryRow(`SELECT count(*) FROM client_events_queue`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestOrdinaryStableObservationsBoundedAndCumulative(t *testing.T) {
	s := ordinaryFixture(t)
	first := stableEvent("http://platform", 1)
	for n := 1; n <= 10000; n++ {
		if err := s.QueueEvent(stableEvent(first.Server, n)); err != nil {
			t.Fatal(err)
		}
	}
	// A repeated cumulative snapshot, including out of order enqueue, adds nothing.
	if err := s.QueueEvent(first); err != nil {
		t.Fatal(err)
	}
	rows, err := s.QueuedEvents()
	if err != nil || len(rows) != 1 {
		t.Fatalf("rows=%d err=%v", len(rows), err)
	}
	d := rows[0].Details
	if observationCount(d) != 10000 || d["first_seen_at"] != first.Details["last_seen_at"] || d["last_seen_at"] != stableEvent(first.Server, 10000).Details["last_seen_at"] || d["first_seen_source"] != "queued_observation" {
		t.Fatal(d)
	}
	// Concurrent producers on independently opened handles share the same identity.
	other, err := OpenStore(filepath.Join(s.root, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	var wg sync.WaitGroup
	for k := 0; k < 8; k++ {
		wg.Add(1)
		go func(k int) {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				if err := other.QueueEvent(stableEvent(first.Server, 10001+k*50+i)); err != nil {
					t.Error(err)
					return
				}
			}
		}(k)
	}
	wg.Wait()
	rows, _ = s.QueuedEvents()
	if len(rows) != 1 || observationCount(rows[0].Details) != 10400 {
		t.Fatal(rows)
	}
}

func TestOrdinaryIdentityPreservesIndependentFacts(t *testing.T) {
	s := ordinaryFixture(t)
	base := stableEvent("http://a", 1)
	if err := s.QueueEvent(base); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"path", "signature", "policy_version", "trigger", "action", "action_status", "error_code", "task_id", "status"} {
		e := stableEvent("http://a", 2)
		e.Details[key] = "changed"
		if err := s.QueueEvent(e); err != nil {
			t.Fatal(err)
		}
	}
	for _, change := range []func(*QueuedEvent){func(e *QueuedEvent) { e.ClientID = "other-device" }, func(e *QueuedEvent) { e.AgentType = "claude-code" }, func(e *QueuedEvent) { e.Server = "http://b" }, func(e *QueuedEvent) { e.EventType = "skill_governance_detected" }} {
		e := stableEvent("http://a", 2)
		change(&e)
		if err := s.QueueEvent(e); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 2; i++ {
		e := stableEvent("http://a", 2)
		e.EventType = "skill_governance_action"
		if err := s.QueueEvent(e); err != nil {
			t.Fatal(err)
		}
	}
	if n := queueTotal(t, s); n != 16 {
		t.Fatalf("independent facts lost: %d", n)
	}
}

func TestOrdinaryUploadConcurrentEnqueueAndFlush(t *testing.T) {
	s := ordinaryFixture(t)
	started, release := make(chan struct{}), make(chan struct{})
	var calls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		close(started)
		<-release
		eventAck(w, d)
	}))
	defer srv.Close()
	api := NewAPI(srv.URL, "token", time.Second)
	s.QueueEvent(stableEvent(srv.URL, 1))
	done := make(chan error, 1)
	go func() { done <- flushEventsLimit(context.Background(), api, s, 1) }()
	<-started
	other, err := OpenStore(filepath.Join(s.root, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	s.QueueEvent(stableEvent(srv.URL, 2))
	if err = flushEventsLimit(context.Background(), api, other, 20); err != nil {
		t.Fatal(err)
	}
	if n := queueTotal(t, s); n != 2 {
		t.Fatalf("in flight evidence mutated: %d", n)
	}
	close(release)
	if err = <-done; err != nil {
		t.Fatal(err)
	}
	rows, _ := s.QueuedEvents()
	if calls != 1 || len(rows) != 1 || observationCount(rows[0].Details) != 2 {
		t.Fatal(calls, rows)
	}
}

func TestOrdinaryLostResponseRestartAndBinding(t *testing.T) {
	s := ordinaryFixture(t)
	saved := map[string]string{}
	requests := 0
	lost := true
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		id := d["delivery_id"].(string)
		b, _ := json.Marshal(d)
		if previous, ok := saved[id]; ok && previous != string(b) {
			t.Error("retry changed bytes")
		}
		saved[id] = string(b)
		requests++
		if lost {
			lost = false
			c, _, _ := w.(http.Hijacker).Hijack()
			c.Close()
			return
		}
		eventAck(w, d)
	}))
	defer srv.Close()
	api := NewAPI(srv.URL, "first-token", time.Second)
	e := stableEvent(srv.URL, 1)
	e.EventType = "skill_installed"
	s.QueueEvent(e)
	if err := flushEventsLimit(context.Background(), api, s, 1); err == nil {
		t.Fatal("lost response accepted")
	}
	before, _ := s.QueuedEvents()
	s.Close()
	var err error
	s, err = OpenStore(filepath.Join(s.root, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	enableOrdinary(t, s)
	after, _ := s.QueuedEvents()
	if before[0].DeliveryID != after[0].DeliveryID {
		t.Fatal("restart changed identity")
	}
	// Advancing the controlled clock allows retry without waiting for wall time.
	s.db.Exec(`UPDATE client_event_sender SET retry_at=0`)
	if err = flushEventsLimit(context.Background(), NewAPI(srv.URL, "rotated-token", time.Second), s, 1); err != nil {
		t.Fatal(err)
	}
	if len(saved) != 1 || requests != 2 || queueTotal(t, s) != 0 {
		t.Fatal(len(saved), requests)
	}
	e.Server = "http://old-platform"
	s.QueueEvent(e)
	s.ResetForConnectionChange()
	enableOrdinary(t, s)
	if err = flushEvents(context.Background(), api, s); err != nil {
		t.Fatal(err)
	}
	if queueTotal(t, s) != 1 || requests != 2 {
		t.Fatal("cross platform replay")
	}
}

func TestOrdinaryOldQueueTransactionalUpgrade(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "client.db")
	os.WriteFile(filepath.Join(root, "config.json"), []byte(`{"server":"http://old-platform"}`), 0600)
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`CREATE TABLE client_events_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id TEXT NOT NULL,event_type TEXT NOT NULL,agent_type TEXT,skill_name TEXT,details_json TEXT NOT NULL,created_at TEXT NOT NULL)`)
	if err != nil {
		t.Fatal(err)
	}
	tx, _ := db.Begin()
	for i := 1; i <= 1000; i++ {
		e := stableEvent("", i)
		b, _ := json.Marshal(e.Details)
		_, err = tx.Exec(`INSERT INTO client_events_queue(client_id,event_type,agent_type,skill_name,details_json,created_at) VALUES(?,?,?,?,?,?)`, e.ClientID, e.EventType, e.AgentType, e.SkillName, string(b), time.Date(2026, 9, 29, 0, 0, i, 0, time.UTC).Format(time.RFC3339Nano))
		if err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 10; i++ {
		_, err = tx.Exec(`INSERT INTO client_events_queue(client_id,event_type,details_json,created_at) VALUES('device','task_result',?,?)`, fmt.Sprintf(`{"task_id":%d}`, i), "2026-09-28T00:00:00Z")
		if err != nil {
			t.Fatal(err)
		}
	}
	tx.Commit()
	db.Close()
	s, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	rows, _ := s.QueuedEvents()
	if len(rows) != 11 {
		t.Fatal(len(rows))
	}
	obs := rows[0]
	if observationCount(obs.Details) != 1000 || obs.Details["first_seen_at"] != stableEvent("", 1).Details["last_seen_at"] || obs.Server != "http://old-platform" {
		t.Fatal(obs)
	}
	for _, e := range rows[1:] {
		if e.CreatedAt != "2026-09-28T00:00:00Z" || e.Details["first_seen_at"] != nil {
			t.Fatal(e)
		}
	}
	s.Close()
	s, err = OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	again, _ := s.QueuedEvents()
	for i := range rows {
		if rows[i].DeliveryID != again[i].DeliveryID {
			t.Fatal("migration reran")
		}
	}
}

func TestOrdinaryPacingFairnessAndRoundBound(t *testing.T) {
	s := ordinaryFixture(t)
	times := []time.Time{}
	seen := []string{}
	var serverURL string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		times = append(times, time.Now())
		seen = append(seen, d["skill_name"].(string))
		if len(times) == 1 {
			s.QueueEvent(QueuedEvent{Server: serverURL, ClientID: "device", EventType: "skill_installed", SkillName: "fresh"})
		}
		eventAck(w, d)
	}))
	defer srv.Close()
	serverURL = srv.URL
	for i := 0; i < 60; i++ {
		s.QueueEvent(QueuedEvent{Server: srv.URL, ClientID: "device", EventType: "skill_installed", SkillName: fmt.Sprint(i), CreatedAt: "2026-09-28T00:00:00Z"})
	}
	if err := flushEvents(context.Background(), NewAPI(srv.URL, "token", time.Second), s); err != nil {
		t.Fatal(err)
	}
	if len(times) != 20 || queueTotal(t, s) != 41 {
		t.Fatal(len(times), queueTotal(t, s))
	}
	fresh := -1
	for i, n := range seen {
		if n == "fresh" {
			fresh = i
		}
	}
	if fresh < 0 || fresh > 2 {
		t.Fatal("fresh event starved", seen)
	}
	for i := 1; i < len(times); i++ {
		if times[i].Sub(times[i-1]) < eventInterval-5*time.Millisecond {
			t.Fatal("send interval exceeded", times[i].Sub(times[i-1]))
		}
	}
	// Actual API entrance, even without flush, uses the same persisted limiter.
	api := NewAPI(srv.URL, "token", time.Second).WithDiagnostics(s)
	if err := api.ReportEvent(context.Background(), "device", "direct", "codex", "direct", map[string]any{}); err != nil {
		t.Fatal(err)
	}
	if times[len(times)-1].Sub(times[len(times)-2]) < eventInterval-5*time.Millisecond {
		t.Fatal("direct send bypassed limiter")
	}
}

func TestOrdinaryBackoffAndOldServerHold(t *testing.T) {
	for _, status := range []int{429, 500, 503} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			s := ordinaryFixture(t)
			calls := 0
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				w.Header().Set("Retry-After", "90")
				w.WriteHeader(status)
			}))
			defer srv.Close()
			api := NewAPI(srv.URL, "token", time.Second)
			s.QueueEvent(stableEvent(srv.URL, 1))
			if flushEvents(context.Background(), api, s) == nil {
				t.Fatal("failure accepted")
			}
			var retry int64
			s.db.QueryRow(`SELECT retry_at FROM client_event_sender WHERE server=?`, srv.URL).Scan(&retry)
			delay := time.Until(time.UnixMilli(retry))
			if delay < 59*time.Second || delay > 61*time.Second {
				t.Fatal(delay)
			}
			if err := flushEvents(context.Background(), api, s); err != nil {
				t.Fatal(err)
			}
			if calls != 1 || queueTotal(t, s) != 1 {
				t.Fatal(calls)
			}
		})
	}
	s := ordinaryFixture(t)
	s.SetState("policy", `{}`)
	s.QueueEvent(stableEvent("http://127.0.0.1:1", 1))
	if err := flushEvents(context.Background(), NewAPI("http://127.0.0.1:1", "token", time.Second), s); err == nil || !strings.Contains(err.Error(), "upgrade_required") {
		t.Fatal(err)
	}
	if queueTotal(t, s) != 1 {
		t.Fatal("old server discarded queue")
	}
	enableOrdinary(t, s)
	if flushEvents(context.Background(), NewAPI("http://127.0.0.1:1", "token", time.Second), s) == nil {
		t.Fatal("offline accepted")
	}
	var failures int
	s.db.QueryRow(`SELECT failures FROM client_event_sender`).Scan(&failures)
	if failures != 1 {
		t.Fatal(failures)
	}
}

func TestOrdinaryTimeoutRecoveryAndUnconfirmedSuccess(t *testing.T) {
	s := ordinaryFixture(t)
	var calls atomic.Int32
	var mode atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		switch mode.Load() {
		case 0:
			<-r.Context().Done()
			return
		case 1:
			json.NewEncoder(w).Encode(map[string]any{"ok": true, "event_id": 1})
		default:
			eventAck(w, d)
		}
	}))
	defer srv.Close()
	api := NewAPI(srv.URL, "token", 20*time.Millisecond)
	s.QueueEvent(stableEvent(srv.URL, 1))
	if err := flushEventsLimit(context.Background(), api, s, 1); err == nil {
		t.Fatal("timeout accepted")
	}
	rows, _ := s.QueuedEvents()
	id := rows[0].DeliveryID
	mode.Store(1)
	s.db.Exec(`UPDATE client_event_sender SET retry_at=0`)
	if err := flushEventsLimit(context.Background(), api, s, 1); err == nil || !strings.Contains(err.Error(), "upgrade_required") {
		t.Fatal(err)
	}
	again, _ := s.QueuedEvents()
	if len(again) != 1 || again[0].DeliveryID != id {
		t.Fatal("200 removed unconfirmed data")
	}
	mode.Store(2)
	s.db.Exec(`UPDATE client_event_sender SET retry_at=0`)
	if err := flushEventsLimit(context.Background(), api, s, 1); err != nil {
		t.Fatal(err)
	}
	if queueTotal(t, s) != 0 || calls.Load() != 3 {
		t.Fatal(calls.Load())
	}
}

func TestOrdinaryUnknownBindingAndLegacyTimeSource(t *testing.T) {
	s := ordinaryFixture(t)
	e := stableEvent("", 50)
	delete(e.Details, "last_seen_at")
	e.CreatedAt = "2026-09-29T00:00:00Z"
	if err := s.QueueEvent(e); err != nil {
		t.Fatal(err)
	}
	rows, _ := s.QueuedEvents()
	if rows[0].Server != "" || rows[0].Details["first_seen_source"] != "queue_created_at" || rows[0].Details["first_seen_at"] != e.CreatedAt {
		t.Fatal(rows)
	}
	if err := flushEvents(context.Background(), NewAPI("http://127.0.0.1:1", "token", time.Second), s); err != nil {
		t.Fatal(err)
	}
	if queueTotal(t, s) != 1 {
		t.Fatal("unbound event guessed platform")
	}
}

func TestOrdinaryMigrationRollbackAndUnsupportedLegacyEvidence(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "client.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`CREATE TABLE client_events_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id TEXT NOT NULL,event_type TEXT NOT NULL,agent_type TEXT,skill_name TEXT,details_json TEXT NOT NULL,created_at TEXT NOT NULL)`)
	if err != nil {
		t.Fatal(err)
	}
	e := stableEvent("", 1)
	b, _ := json.Marshal(e.Details)
	_, err = db.Exec(`INSERT INTO client_events_queue(client_id,event_type,details_json,created_at) VALUES('device','skill_governance_recorded',?,'2026-09-28T00:00:00Z'); CREATE TRIGGER preserve_evidence BEFORE DELETE ON client_events_queue BEGIN SELECT RAISE(ABORT,'controlled_migration_failure'); END`, string(b))
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	if opened, err := OpenStore(path); err == nil {
		opened.Close()
		t.Fatal("migration failure ignored")
	}
	db, err = sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	var saved string
	if err = db.QueryRow(`SELECT details_json FROM client_events_queue`).Scan(&saved); err != nil || saved != string(b) {
		t.Fatal("rollback lost evidence", err)
	}
	db.Exec(`DROP TRIGGER preserve_evidence`)
	large := `{"payload":"` + strings.Repeat("x", 300*1024) + `"}`
	for _, body := range []string{large, `{not-json}`} {
		if _, err = db.Exec(`INSERT INTO client_events_queue(client_id,event_type,details_json,created_at) VALUES('device','independent',?,'2026-09-28T00:00:00Z')`, body); err != nil {
			t.Fatal(err)
		}
	}
	db.Close()
	s, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	var held int
	s.db.QueryRow(`SELECT count(*) FROM client_events_queue WHERE sealed=-1`).Scan(&held)
	if held != 2 || queueTotal(t, s) != 3 {
		t.Fatal(held)
	}
	if err = s.db.QueryRow(`SELECT details_json FROM client_events_queue WHERE details_json LIKE '%payload%'`).Scan(&saved); err != nil || saved != large {
		t.Fatal("legacy body rewritten")
	}
	if err = s.QueueEvent(QueuedEvent{Details: map[string]any{"payload": strings.Repeat("x", 300*1024)}}); err == nil {
		t.Fatal("memory boundary ignored")
	}
}

func TestOrdinaryConfirmedDeliverySurvivesLocalCleanupFailure(t *testing.T) {
	s := ordinaryFixture(t)
	saved := map[string]bool{}
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		calls++
		saved[d["delivery_id"].(string)] = true
		eventAck(w, d)
	}))
	defer srv.Close()
	api := NewAPI(srv.URL, "token", time.Second)
	s.QueueEvent(stableEvent(srv.URL, 1))
	if _, err := s.db.Exec(`CREATE TRIGGER prevent_cleanup BEFORE DELETE ON client_events_queue BEGIN SELECT RAISE(ABORT,'controlled_cleanup_failure'); END`); err != nil {
		t.Fatal(err)
	}
	if err := flushEventsLimit(context.Background(), api, s, 1); err == nil {
		t.Fatal("cleanup failure ignored")
	}
	if queueTotal(t, s) != 1 || len(saved) != 1 {
		t.Fatal("confirmed evidence disappeared")
	}
	s.db.Exec(`DROP TRIGGER prevent_cleanup`)
	if err := flushEventsLimit(context.Background(), api, s, 1); err != nil {
		t.Fatal(err)
	}
	if queueTotal(t, s) != 0 || len(saved) != 1 || calls != 2 {
		t.Fatal("local cleanup retry duplicated logic", calls, len(saved))
	}
}

func TestOrdinaryProducerBindingSurvivesConcurrentConfigurationChange(t *testing.T) {
	s := ordinaryFixture(t)
	source := stableEvent("http://old-platform", 1)
	if err := os.WriteFile(filepath.Join(s.root, "config.json"), []byte(`{"server":"http://new-platform"}`), 0600); err != nil {
		t.Fatal(err)
	}
	// The producer carries the platform captured for this observation even when
	// an independent settings command has already saved a different connection.
	if err := queueEventWithLocalNotification(s, source.Server, source.ClientID, source.EventType, source.AgentType, source.SkillName, source.Details, false); err != nil {
		t.Fatal(err)
	}
	rows, err := s.QueuedEvents()
	if err != nil || len(rows) != 1 || rows[0].Server != source.Server {
		t.Fatal(rows, err)
	}
	if err = flushEvents(context.Background(), NewAPI("http://new-platform", "token", time.Second), s); err != nil {
		t.Fatal(err)
	}
	if queueTotal(t, s) != 1 {
		t.Fatal("old producer replayed to new platform")
	}
}
