package managedclient

import (
	"archive/zip"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDiagnosticExportOfflineIncludesEvidenceNotCredentials(t *testing.T) {
	root := t.TempDir()
	store, err := OpenStore(filepath.Join(root, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := os.WriteFile(filepath.Join(root, "config.json"), []byte(`{"token":"UNLABELED-CREDENTIAL","connections":[{"server":"https://saved.example","token":"SAVED-UNLABELED-CREDENTIAL"}]}`), 0600); err != nil {
		t.Fatal(err)
	}
	store.SetState("policy", `{"mode":"audit","release_public_key":"public","token":"TOPSECRET"}`)
	store.SaveTask(Task{ID: 21, TaskType: "apply_model_config", Payload: map[string]any{"api_key": "PRIVATEKEY"}}, "failed", "connection_failed")
	store.LogDiagnostic("warning", "test", "failed", map[string]any{"password": "SECRETPASSWORD", "task_id": 21, "error": "request rejected UNLABELED-CREDENTIAL and SAVED-UNLABELED-CREDENTIAL"})
	store.QueueEvent(QueuedEvent{ClientID: "offline-client", EventType: "skill_quarantined", Details: map[string]any{"signature": "signed-content", "token": "OFFLINESECRET"}})
	_, err = store.db.Exec(`UPDATE client_events_queue SET created_at = ?`, "2026-09-12T12:34:56.789Z")
	if err != nil {
		t.Fatal(err)
	}
	path, err := store.ExportDiagnostics(t.TempDir(), 3)
	if err != nil {
		t.Fatal(err)
	}
	archive, err := zip.OpenReader(path)
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	found := map[string]bool{}
	for _, entry := range archive.File {
		found[entry.Name] = true
		r, err := entry.Open()
		if err != nil {
			t.Fatal(err)
		}
		body, _ := io.ReadAll(r)
		r.Close()
		for _, secret := range []string{"TOPSECRET", "PRIVATEKEY", "SECRETPASSWORD", "OFFLINESECRET", "UNLABELED-CREDENTIAL", "SAVED-UNLABELED-CREDENTIAL"} {
			if strings.Contains(string(body), secret) {
				t.Fatal("credential leaked")
			}
		}
		if entry.Name == "summary.json" {
			var summary map[string]any
			if err := json.Unmarshal(body, &summary); err != nil {
				t.Fatal(err)
			}
			events := summary["queued_events"].([]any)
			event := events[0].(map[string]any)
			if event["created_at"] != "2026-09-12T12:34:56.789Z" || event["details"].(map[string]any)["last_seen_at"] != event["created_at"] {
				t.Fatal(event)
			}
		}
		if strings.HasSuffix(entry.Name, ".json") {
			var v any
			if err = json.Unmarshal(body, &v); err != nil {
				t.Fatal(err)
			}
		}
		if entry.Name == "runtime.jsonl" {
			for _, line := range strings.Split(strings.TrimSpace(string(body)), "\n") {
				var v any
				if err = json.Unmarshal([]byte(line), &v); err != nil {
					t.Fatal(err)
				}
			}
		}
	}
	if !found["summary.json"] || !found["runtime.jsonl"] || !found["manifest.json"] {
		t.Fatal(found)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ExportDiagnostics(t.TempDir(), 31); err == nil {
		t.Fatal("invalid range accepted")
	}
}

func TestDiagnosticSnapshotReleasesWriterLockAndRemainsStable(t *testing.T) {
	root := t.TempDir()
	if err := writeDiagnostic(root, DiagnosticRecord{Event: "before_export"}); err != nil {
		t.Fatal(err)
	}
	files, err := diagnosticFiles(root)
	if err != nil || len(files) != 1 {
		t.Fatalf("files: %v, %v", files, err)
	}
	snapshot, err := readDiagnosticSnapshot(root, files[0].path)
	if err != nil {
		t.Fatal(err)
	}
	// A writer must proceed while the exported bytes are being processed.
	if err = writeDiagnostic(root, DiagnosticRecord{Event: "during_export"}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(snapshot), "before_export") || strings.Contains(string(snapshot), "during_export") {
		t.Fatal("snapshot changed after releasing the writer lock")
	}
	file, err := os.OpenFile(files[0].path, os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	err = file.Truncate(diagnosticFileBytes + 1)
	file.Close()
	if err != nil {
		t.Fatal(err)
	}
	if _, err = readDiagnosticSnapshot(root, files[0].path); err == nil {
		t.Fatal("oversized log accepted into memory")
	}
	if _, err = readDiagnosticSnapshot(root, t.TempDir()); err == nil {
		t.Fatal("non-file log accepted")
	}
}
