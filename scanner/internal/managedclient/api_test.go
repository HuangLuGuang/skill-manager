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
