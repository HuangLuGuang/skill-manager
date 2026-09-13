package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPolicySyncPersistsExactVersionAndReportsAcknowledgment(t *testing.T) {
	home, store, inventory, _ := observedFixture(t)
	var report map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.Write([]byte(`{"classification":{"enabled":true,"version":"2:1","rules":{}}}`))
		} else {
			json.NewDecoder(r.Body).Decode(&report)
			w.Write([]byte(`{"status":"succeeded"}`))
		}
	}))
	defer server.Close()
	api := NewAPI(server.URL, "test", time.Second)
	task := Task{ID: 1, TaskType: "sync_policy", Payload: map[string]any{"target_version": "2:1"}}
	if err := executeTask(context.Background(), home, inventory, Policy{}, api, store, task); err != nil {
		t.Fatal(err)
	}
	if cachedPolicy(store).Classification.Version != "2:1" {
		t.Fatal("policy was not persisted")
	}
	if body, err := os.ReadFile(filepath.Join(home, ".agent-manager", "run-now")); err != nil || string(body) != "full" {
		t.Fatalf("inspection was not requested: %s, %v", body, err)
	}
	if err := api.ReportExecutedTask(context.Background(), inventory.ClientID, task, "succeeded", ""); err != nil {
		t.Fatal(err)
	}
	if report["applied_policy_version"] != "2:1" {
		t.Fatal(report)
	}
	task.Payload["target_version"] = "1:0"
	if err := executeTask(context.Background(), home, inventory, Policy{}, api, store, task); err == nil || err.Error() != "policy_superseded" {
		t.Fatalf("obsolete policy accepted: %v", err)
	}
}

func TestDiscoverySyncTaskUpdatesCatalogWithoutHeartbeat(t *testing.T) {
	home, store, inventory, _ := observedFixture(t)
	root := filepath.Join(home, ".qoder-c", "skills")
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		w.Write([]byte(`{"agent_discovery":{"version":"updated","agents":[{"agent_type":"qoder-cn","name":"Qoder CN","enabled":true,"systems":["darwin","linux","windows"],"skill_roots":[".qoder-c/skills"]}]}}`))
	}))
	defer server.Close()
	task := Task{ID: 2, TaskType: "sync_policy", Payload: map[string]any{"agent_discovery_version": "updated"}}
	if err := executeTask(context.Background(), home, inventory, Policy{}, NewAPI(server.URL, "test", time.Second), store, task); err != nil {
		t.Fatal(err)
	}
	fresh, err := Discover(home)
	if err != nil || len(fresh.Agents) != 1 || fresh.Agents[0].SkillsPath != root {
		t.Fatalf("new directory not discovered: %+v, %v", fresh, err)
	}
	if _, err := os.Stat(filepath.Join(home, ".agent-manager", "run-now")); err != nil {
		t.Fatal("rediscovery was not requested", err)
	}
}

func TestTaskReportFailureDoesNotBlockLaterReceipt(t *testing.T) {
	_, store, inventory, _ := observedFixture(t)
	for _, id := range []int64{1, 2} {
		if err := store.SaveTask(Task{ID: id, TaskType: "sync_policy"}, "failed", "test"); err != nil {
			t.Fatal(err)
		}
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/clients/host/tasks/1/result" {
			w.WriteHeader(503)
			return
		}
		w.Write([]byte(`{"status":"failed"}`))
	}))
	defer server.Close()
	if err := flushTaskResults(context.Background(), inventory.ClientID, NewAPI(server.URL, "test", time.Second), store); err == nil {
		t.Fatal("missing delivery error")
	}
	remaining, err := store.UnreportedTasks()
	if err != nil || len(remaining) != 1 || remaining[0].ID != 1 {
		t.Fatalf("later receipt was blocked: %+v, %v", remaining, err)
	}
}
