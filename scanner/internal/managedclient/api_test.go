package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestRegisterSendsClientTokenAndInventory(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/api/v1/clients/register" {
			t.Fatalf("unexpected path %s", request.URL.Path)
		}
		if request.Header.Get("Authorization") != "Bearer secret" {
			t.Fatalf("unexpected authorization %q", request.Header.Get("Authorization"))
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	err := NewAPI(server.URL, "secret", time.Second).Register(
		context.Background(),
		Inventory{ClientID: "client-1", Agents: []Agent{}},
	)
	if err != nil {
		t.Fatal(err)
	}
}

func TestWaitTasksReturnsUpdateVersionsFromLongPoll(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		w.Header().Set("X-Agent-Manager-Client-Stable-Version", "26.9.1403")
		w.Header().Set("X-Agent-Manager-Client-Preview-Version", "26.9.1404")
		_ = json.NewEncoder(w).Encode([]Task{})
	}))
	defer server.Close()
	tasks, versions, err := NewAPI(server.URL, "secret", time.Second).WaitTasksWithUpdates(context.Background(), "client-1", 0)
	if err != nil || len(tasks) != 0 || versions.Stable != "26.9.1403" || versions.Preview != "26.9.1404" {
		t.Fatalf("unexpected long-poll result tasks=%#v versions=%#v err=%v", tasks, versions, err)
	}
}

func TestWaitTasksWithScansDecodesDurableScanEvents(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.URL.Query().Get("scan_ids") != "version-1" || request.URL.Query().Get("scan_after_revision") != "7" {
			t.Fatalf("unexpected scan cursor: %s", request.URL.RawQuery)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"tasks":       []map[string]any{},
			"scan_events": []map[string]any{{"revision": 8, "skill_id": "family-1", "version_id": "version-1", "status": "APPROVED"}},
		})
	}))
	defer server.Close()
	_, _, events, err := NewAPI(server.URL, "secret", time.Second).WaitTasksWithUpdatesAndScans(context.Background(), "client-1", 0, []string{"version-1"}, 7)
	if err != nil || len(events) != 1 || events[0].Revision != 8 || events[0].Status != "APPROVED" {
		t.Fatalf("unexpected scan events=%#v err=%v", events, err)
	}
}

func TestAvailableSkillsSendsExactSkillQuery(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/api/v1/clients/client-1/skills/available" {
			t.Fatalf("unexpected path %s", request.URL.Path)
		}
		query := request.URL.Query()
		if query.Get("agent_type") != "codex" || query.Get("managed_agent_id") != "agent-1" {
			t.Fatalf("unexpected agent query %s", request.URL.RawQuery)
		}
		if query.Get("skill_id") != "family-old" || query.Get("q") != "" {
			t.Fatalf("unexpected skill query %s", request.URL.RawQuery)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"items": []map[string]any{{"skill_id": "family-old", "name": "older-skill"}},
		})
	}))
	defer server.Close()

	items, err := NewAPI(server.URL, "secret", time.Second).AvailableSkills(
		context.Background(),
		"client-1",
		"codex",
		"agent-1",
		"",
		"family-old",
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].SkillID != "family-old" {
		t.Fatalf("unexpected items %#v", items)
	}
}

func TestRequestModelConfigurationSendsLocalTargetWithoutExposingCredential(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/api/v1/clients/client-1/model-configurations" {
			t.Fatalf("unexpected path %s", request.URL.Path)
		}
		var body map[string]any
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["local_agent_id"] != "codex" || body["agent_type"] != "codex" || body["managed_agent_id"] != "agent-1" || body["model"] != "gpt-managed" {
			t.Fatalf("unexpected request body %#v", body)
		}
		if _, exposed := body["token"]; exposed {
			t.Fatalf("credential leaked into request body: %#v", body)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"id": 12, "task_type": "apply_model_config", "payload": body})
	}))
	defer server.Close()

	task, err := NewAPI(server.URL, "secret", time.Second).RequestModelConfiguration(context.Background(), "client-1", "codex", "codex", "agent-1", "gpt-managed")
	if err != nil || task.ID != 12 || task.TaskType != "apply_model_config" {
		t.Fatalf("unexpected task %#v err=%v", task, err)
	}
}
