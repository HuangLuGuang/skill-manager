package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestLoadCachedInventoryRejectsOutdatedCache(t *testing.T) {
	store, err := managedclient.OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SetState("inventory", `{"client_id":"old-client"}`); err != nil {
		t.Fatal(err)
	}
	if _, err := loadCachedInventory(store); err == nil {
		t.Fatal("outdated inventory cache should be rejected")
	}
	if err := store.SaveInventory(managedclient.Inventory{ClientID: "current-client"}); err != nil {
		t.Fatal(err)
	}
	cached, err := loadCachedInventory(store)
	if err != nil || cached.ClientID != "current-client" {
		t.Fatalf("current inventory cache was not loaded: %#v %v", cached, err)
	}
}

func TestTakeoverPreviewUsesCachedInventory(t *testing.T) {
	home := t.TempDir()
	store, err := managedclient.OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInventory(managedclient.Inventory{
		ClientID: "cached-client",
		Agents: []managedclient.Agent{{
			AgentType:                "codex",
			SkillManagementSupported: true,
			Skills:                   []managedclient.Skill{{Name: "cached-skill", Path: "/missing/cached-skill", Signature: "cached-signature"}},
		}},
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/api/v1/clients/cached-client/inventory":
			response.WriteHeader(http.StatusOK)
		case "/api/v1/clients/cached-client/compare":
			_ = json.NewEncoder(response).Encode(map[string]any{"items": []map[string]any{{
				"agent_type": "codex", "name": "cached-skill", "local_path": "/missing/cached-skill",
				"local_signature": "cached-signature", "allowed": false, "reason": "skill_not_found",
			}}})
		default:
			http.NotFound(response, request)
		}
	}))
	defer server.Close()

	if err := run([]string{"takeover", "--home", home, "--server", server.URL, "--token", "token", "--skill", "/missing/cached-skill"}); err != nil {
		t.Fatalf("takeover preview should use cached inventory without reading the missing Skill path: %v", err)
	}
}

func TestFilterInventorySkillsBeforeCompare(t *testing.T) {
	inventory := managedclient.Inventory{Agents: []managedclient.Agent{
		{AgentType: "codex", Skills: []managedclient.Skill{{Path: "/skills/first"}, {Path: "/skills/second"}}},
		{AgentType: "hermes", Skills: []managedclient.Skill{{Path: "/skills/third"}}},
	}}
	filtered, excluded := filterInventorySkills(inventory, []string{"/skills/second"})
	if len(filtered.Agents) != 1 || len(filtered.Agents[0].Skills) != 1 || filtered.Agents[0].Skills[0].Path != "/skills/second" {
		t.Fatalf("unexpected filtered inventory: %#v", filtered.Agents)
	}
	if len(excluded) != 2 {
		t.Fatalf("unexpected exclusions: %#v", excluded)
	}
}
