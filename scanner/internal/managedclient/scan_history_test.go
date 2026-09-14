package managedclient

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestConcurrentStoreOpenPreservesScanHistory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "client.db")
	store, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.db.Exec(`INSERT INTO client_scan_history VALUES ('retained','{"id":"retained","skill_id":"skill","status":"APPROVED"}')`); err != nil {
		t.Fatal(err)
	}
	results := make(chan error, 12)
	for i := 0; i < 12; i++ {
		go func() {
			for n := 0; n < 5; n++ {
				opened, err := OpenStore(path)
				if err != nil {
					results <- err
					return
				}
				_, err = opened.ScanHistory()
				opened.Close()
				if err != nil {
					results <- err
					return
				}
			}
			results <- nil
		}()
	}
	for i := 0; i < 12; i++ {
		if err := <-results; err != nil {
			t.Error(err)
		}
	}
	items, err := store.ScanHistory()
	if err != nil || len(items) != 1 || items[0].Status != "APPROVED" {
		t.Fatalf("history changed after concurrent opens: %+v, %v", items, err)
	}
}

func TestScanHistorySurvivesCopyCleanupAndResubmission(t *testing.T) {
	home := t.TempDir()
	db := filepath.Join(home, "client.db")
	store, err := OpenStore(db)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(home, "copy")
	if err = os.Mkdir(path, 0700); err != nil {
		t.Fatal(err)
	}
	item := PendingItem{ID: "copy", AgentType: "claude-code", SkillName: "example", PendingPath: path, OriginalPath: filepath.Join(home, "skills", "example")}
	if err = store.SavePending(item); err != nil {
		t.Fatal(err)
	}
	history, err := store.ScanHistory()
	if err != nil || len(history) != 0 {
		t.Fatal("unsubmitted copy appeared as scan", history, err)
	}
	if err = store.MarkPendingSubmitted(item, "family", "v1"); err != nil {
		t.Fatal(err)
	}
	if err = store.UpdatePendingStatus("family", "v1", "APPROVED"); err != nil {
		t.Fatal(err)
	}
	if err = store.ResetPendingSubmission(item.ID); err != nil {
		t.Fatal(err)
	}
	if err = store.MarkPendingSubmitted(item, "family", "v2"); err != nil {
		t.Fatal(err)
	}
	if err = store.RemovePending(item.ID); err != nil {
		t.Fatal(err)
	}
	store.Close()
	store, err = OpenStore(db)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	history, err = store.ScanHistory()
	if err != nil || len(history) != 2 {
		t.Fatal("scan history lost", history, err)
	}
	found := false
	for _, entry := range history {
		if entry.VersionID == "v1" && entry.Status == "APPROVED" {
			found = true
		}
	}
	if !found {
		t.Fatal("completed scan overwritten", history)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"skill_id":"family","version_id":"v2","version_no":2,"source_version":"1.4.0","status":"REJECTED"}`))
	}))
	defer server.Close()
	history, err = RefreshScanHistory(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range history {
		if entry.VersionID == "v2" && (entry.Status != "REJECTED" || entry.VersionNo != 2 || entry.SourceVersion != "1.4.0") {
			t.Fatal("removed-copy scan metadata not refreshed", history)
		}
	}
}

func TestScanHistoryBackfillsExistingSubmittedRowsWithoutCopyFiles(t *testing.T) {
	db := filepath.Join(t.TempDir(), "client.db")
	store, err := OpenStore(db)
	if err != nil {
		t.Fatal(err)
	}
	item := PendingItem{ID: "old", AgentType: "codex", SkillName: "old-scan", PendingPath: "/missing-copy", SkillID: "family", VersionID: "version", Status: "APPROVED", SubmittedAt: "2026-09-12T00:00:00Z"}
	if err = store.SavePending(item); err != nil {
		t.Fatal(err)
	}
	if _, err = store.db.Exec(`DROP TRIGGER scan_history_after_insert; DROP TRIGGER scan_history_after_update; DROP TABLE client_scan_history;`); err != nil {
		t.Fatal(err)
	}
	store.Close()
	store, err = OpenStore(db)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	history, err := store.ScanHistory()
	if err != nil || len(history) != 1 || history[0].VersionID != "version" {
		t.Fatal("legacy scan was not preserved", history, err)
	}
	if err = store.ResetForConnectionChange(); err != nil {
		t.Fatal(err)
	}
	history, err = store.ScanHistory()
	if err != nil || len(history) != 0 {
		t.Fatal("history crossed platform connection", history, err)
	}
}
