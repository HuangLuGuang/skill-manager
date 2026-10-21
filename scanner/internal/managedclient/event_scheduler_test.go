package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"
)

func TestEventUploaderCrossProcessWakeAndShutdown(t *testing.T) {
	store := ordinaryFixture(t)
	arrived := make(chan time.Time, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		eventAck(w, body)
		arrived <- time.Now()
	}))
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go func() { defer close(done); runEventUploader(ctx, NewAPI(server.URL, "fixture", time.Second), store) }()
	// Let the initial empty pass complete; subsequent work must wake the idle worker.
	time.Sleep(100 * time.Millisecond)
	producer, err := OpenStore(filepath.Join(store.root, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer producer.Close()
	start := time.Now()
	if err := producer.QueueEvent(stableEvent(server.URL, 1)); err != nil {
		t.Fatal(err)
	}
	select {
	case at := <-arrived:
		t.Logf("enqueue-to-request: %s", at.Sub(start))
	case <-time.After(3 * time.Second):
		t.Fatal("cross-process wake was lost")
	}
	deadline := time.Now().Add(time.Second)
	for queueTotal(t, store) != 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("uploader did not stop")
	}
	if queueTotal(t, store) != 0 {
		t.Fatal("durably acknowledged event retained")
	}
}

func TestEventUploadDelayHonorsPersistedRetryAndIdle(t *testing.T) {
	store := ordinaryFixture(t)
	server := "http://fixture"
	if got := eventUploadDelay(store, server); got != eventRepairInterval {
		t.Fatal(got)
	}
	store.QueueEvent(stableEvent(server, 1))
	store.db.Exec(`INSERT INTO client_event_sender(server,retry_at) VALUES(?,?)`, server, time.Now().Add(5*time.Second).UnixMilli())
	if got := eventUploadDelay(store, server); got < 4*time.Second || got > 5*time.Second {
		t.Fatal(got)
	}
	store.db.Exec(`UPDATE client_event_sender SET retry_at=0 WHERE server=?`, server)
	if got := eventUploadDelay(store, server); got != 100*time.Millisecond {
		t.Fatal(got)
	}
}

func TestEventUploaderRepairsMissingWake(t *testing.T) {
	store := ordinaryFixture(t)
	arrived := make(chan time.Time, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		eventAck(w, body)
		arrived <- time.Now()
	}))
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); runEventUploader(ctx, NewAPI(server.URL, "fixture", time.Second), store) }()
	defer func() { cancel(); <-done }()
	time.Sleep(100 * time.Millisecond)
	tx, err := eventTx(store.db)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback()
	// Commit without the filesystem hint, as after a producer crash at that boundary.
	if err := insertEvent(tx, stableEvent(server.URL, 1)); err != nil {
		t.Fatal(err)
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	select {
	case at := <-arrived:
		t.Logf("missing hint repaired after %s", at.Sub(start))
	case <-time.After(eventRepairInterval + 5*time.Second):
		t.Fatal("committed event was stranded without a wake hint")
	}
}

// Compare the previous one-second polling loop with filesystem wakeups using the same queue and HTTP ACK.
func TestEventSchedulerLatencyComparison(t *testing.T) {
	for _, mode := range []string{"polling", "event"} {
		t.Run(mode, func(t *testing.T) {
			for sample := 0; sample < 3; sample++ {
				store := ordinaryFixture(t)
				arrived := make(chan time.Time, 1)
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					var body map[string]any
					json.NewDecoder(r.Body).Decode(&body)
					eventAck(w, body)
					arrived <- time.Now()
				}))
				ctx, cancel := context.WithCancel(context.Background())
				done := make(chan struct{})
				api := NewAPI(server.URL, "fixture", time.Second)
				go func() {
					defer close(done)
					if mode == "event" {
						runEventUploader(ctx, api, store)
						return
					}
					ticker := time.NewTicker(time.Second)
					defer ticker.Stop()
					for {
						_ = flushEvents(ctx, api, store)
						select {
						case <-ctx.Done():
							return
						case <-ticker.C:
						}
					}
				}()
				time.Sleep(100 * time.Millisecond)
				start := time.Now()
				err := store.QueueEvent(stableEvent(server.URL, 1))
				select {
				case at := <-arrived:
					t.Logf("sample=%d enqueue_to_request_ms=%.3f", sample, float64(at.Sub(start).Microseconds())/1000)
				case <-time.After(3 * time.Second):
					t.Error("event was not sent", err)
				}
				cancel()
				<-done
				server.Close()
			}
		})
	}
}
