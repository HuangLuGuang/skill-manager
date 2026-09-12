package managedclient

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestScanProgressPersistsForItsDetectionVersion(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
		} else {
			w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING","scan_progress_stage":"analyzers","scan_progress_analyzers":{"scanner":"completed","llm":"running","sandbox":"disabled"}}`))
		}
	}))
	defer server.Close()
	id, err := SubmitDiscoveredSkill(context.Background(), home, NewAPI(server.URL, "token", time.Second), store, "codex", skill.Path, skill.Signature)
	if err != nil {
		t.Fatal(err)
	}
	items, err := RefreshPending(context.Background(), server.URL, "token", store)
	if err != nil || len(items) != 1 || items[0].Progress.Stage != "analyzers" {
		t.Fatal("live progress missing", items, err)
	}
	cached, err := store.PendingItem(id)
	if err != nil || cached.Progress.Analyzers["llm"] != "running" || cached.Progress.VersionID != "v1" || cached.Progress.UpdatedAt == "" {
		t.Fatal("progress cache missing", cached, err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.EnrichInventory(&inventory); err != nil {
		t.Fatal(err)
	}
	var scan *SkillScanObservation
	for _, agent := range inventory.Agents {
		for _, found := range agent.Skills {
			if found.Path == skill.Path && found.Governance != nil {
				scan = found.Governance.Scan
			}
		}
	}
	if scan == nil || scan.Status != "PENDING" || scan.Progress.Analyzers["llm"] != "running" {
		t.Fatal("inventory omitted actual detection progress", scan)
	}
	original, err := os.ReadFile(filepath.Join(skill.Path, "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(skill.Path, "SKILL.md"), []byte("edited after scan submission"), 0600); err != nil {
		t.Fatal(err)
	}
	inventory, err = Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.EnrichInventory(&inventory); err != nil {
		t.Fatal(err)
	}
	for _, agent := range inventory.Agents {
		for _, found := range agent.Skills {
			if found.Path == skill.Path && found.Governance != nil && found.Governance.Scan != nil {
				t.Fatal("edited content reused old scan progress")
			}
		}
	}
	if err := os.WriteFile(filepath.Join(skill.Path, "SKILL.md"), original, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`UPDATE client_pending SET version_id='v2' WHERE id=?`, id); err != nil {
		t.Fatal(err)
	}
	cached, err = store.PendingItem(id)
	if err != nil || cached.Progress.Stage != "" {
		t.Fatal("another version reused progress", cached, err)
	}
	if err := store.ResetForConnectionChange(); err != nil {
		t.Fatal(err)
	}
	cached, err = store.PendingItem(id)
	if err != nil || cached.Progress.Stage != "" || cached.VersionID != "" {
		t.Fatal("another connection reused progress", cached, err)
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal("progress polling changed the source", err)
	}

}

func TestBackgroundScanProgressRetriesAndStopsPollingTerminalResults(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	status, calls := "unavailable", 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
			return
		}
		calls++
		switch status {
		case "unavailable":
			http.Error(w, "temporary failure", http.StatusServiceUnavailable)
		case "running":
			w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING","scan_progress_stage":"analyzers","scan_progress_analyzers":{"scanner":"running"}}`))
		default:
			w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"REJECTED"}`))
		}
	}))
	defer server.Close()
	api := NewAPI(server.URL, "token", time.Second)
	id, err := SubmitDiscoveredSkill(context.Background(), home, api, store, "codex", skill.Path, skill.Signature)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := refreshBackgroundScans(context.Background(), api, store); err == nil {
		t.Fatal("missing network error")
	}
	status = "running"
	changed, _, err := refreshBackgroundScans(context.Background(), api, store)
	if err != nil || !changed {
		t.Fatal(changed, err)
	}
	item, err := store.PendingItem(id)
	if err != nil || item.Progress.Analyzers["scanner"] != "running" {
		t.Fatal(item, err)
	}
	status = "rejected"
	changed, transition, err := refreshBackgroundScans(context.Background(), api, store)
	if err != nil || !changed || !transition {
		t.Fatal(changed, transition, err)
	}
	item, err = store.PendingItem(id)
	if err != nil || item.Status != "REJECTED" || item.Progress.Stage != "" {
		t.Fatal(item, err)
	}
	before := calls
	changed, transition, err = refreshBackgroundScans(context.Background(), api, store)
	if err != nil || changed || transition || calls != before {
		t.Fatal(changed, transition, calls, err)
	}
}

func TestInventoryRefreshAfterPendingRecordIsRemoved(t *testing.T) {
	_, store, inventory, skill := observedFixture(t)
	observation := SkillObservation{Signature: skill.Signature, PendingID: strings.TrimPrefix(observationKey(skill.Path+":"+skill.Signature), "observation:")}
	if err := store.SaveObservation(skill.Path, observation); err != nil {
		t.Fatal(err)
	}
	if err := store.EnrichInventory(&inventory); err != nil {
		t.Fatal("removed detection record blocked inventory refresh", err)
	}
	agent, ok := findAgent(inventory, "codex")
	if !ok {
		t.Fatal("missing Agent")
	}
	for _, item := range agent.Skills {
		if item.Path == skill.Path && (item.Governance.PendingID != "" || item.Governance.Scan != nil) {
			t.Fatal("stale detection association retained")
		}
	}
}
