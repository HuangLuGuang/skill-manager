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
	"runtime"
	"sync"
	"testing"
	"time"
)

func TestOrdinaryLoadAcceptance(t *testing.T) {
	root := t.TempDir()
	times := []time.Time{}
	var mu sync.Mutex
	var receivedObservations float64
	independentSeen := map[string]bool{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		mu.Lock()
		times = append(times, time.Now())
		if d["event_type"] == "skill_governance_recorded" {
			if n, ok := d["observation_count"].(float64); ok && n > receivedObservations {
				receivedObservations = n
			}
		}
		if d["event_type"] == "skill_installed" {
			if name, ok := d["skill_name"].(string); ok {
				independentSeen[name] = true
			}
		}
		mu.Unlock()
		json.NewEncoder(w).Encode(map[string]any{"ok": true, "event_id": 1, "delivery_id": d["delivery_id"], "durable": true})
	}))
	defer srv.Close()
	os.WriteFile(filepath.Join(root, "config.json"), []byte(fmt.Sprintf(`{"server":%q}`, srv.URL)), 0600)
	path := filepath.Join(root, "client.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`CREATE TABLE client_events_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id TEXT NOT NULL,event_type TEXT NOT NULL,agent_type TEXT,skill_name TEXT,details_json TEXT NOT NULL,created_at TEXT NOT NULL)`)
	if err != nil {
		t.Fatal(err)
	}
	tx, _ := db.Begin()
	for i := 1; i <= 5000; i++ {
		at := time.Date(2026, 9, 28, 0, 0, i, 0, time.UTC).Format(time.RFC3339Nano)
		d := map[string]any{"path": "/controlled/skill", "signature": "content", "trigger": "unverified", "action": "record_only", "policy_version": "6:4", "action_status": "completed", "observation_count": i, "last_seen_at": at}
		b, _ := json.Marshal(d)
		_, err = tx.Exec(`INSERT INTO client_events_queue(client_id,event_type,agent_type,skill_name,details_json,created_at) VALUES('controlled','skill_governance_recorded','codex','shared',?,?)`, string(b), at)
		if err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 40; i++ {
		_, err = tx.Exec(`INSERT INTO client_events_queue(client_id,event_type,agent_type,skill_name,details_json,created_at) VALUES('controlled','skill_installed','codex',?,?,?)`, fmt.Sprint(i), fmt.Sprintf(`{"task_id":%d}`, i), "2026-09-29T00:00:00Z")
		if err != nil {
			t.Fatal(err)
		}
	}
	tx.Commit()
	db.Close()
	runtime.GC()
	var before runtime.MemStats
	runtime.ReadMemStats(&before)
	stop := make(chan struct{})
	sampled := make(chan uint64, 1)
	go func() {
		var peak uint64
		for {
			var m runtime.MemStats
			runtime.ReadMemStats(&m)
			if m.HeapAlloc > peak {
				peak = m.HeapAlloc
			}
			select {
			case <-stop:
				sampled <- peak
				return
			case <-time.After(5 * time.Millisecond):
			}
		}
	}()
	upgradeStart := time.Now()
	store, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	upgrade := time.Since(upgradeStart)
	store.SetState("policy", `{"ordinary_events_protocol":1}`)
	var afterUpgrade int
	store.db.QueryRow(`SELECT count(*) FROM client_events_queue`).Scan(&afterUpgrade)
	api := NewAPI(srv.URL, "controlled", time.Second)
	sendStart := time.Now()
	for {
		var n int
		store.db.QueryRow(`SELECT count(*) FROM client_events_queue`).Scan(&n)
		if n == 0 {
			break
		}
		if err = flushEvents(context.Background(), api, store); err != nil {
			t.Fatal(err)
		}
	}
	elapsed := time.Since(sendStart)
	close(stop)
	peak := <-sampled
	var after runtime.MemStats
	runtime.ReadMemStats(&after)
	mu.Lock()
	defer mu.Unlock()
	max := 0
	start := 0
	for end := range times {
		for times[end].Sub(times[start]) >= time.Second {
			start++
		}
		if n := end - start + 1; n > max {
			max = n
		}
	}
	result := map[string]any{"source_queue_rows": 5040, "rows_after_upgrade": afterUpgrade, "final_queue_rows": 0, "cumulative_observations": receivedObservations, "independent_facts": len(independentSeen), "requests": len(times), "peak_requests_rolling_second": max, "send_seconds": elapsed.Seconds(), "upgrade_seconds": upgrade.Seconds(), "peak_heap_bytes": peak, "allocated_bytes": after.TotalAlloc - before.TotalAlloc}
	if receivedObservations != 5000 || len(independentSeen) != 40 {
		t.Fatal("receiver lost observations or independent facts", receivedObservations, len(independentSeen))
	}
	b, _ := json.Marshal(result)
	t.Log(string(b))
	if p := os.Getenv("ORDINARY_METRICS_FILE"); p != "" {
		os.WriteFile(p, b, 0600)
	}
}
