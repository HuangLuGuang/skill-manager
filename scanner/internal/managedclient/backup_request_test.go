package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestBackupBatchRetryKeepsOriginalRequestsAfterRestart(t *testing.T) {
	home := t.TempDir()
	const backup = "20260911T120000Z"
	for _, name := range []string{"first", "second"} {
		writeSkill(t, filepath.Join(BackupsRoot(home), backup, "codex", name), name)
		writeSkill(t, filepath.Join(home, ".codex", "skills", name), name+"-current")
	}
	dbPath := filepath.Join(home, ".agent-manager", "client.db")
	store, err := OpenStore(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { store.Close() }()
	var mu sync.Mutex
	requests := map[string]SkillActionRequest{}
	calls := map[string]int{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/inventory") {
			w.Write([]byte(`{"ok":true}`))
			return
		}
		var request SkillActionRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
			w.WriteHeader(400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		calls[request.Path]++
		if previous, exists := requests[request.Path]; exists && !reflect.DeepEqual(previous, request) {
			t.Error("retry changed the content-bound request", previous, request)
			w.WriteHeader(409)
			return
		}
		requests[request.Path] = request
		// The platform accepted the second task, but the response was lost.
		if filepath.Base(request.Path) == "second" && calls[request.Path] == 1 {
			w.WriteHeader(503)
			return
		}
		id := int64(1)
		if filepath.Base(request.Path) == "second" {
			id = 2
		}
		json.NewEncoder(w).Encode(Task{ID: id, TaskType: "skill_action"})
	}))
	defer server.Close()
	api := NewAPI(server.URL, "token", time.Second)
	first, err := RequestBackupRestore(context.Background(), home, backup, "batch", api, store)
	if err != nil || len(first.Tasks) != 1 || len(first.Errors) != 1 {
		t.Fatal("expected partial result", first, err)
	}
	// Simulate the accepted task finishing while the desktop is closed.
	writeSkill(t, filepath.Join(home, ".codex", "skills", "first"), "restored-first")
	if _, err := store.db.Exec(`UPDATE client_quarantine SET status='restored',restored_at='completed' WHERE skill_name='first'`); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = OpenStore(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	second, err := RequestBackupRestore(context.Background(), home, backup, "batch", api, store)
	if err != nil || len(second.Tasks) != 2 || len(second.Errors) != 0 || second.Tasks[0].ID != first.Tasks[0].ID {
		t.Fatal("retry failed to reuse accepted tasks", second, err)
	}
	var status, restored string
	if err := store.db.QueryRow(`SELECT status,restored_at FROM client_quarantine WHERE skill_name='first'`).Scan(&status, &restored); err != nil || status != "restored" || restored != "completed" {
		t.Fatal("retry reset a completed recovery record", status, restored, err)
	}
	if _, err := RequestBackupRestore(context.Background(), home, "another-backup", "batch", api, store); err == nil || err.Error() != "backup_request_conflict" {
		t.Fatal("request ID accepted another backup", err)
	}
	if err := store.ResetForConnectionChange(); err != nil {
		t.Fatal(err)
	}
	if _, exists, err := store.State("backup-restore-request:batch"); err != nil || exists {
		t.Fatal("old platform request survived connection reset", exists, err)
	}
}
