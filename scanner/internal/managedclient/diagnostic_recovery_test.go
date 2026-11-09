package managedclient

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDiagnosticErrorPolicyRecoveryAndRetry(t *testing.T) {
	root := t.TempDir()
	offline := false
	var batches [][]uploadedDiagnostic
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "config") {
			json.NewEncoder(w).Encode(map[string]string{"effective_level": "ERROR"})
			return
		}
		var batch struct {
			Records []uploadedDiagnostic `json:"records"`
		}
		if err := json.NewDecoder(r.Body).Decode(&batch); err != nil {
			t.Error(err)
		}
		batches = append(batches, batch.Records)
		if offline {
			w.WriteHeader(503)
			return
		}
		ids := []string{}
		for _, rec := range batch.Records {
			ids = append(ids, rec.ID)
		}
		json.NewEncoder(w).Encode(map[string]any{"acknowledged": ids})
	}))
	defer server.Close()
	api := API{server: server.URL, http: server.Client()}
	send := func() error { return uploadDiagnostics(context.Background(), api, root, "test") }
	if err := send(); err != nil {
		t.Fatal(err)
	}
	record := func(level, module, event string, fields map[string]any) {
		if err := writeDiagnostic(root, DiagnosticRecord{Level: level, Module: module, Event: event, Fields: fields}); err != nil {
			t.Fatal(err)
		}
	}
	recordSyncTransition(root, record, "test", nil)
	for i := 0; i < 20; i++ {
		recordSyncTransition(root, record, "test", errors.New("connection refused"), map[string]any{"request_id": "first"})
	}
	recordSyncTransition(root, record, "test", nil, map[string]any{"request_id": "recovery"})
	recordSyncTransition(root, record, "test", nil)
	record("info", "test", "ordinary_success", nil)
	offline = true
	if err := send(); err == nil {
		t.Fatal("expected upload failure")
	}
	offline = false
	if err := send(); err != nil {
		t.Fatal(err)
	}
	if err := send(); err != nil {
		t.Fatal(err)
	}
	if len(batches) != 2 || len(batches[0]) != 2 || len(batches[1]) != 2 {
		t.Fatalf("unexpected batches: %+v", batches)
	}
	first, recovery := batches[1][0], batches[1][1]
	if first.Level != "ERROR" || !diagnosticRecovery(recovery.DiagnosticRecord) || recovery.Level != "INFO" || first.Fields["incident_id"] != recovery.Fields["incident_id"] || recovery.Fields["failure_count"] != float64(20) || recovery.Fields["first_request_id"] != "first" || recovery.Fields["request_id"] != "recovery" {
		t.Fatalf("broken correlation: %+v %+v", first, recovery)
	}
	for i := range batches[0] {
		if batches[0][i].ID != batches[1][i].ID {
			t.Fatal("retry ID changed")
		}
	}
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var groups int
	if err = db.QueryRow(`SELECT COUNT(*) FROM error_groups`).Scan(&groups); err != nil || groups != 0 {
		t.Fatal("closed incident left repeat summaries", groups, err)
	}
}

func TestDiagnosticHTTPBusinessDuplicateAndResponseDetail(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	failed := true
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Request-ID") == "" {
			t.Error("missing request ID")
		}
		w.Header().Set("X-Request-ID", "server-request")
		if failed {
			w.WriteHeader(503)
			w.Write([]byte("upstream unavailable"))
			return
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	api := (API{server: server.URL, http: server.Client()}).WithDiagnostics(store)
	err = api.getJSON(context.Background(), "/health", nil)
	if err == nil || !strings.Contains(err.Error(), "upstream unavailable") {
		t.Fatal(err)
	}
	syncError(store, "business", err)
	failed = false
	var result any
	if err = api.getJSON(context.Background(), "/health", &result); err != nil {
		t.Fatal(err)
	}
	syncError(store, "business", nil)
	files, _ := diagnosticFiles(store.root)
	records := 0
	for _, file := range files {
		data, err := os.ReadFile(file.path)
		if err != nil {
			t.Fatal(err)
		}
		records += len(strings.Split(strings.TrimSpace(string(data)), "\n"))
		if !strings.Contains(string(data), "server-request") || !strings.Contains(string(data), "response_detail") {
			t.Fatal(string(data))
		}
	}
	if records != 2 {
		t.Fatalf("HTTP/business duplicate logs: %d", records)
	}
}
