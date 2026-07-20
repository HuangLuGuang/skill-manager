package main

import (
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

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
