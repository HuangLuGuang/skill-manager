package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDiagnosticUploadRetryRawAndAcknowledgement(t *testing.T) {
	root := t.TempDir()
	level := "WARN"
	fail := true
	var ids []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "config") {
			json.NewEncoder(w).Encode(map[string]string{"effective_level": level})
			return
		}
		var batch struct {
			Records []uploadedDiagnostic `json:"records"`
		}
		if err := json.NewDecoder(r.Body).Decode(&batch); err != nil {
			t.Error(err)
		}
		if len(batch.Records) != 1 {
			t.Errorf("unexpected batch: %v", batch)
			w.WriteHeader(500)
			return
		}
		rec := batch.Records[0]
		if rec.Fields["token"] != "ORIGINAL" {
			t.Errorf("original content lost: %v", rec)
		}
		ids = append(ids, rec.ID)
		if fail {
			w.WriteHeader(503)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"acknowledged": []string{rec.ID, "unsent"}})
	}))
	defer server.Close()
	api := API{server: server.URL, http: server.Client()}
	ctx := context.Background()
	if err := uploadDiagnostics(ctx, api, root, "test"); err != nil {
		t.Fatal(err)
	}
	if err := writeDiagnostic(root, DiagnosticRecord{Level: "info", Module: "test", Event: "ignored"}); err != nil {
		t.Fatal(err)
	}
	if err := writeDiagnostic(root, DiagnosticRecord{Level: "error", Module: "test", Event: "failure", Fields: map[string]any{"token": "ORIGINAL"}}); err != nil {
		t.Fatal(err)
	}
	if err := uploadDiagnostics(ctx, api, root, "test"); err == nil {
		t.Fatal("expected offline failure")
	}
	files, _ := diagnosticFiles(root)
	for _, file := range files {
		body, _ := os.ReadFile(file.path)
		if strings.Contains(string(body), "ORIGINAL") {
			t.Fatal("changed existing local export redaction")
		}
	}
	fail = false
	if err := uploadDiagnostics(ctx, api, root, "test"); err != nil {
		t.Fatal(err)
	}
	if len(ids) != 2 || ids[0] != ids[1] {
		t.Fatalf("unstable retry identity: %v", ids)
	}
	if err := uploadDiagnostics(ctx, api, root, "test"); err != nil {
		t.Fatal(err)
	}
	if len(ids) != 2 {
		t.Fatal("acknowledged record resent")
	}
	level = "OFF"
	if err := uploadDiagnostics(ctx, api, root, "test"); err != nil {
		t.Fatal(err)
	}
	if err := writeDiagnostic(root, DiagnosticRecord{Level: "error", Module: "test", Event: "disabled"}); err != nil {
		t.Fatal(err)
	}
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var count int
	db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&count)
	if count != 0 {
		t.Fatal("disabled upload enqueued records")
	}
}

func TestDiagnosticQueuePriorityBoundAndDestination(t *testing.T) {
	root := t.TempDir()
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	cfg, _ := json.Marshal(diagnosticUploadConfig{EffectiveLevel: "DEBUG", Destination: "original"})
	if err = os.WriteFile(filepath.Join(root, "diagnostic-upload", "config.json"), cfg, 0600); err != nil {
		t.Fatal(err)
	}
	tx, _ := db.Begin()
	for i := 0; i < diagnosticQueueLimit; i++ {
		tx.Exec(`INSERT INTO records VALUES(?, 'original',40,'{}',?)`, time.Unix(0, int64(i)).String(), i)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if err = enqueueDiagnostic(root, DiagnosticRecord{Level: "DEBUG", Module: "test", Event: "low"}); err != nil {
		t.Fatal(err)
	}
	var count, lost int
	db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&count)
	db.QueryRow(`SELECT count FROM losses WHERE destination='original'`).Scan(&lost)
	if count != diagnosticQueueLimit || lost != 1 {
		t.Fatalf("queue bound/drop reporting: %d %d", count, lost)
	}
	var posts int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			posts++
		}
		json.NewEncoder(w).Encode(map[string]string{"effective_level": "ERROR"})
	}))
	defer server.Close()
	if err = uploadDiagnostics(context.Background(), API{server: server.URL, http: server.Client()}, root, "different"); err != nil {
		t.Fatal(err)
	}
	if posts != 0 {
		t.Fatal("sent old destination logs to new platform")
	}
}
