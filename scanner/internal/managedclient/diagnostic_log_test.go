package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestDiagnosticRetentionAndSpaceBound(t *testing.T) {
	root := t.TempDir()
	if _, err := SaveLogSettings(root, 7); err != nil {
		t.Fatal(err)
	}
	keep := filepath.Join(root, "retained-backup")
	os.WriteFile(keep, []byte("keep"), 0600)
	for _, name := range []string{"old.jsonl", "recent.jsonl"} {
		path := filepath.Join(logRoot(root), name)
		os.WriteFile(path, make([]byte, 80), 0600)
		if name == "old.jsonl" {
			past := time.Now().Add(-8 * 24 * time.Hour)
			os.Chtimes(path, past, past)
		}
	}
	if err := pruneDiagnosticLogs(root, time.Now(), 7, 30, 100); err != nil {
		t.Fatal(err)
	}
	files, _ := diagnosticFiles(root)
	if len(files) != 0 {
		t.Fatalf("space cap did not remove old files: %v", files)
	}
	if body, err := os.ReadFile(keep); err != nil || string(body) != "keep" {
		t.Fatal("business data touched")
	}
	if _, err := SaveLogSettings(root, 0); err == nil {
		t.Fatal("accepted unlimited retention")
	}
	settings, err := ReadLogSettings(root)
	if err != nil || settings.RetentionDays != 7 {
		t.Fatal(settings, err)
	}
}

func TestDiagnosticConcurrentWritesAndRedaction(t *testing.T) {
	root := t.TempDir()
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			err := writeDiagnostic(root, DiagnosticRecord{Level: "error", Module: "test", Event: "failed", Fields: map[string]any{"token": "SECRET", "error": "Authorization: Bearer TOPSECRET https://user:pass@example.test/path?api_key=HIDDEN", "nested": map[string]any{"password": "PASSWORD"}}})
			if err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	files, err := diagnosticFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, file := range files {
		body, _ := os.ReadFile(file.path)
		for _, secret := range []string{"TOPSECRET", "HIDDEN", "PASSWORD", "user:pass", "\"SECRET\""} {
			if strings.Contains(string(body), secret) {
				t.Fatalf("leaked %s", secret)
			}
		}
		for _, line := range strings.Split(strings.TrimSpace(string(body)), "\n") {
			var record DiagnosticRecord
			if err := json.Unmarshal([]byte(line), &record); err != nil {
				t.Fatal(err)
			}
			if _, err := time.Parse("2006-01-02T15:04:05.000Z07:00", record.Time); err != nil {
				t.Fatal(err)
			}
			count++
		}
	}
	if count != 12 {
		t.Fatal(count)
	}
}

func TestSyncErrorsAreSummarizedAndRecoveryRecorded(t *testing.T) {
	store, err := OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	for i := 0; i < 20; i++ {
		syncError(store, "heartbeat", os.ErrPermission)
	}
	syncError(store, "heartbeat", nil)
	files, _ := diagnosticFiles(store.root)
	body, _ := os.ReadFile(files[0].path)
	lines := strings.Split(strings.TrimSpace(string(body)), "\n")
	if len(lines) != 2 {
		t.Fatalf("duplicate logs: %s", body)
	}
	if !strings.Contains(string(body), `"failure_count":20`) || !strings.Contains(string(body), "sync_recovered") {
		t.Fatal(string(body))
	}
}

func TestDiagnosticFileRotation(t *testing.T) {
	root := t.TempDir()
	if _, err := SaveLogSettings(root, 7); err != nil {
		t.Fatal(err)
	}
	file, err := os.Create(filepath.Join(logRoot(root), "full.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	file.Truncate(diagnosticFileBytes)
	file.Close()
	if err := writeDiagnostic(root, DiagnosticRecord{Level: "info", Module: "test", Event: "next"}); err != nil {
		t.Fatal(err)
	}
	files, _ := diagnosticFiles(root)
	if len(files) != 2 {
		t.Fatal(files)
	}
	for _, file := range files {
		if file.size > diagnosticFileBytes {
			t.Fatal("oversized file")
		}
	}
}

func TestDiagnosticCredentialFormatsAreRedacted(t *testing.T) {
	inputs := []string{
		`Authorization: Basic c2VjcmV0`,
		`token='secret with spaces'`,
		`api_key="secret with \"quoted\" value"`,
		"-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
		`https://user:secret@example.invalid/`,
	}
	for _, input := range inputs {
		output := redactDiagnostic(input)
		if strings.Contains(output, "secret") || strings.Contains(output, "c2VjcmV0") || !strings.Contains(output, "REDACTED") {
			t.Fatalf("unredacted credential format: %q", output)
		}
	}
	for _, key := range []string{"private_key", "Cookie", "refresh_token", "client_secret"} {
		if safeDiagnosticValue(key, "secret") != "[REDACTED]" {
			t.Fatal(key)
		}
	}
}

func TestDiagnosticProductionCapacityRemovesOldestBeforeWriting(t *testing.T) {
	root := t.TempDir()
	if _, err := SaveLogSettings(root, 7); err != nil {
		t.Fatal(err)
	}
	oldest := ""
	for i := 0; i < 20; i++ {
		file, err := os.CreateTemp(logRoot(root), "capacity-*.jsonl")
		if err != nil {
			t.Fatal(err)
		}
		if i == 0 {
			oldest = file.Name()
		}
		err = file.Truncate(diagnosticFileBytes)
		file.Close()
		if err != nil {
			t.Fatal(err)
		}
		at := time.Now().Add(time.Duration(i-20) * time.Second)
		if err := os.Chtimes(file.Name(), at, at); err != nil {
			t.Fatal(err)
		}
	}
	if err := writeDiagnostic(root, DiagnosticRecord{Event: "capacity_boundary"}); err != nil {
		t.Fatal(err)
	}
	settings, err := ReadLogSettings(root)
	if err != nil {
		t.Fatal(err)
	}
	if settings.UsedBytes > diagnosticMaxBytes {
		t.Fatal(settings)
	}
	if _, err := os.Stat(oldest); !os.IsNotExist(err) {
		t.Fatalf("oldest retained: %v", err)
	}
	files, err := diagnosticFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, file := range files {
		if file.size > diagnosticFileBytes {
			t.Fatal(file)
		}
	}
}
