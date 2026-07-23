package main

import (
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
