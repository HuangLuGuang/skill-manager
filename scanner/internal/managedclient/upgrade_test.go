package managedclient

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestUpgradePreservesLegacyDataAndEnablesClassifiedEnrollment(t *testing.T) {
	home := t.TempDir()
	databasePath := filepath.Join(home, ".agent-manager", "client.db")
	if err := os.MkdirAll(filepath.Dir(databasePath), 0700); err != nil {
		t.Fatal(err)
	}
	schema, err := os.ReadFile("testdata/client-store-before-classification.sql")
	if err != nil {
		t.Fatal(err)
	}
	legacy, err := sql.Open("sqlite", databasePath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := legacy.Exec(string(schema)); err != nil {
		t.Fatal(err)
	}
	active := filepath.Join(home, ".codex", "skills", "newly-discovered")
	quarantine := filepath.Join(QuarantineRoot(home), "old-quarantine", "sample")
	pending := filepath.Join(PendingRoot(home), "codex", "old-pending")
	backup := filepath.Join(BackupsRoot(home), "before-upgrade", "sample")
	for _, path := range []string{active, quarantine, pending, backup} {
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(path, "SKILL.md"), []byte("---\nname: sample\n---\nretained content"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	statements := []struct {
		query string
		args  []any
	}{
		{`INSERT INTO client_state VALUES('governance_enabled','0','2026-09-01')`, nil},
		{`INSERT INTO client_state VALUES('policy','{"mode":"repair"}','2026-09-01')`, nil},
		{`INSERT INTO client_tasks(task_id,status,updated_at,task_json) VALUES(9,'pending','2026-09-01','{"id":9,"task_type":"rescan","payload":{}}')`, nil},
		{`INSERT INTO client_quarantine(id,agent_type,skill_name,original_path,quarantine_path,reason,status,created_at) VALUES('old-copy','codex','sample',?,?,'unmanaged_skill','quarantined','2026-09-01')`, []any{filepath.Join(home, ".codex", "skills", "sample"), quarantine}},
		{`INSERT INTO client_pending(id,agent_type,skill_name,original_path,pending_path,reason,status,skill_id,version_id,created_at) VALUES('old-pending','codex','sample',?,?,'takeover','PENDING','family','version','2026-09-01')`, []any{active, pending}},
	}
	for _, statement := range statements {
		if _, err := legacy.Exec(statement.query, statement.args...); err != nil {
			t.Fatal(err)
		}
	}
	if err := legacy.Close(); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(databasePath)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	policy := cachedPolicy(store)
	if policy.Mode != "repair" || classificationEnabled(policy) {
		t.Fatal("upgrade changed the administrator policy", policy)
	}
	items, err := store.PendingItems()
	if err != nil || len(items) != 1 || items[0].VersionID != "version" || items[0].Status != "PENDING" {
		t.Fatal("pending scan lost", items, err)
	}
	copies, err := store.QuarantineItems()
	if err != nil || len(copies) != 1 || copies[0].ID != "old-copy" {
		t.Fatal("quarantine lost", copies, err)
	}
	tasks, err := store.PendingTasks()
	if err != nil || len(tasks) != 1 || tasks[0].ID != 9 {
		t.Fatal("pending task lost", tasks, err)
	}
	policy.Classification = DefaultClassificationPolicy()
	body, err := json.Marshal(policy)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SetState("policy", string(body)); err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInventory(inventory); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "offline", http.StatusServiceUnavailable) }))
	defer server.Close()
	if err := patrol(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, true, false); err != nil {
		t.Fatal(err)
	}
	observation, err := store.Observation(active)
	if err != nil || observation.Signature == "" || observation.Action != "record" {
		t.Fatal("old pause prevented classified enrollment", observation, err)
	}
	for _, path := range []string{active, quarantine, pending, backup} {
		body, err := os.ReadFile(filepath.Join(path, "SKILL.md"))
		if err != nil || string(body) != "---\nname: sample\n---\nretained content" {
			t.Fatal("upgrade changed files", path, err)
		}
	}
}
