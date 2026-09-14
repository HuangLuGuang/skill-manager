package managedclient

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestHeartbeatContinuesDuringBlockedAnalysis(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	entered := make(chan struct{})
	var once sync.Once
	var heartbeats atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/heartbeat"):
			heartbeats.Add(1)
			json.NewEncoder(w).Encode(map[string]any{"policy": Policy{Mode: "audit", Classification: DefaultClassificationPolicy()}})
		case strings.HasSuffix(r.URL.Path, "/compare"):
			once.Do(func() { close(entered) })
			select {
			case <-r.Context().Done():
			case <-ctx.Done():
			}
		case strings.HasSuffix(r.URL.Path, "/tasks"):
			w.Write([]byte(`[]`))
		default:
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	result := make(chan error, 1)
	go func() {
		result <- RunDaemon(ctx, home, NewAPI(server.URL, "token", time.Second), store, 40*time.Millisecond, nil)
	}()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("worker did not start")
	}
	before := heartbeats.Load()
	deadline := time.After(2 * time.Second)
	for heartbeats.Load() < before+2 {
		select {
		case <-deadline:
			cancel()
			t.Fatal("analysis blocked heartbeat")
		case <-time.After(10 * time.Millisecond):
		}
	}
	cancel()
	select {
	case err := <-result:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("daemon did not stop on process context cancellation")
	}
}

func TestInventoryRevisionIgnoresGovernancePresentation(t *testing.T) {
	_, _, inventory, _ := observedFixture(t)
	before := inventoryRevision(inventory)
	inventory.Agents[0].Skills[0].Governance = &SkillObservation{LastSeenAt: "new", ActionStatus: "completed"}
	if inventoryRevision(inventory) != before {
		t.Fatal("presentation update triggered another detection")
	}
	inventory.Agents[0].Skills[0].Signature = "edited"
	if inventoryRevision(inventory) == before {
		t.Fatal("content change was missed")
	}
}

func TestDaemonRetriesInitialRegistrationBeforeReportingInventory(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var registrations atomic.Int32
	var inventories atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/register"):
			if registrations.Add(1) == 1 {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
		case strings.HasSuffix(r.URL.Path, "/heartbeat"):
			json.NewEncoder(w).Encode(map[string]any{"policy": Policy{Mode: "audit", Classification: DefaultClassificationPolicy()}})
			return
		case strings.HasSuffix(r.URL.Path, "/inventory"):
			if registrations.Load() < 2 {
				t.Error("inventory sent before registration succeeded")
			}
			inventories.Add(1)
		case strings.HasSuffix(r.URL.Path, "/tasks"):
			w.Write([]byte(`[]`))
			return
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	finished := make(chan error, 1)
	go func() {
		finished <- RunDaemon(ctx, home, NewAPI(server.URL, "token", time.Second), store, 30*time.Millisecond, nil)
	}()
	deadline := time.Now().Add(4 * time.Second)
	for inventories.Load() < 2 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	select {
	case err := <-finished:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("daemon failed to exit")
	}
	if registrations.Load() != 2 || inventories.Load() < 2 {
		t.Fatalf("registration retry or subsequent inventory failed: registrations=%d inventories=%d", registrations.Load(), inventories.Load())
	}
}

func TestTaskQueueRetainsOlderWorkAndRetriesReceipts(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	for id := int64(1); id <= 150; id++ {
		status := "succeeded"
		if id == 1 {
			status = "pending"
		}
		if err := store.SaveTask(Task{ID: id, TaskType: "rescan"}, status, ""); err != nil {
			t.Fatal(err)
		}
		if id > 2 {
			if err := store.SetState(fmt.Sprintf("task:reported:%d", id), status); err != nil {
				t.Fatal(err)
			}
		}
	}
	pending, err := store.PendingTasks()
	if err != nil || len(pending) != 1 || pending[0].ID != 1 {
		t.Fatalf("older pending task missing: %v %v", pending, err)
	}
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.Write([]byte(`[]`))
			return
		}
		if attempts.Add(1) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	api := NewAPI(server.URL, "token", time.Second)
	if err := flushTaskResults(context.Background(), clientIDForHome(home), api, store); err == nil {
		t.Fatal("expected receipt transport failure")
	}
	unreported, err := store.UnreportedTasks()
	if err != nil || len(unreported) != 1 || unreported[0].ID != 2 {
		t.Fatalf("failed receipt was lost: %v %v", unreported, err)
	}
	for i := 0; i < 2; i++ {
		if err := flushTaskResults(context.Background(), clientIDForHome(home), api, store); err != nil {
			t.Fatal(err)
		}
	}
	if attempts.Load() != 2 {
		t.Fatalf("acknowledged receipt was resent: %d", attempts.Load())
	}
}

func TestLocalStatusIncludesObservedSkillsAndIndependentSyncHealth(t *testing.T) {
	_, store, inventory, _ := observedFixture(t)
	// Shared roots can occur in more than one discovery group.
	inventory.Agents = append(inventory.Agents, inventory.Agents[0])
	if err := store.SaveInventory(inventory); err != nil {
		t.Fatal(err)
	}
	syncError(store, "heartbeat", nil)
	syncError(store, "inventory", fmt.Errorf("upload unavailable"))
	if err := store.SetState("client:update-versions", `{"stable":"26.9.1403","preview":"26.9.1404"}`); err != nil {
		t.Fatal(err)
	}
	status, err := store.LocalStatus()
	if err != nil {
		t.Fatal(err)
	}
	if status.ManagedSkills != 1 || !status.GovernanceEnabled {
		t.Fatalf("discovered Skill was not enrolled: %+v", status)
	}
	if status.Sync["heartbeat"].LastSuccessAt == "" || status.Sync["heartbeat"].Error != "" {
		t.Fatal(status.Sync)
	}
	if status.Sync["inventory"].Error != "upload unavailable" || status.Sync["inventory"].LastSuccessAt != "" {
		t.Fatal(status.Sync)
	}
	if status.ClientUpdates.Stable != "26.9.1403" || status.ClientUpdates.Preview != "26.9.1404" {
		t.Fatal(status.ClientUpdates)
	}
}

func TestHeartbeatDoesNotWaitForFiveMinuteDiscoveryInterval(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var heartbeats atomic.Int32
	reached := make(chan struct{})
	var once sync.Once
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/heartbeat"):
			if heartbeats.Add(1) >= 3 {
				once.Do(func() { close(reached) })
			}
			json.NewEncoder(w).Encode(map[string]any{"policy": Policy{Mode: "audit", Classification: DefaultClassificationPolicy()}})
		case strings.HasSuffix(r.URL.Path, "/tasks"):
			w.Write([]byte(`[]`))
		case strings.HasSuffix(r.URL.Path, "/compare"):
			w.Write([]byte(`{"items":[]}`))
		default:
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	finished := make(chan error, 1)
	go func() {
		finished <- RunDaemon(ctx, home, NewAPI(server.URL, "test", time.Second), store, 5*time.Minute, nil)
	}()
	select {
	case <-reached:
	case <-time.After(14 * time.Second):
		t.Error("heartbeat still waits for discovery interval", heartbeats.Load())
	}
	cancel()
	select {
	case <-finished:
	case <-time.After(3 * time.Second):
		t.Error("daemon did not stop")
	}
}
