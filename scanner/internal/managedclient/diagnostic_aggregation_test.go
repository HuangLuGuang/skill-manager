package managedclient

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func diagnosticTestConfig(t *testing.T, root string) {
	t.Helper()
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	body, _ := json.Marshal(diagnosticUploadConfig{EffectiveLevel: "ERROR", Destination: "test"})
	if err = os.WriteFile(filepath.Join(root, "diagnostic-upload", "config.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestDiagnosticPersistentAggregationAndQuietFlush(t *testing.T) {
	root := t.TempDir()
	diagnosticTestConfig(t, root)
	record := DiagnosticRecord{Time: time.Now().Format(time.RFC3339Nano), Level: "ERROR", Module: "test", Event: "failed", Fields: map[string]any{"error": "ORIGINAL", "request_id": "first"}}
	for i := 0; i < 100; i++ {
		record.Fields["request_id"] = fmt.Sprint(i)
		if err := enqueueDiagnostic(root, record); err != nil {
			t.Fatal(err)
		}
	}
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	var count int
	db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&count)
	if count != 1 {
		t.Fatal("duplicate queue entries", count)
	}
	db.Close()
	// Reopening simulates restart; the final repeated errors must flush even after they stop.
	db, err = diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err = flushDiagnosticGroups(db, "test", time.Now().Add(6*time.Minute)); err != nil {
		t.Fatal(err)
	}
	var raw []byte
	if err = db.QueryRow(`SELECT body FROM records ORDER BY created DESC LIMIT 1`).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	var summary uploadedDiagnostic
	if err = json.Unmarshal(raw, &summary); err != nil {
		t.Fatal(err)
	}
	if summary.Aggregation == nil || summary.Aggregation.RepeatedCount != 99 || summary.Fields["error"] != "ORIGINAL" {
		t.Fatalf("bad summary: %s", raw)
	}
	if err = flushDiagnosticGroups(db, "test", time.Now().Add(7*time.Minute)); err != nil {
		t.Fatal(err)
	}
	db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&count)
	if count != 2 {
		t.Fatal("summary emitted too often", count)
	}
}

func TestDiagnosticErrorRateAndExpiry(t *testing.T) {
	root := t.TempDir()
	diagnosticTestConfig(t, root)
	for i := 0; i < 105; i++ {
		if err := enqueueDiagnostic(root, DiagnosticRecord{Time: time.Now().Format(time.RFC3339Nano), Level: "ERROR", Module: "test", Event: "failed", Fields: map[string]any{"error": fmt.Sprint(i)}}); err != nil {
			t.Fatal(err)
		}
	}
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var count, lost int
	db.QueryRow(`SELECT COUNT(*) FROM records`).Scan(&count)
	db.QueryRow(`SELECT count FROM losses WHERE destination='test'`).Scan(&lost)
	if count != 100 || lost != 5 {
		t.Fatalf("rate cap: queued=%d lost=%d", count, lost)
	}
	tx, _ := db.Begin()
	now := time.Now()
	n, err := diagnosticAllowance(tx, "send:test", 80, now)
	if err != nil || n != 80 {
		t.Fatal(n, err)
	}
	n, err = diagnosticAllowance(tx, "send:test", 80, now.Add(30*time.Second))
	if err != nil || n != 20 {
		t.Fatal(n, err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	tx, _ = db.Begin()
	n, err = diagnosticAllowance(tx, "send:test", 1, now.Add(45*time.Second))
	if err != nil || n != 0 {
		t.Fatal("restart reset budget", n, err)
	}
	n, err = diagnosticAllowance(tx, "send:test", 100, now.Add(61*time.Second))
	if err != nil || n != 100 {
		t.Fatal(n, err)
	}
	tx.Rollback()
	config := diagnosticUploadConfig{EffectiveLevel: "DEBUG", ExpiresAt: now.Add(time.Hour).Format(time.RFC3339Nano)}
	if config.minimum(now) != 10 || config.minimum(now.Add(time.Hour)) != 40 {
		t.Fatal("temporary level did not expire offline")
	}
	config.ExpiresAt = ""
	if config.minimum(now.Add(2*time.Hour)) != 10 {
		t.Fatal("overwrote pre-existing DEBUG config")
	}
}

func TestDiagnosticSyncSuppressionStillAggregates(t *testing.T) {
	root := t.TempDir()
	diagnosticTestConfig(t, root)
	for i := 0; i < 5; i++ {
		recordSyncTransition(root, func(level, module, event string, fields map[string]any) {
			if err := writeDiagnostic(root, DiagnosticRecord{Level: level, Module: module, Event: event, Fields: fields}); err != nil {
				t.Error(err)
			}
		}, "http", fmt.Errorf("same failure"))
	}
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var repeats int
	if err = db.QueryRow(`SELECT repeats FROM error_groups`).Scan(&repeats); err != nil || repeats != 4 {
		t.Fatal(repeats, err)
	}
}

func TestDiagnosticGroupCapacityPreservesNewErrors(t *testing.T) {
	root := t.TempDir()
	diagnosticTestConfig(t, root)
	db, err := diagnosticOutbox(root)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	tx, _ := db.Begin()
	if _, err = tx.Exec(`INSERT INTO losses VALUES ('old',0,0,'epoch')`); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < diagnosticGroupLimit; i++ {
		if _, err = tx.Exec(`INSERT INTO error_groups VALUES ('old',?,'{}','first','last',7,?)`, fmt.Sprint(i), i); err != nil {
			t.Fatal(err)
		}
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if err = enqueueDiagnostic(root, DiagnosticRecord{Time: time.Now().Format(time.RFC3339Nano), Level: "ERROR", Module: "test", Event: "new"}); err != nil {
		t.Fatal(err)
	}
	var groups, queued, lost int
	db.QueryRow(`SELECT COUNT(*) FROM error_groups`).Scan(&groups)
	db.QueryRow(`SELECT COUNT(*) FROM records WHERE destination='test'`).Scan(&queued)
	db.QueryRow(`SELECT count FROM losses WHERE destination='old'`).Scan(&lost)
	if groups != diagnosticGroupLimit || queued != 1 || lost != 7 {
		t.Fatalf("groups=%d queued=%d lost=%d", groups, queued, lost)
	}
}
