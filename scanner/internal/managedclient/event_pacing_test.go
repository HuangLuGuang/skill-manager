package managedclient

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// Delaying the first receipt beyond multiple intervals must not allow the
// second sender to catch up, even through an independently opened store.
func TestOrdinaryDelayedReceiptCannotBurstAcrossStores(t *testing.T) {
	store := ordinaryFixture(t)
	other, err := OpenStore(filepath.Join(store.root, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	entered := make(chan struct{})
	release := make(chan struct{})
	var mu sync.Mutex
	var times []time.Time
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		mu.Lock()
		times = append(times, time.Now())
		n := len(times)
		mu.Unlock()
		if n == 1 {
			close(entered)
			<-release
		}
		eventAck(w, d)
	}))
	defer srv.Close()
	first := NewAPI(srv.URL, "token", 3*time.Second).WithDiagnostics(store)
	second := NewAPI(srv.URL, "token", 3*time.Second).WithDiagnostics(other)
	done := make(chan error, 2)
	go func() { done <- first.ReportEvent(context.Background(), "device", "first", "codex", "one", nil) }()
	<-entered
	go func() { done <- second.ReportEvent(context.Background(), "device", "second", "codex", "two", nil) }()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	if err := second.ReportEvent(ctx, "device", "cancelled", "codex", "three", nil); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("waiting sender: %v", err)
	}
	time.Sleep(2 * eventInterval)
	receiptAt := time.Now()
	close(release)
	for i := 0; i < 2; i++ {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if len(times) != 2 || times[1].Sub(receiptAt) < eventInterval {
		t.Fatalf("compressed dispatch: %v", times)
	}
}

func TestOrdinaryRoundPacingExpiryPreservesUnsentEvent(t *testing.T) {
	store := ordinaryFixture(t)
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		var d map[string]any
		json.NewDecoder(r.Body).Decode(&d)
		time.Sleep(5800 * time.Millisecond)
		eventAck(w, d)
	}))
	defer srv.Close()
	for _, name := range []string{"one", "two"} {
		if err := store.QueueEvent(QueuedEvent{Server: srv.URL, ClientID: "device", EventType: "skill_installed", SkillName: name}); err != nil {
			t.Fatal(err)
		}
	}
	if err := flushEvents(context.Background(), NewAPI(srv.URL, "token", 10*time.Second), store); err != nil {
		t.Fatal("pacing expiry is not a network failure", err)
	}
	if calls != 1 || queueTotal(t, store) != 1 {
		t.Fatalf("calls=%d queue=%d", calls, queueTotal(t, store))
	}
	var retry int64
	if err := store.db.QueryRow(`SELECT retry_at FROM client_event_sender WHERE server=?`, srv.URL).Scan(&retry); err != nil || retry != 0 {
		t.Fatalf("unsent event introduced backoff: %d %v", retry, err)
	}
}
