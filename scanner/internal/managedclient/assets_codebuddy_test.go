package managedclient

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCodeBuddyLocalInventory(t *testing.T) {
	home, output := os.Getenv("CODEBUDDY_TEST_HOME"), os.Getenv("CODEBUDDY_TEST_OUTPUT")
	if home == "" || output == "" {
		t.Skip("real IDE inventory not requested")
	}
	for _, spec := range adaptersForHome(home) {
		if spec.agentType != "codebuddy" {
			continue
		}
		agent, found, err := discoverAgent(home, spec, DefaultManifestOptions())
		if err != nil || !found || agent.Capabilities["installed"] != true {
			t.Fatal("IDE not discovered", err)
		}
		raw, err := json.MarshalIndent(agent, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(output, "inventory.json"), raw, 0600); err != nil {
			t.Fatal(err)
		}
		t.Logf("CodeBuddy: plugins=%d MCP=%d", len(agent.AssetInventory.Plugins), len(agent.AssetInventory.MCPServers))
		return
	}
	t.Fatal("CodeBuddy adapter missing")
}

func TestCodeBuddyMarketInstalledMissingDisabledAndProjectAssets(t *testing.T) {
	home := t.TempDir()
	market := filepath.Join(home, ".codebuddy/plugins/marketplaces/official")
	putAsset(t, home, ".codebuddy/settings.json", `{"enabledPlugins":{"active@official":true,"disabled@official":false,"missing@official":true}}`)
	putAsset(t, home, ".codebuddy/plugins/known_marketplaces.json", fmt.Sprintf(`{"official":{"installLocation":%q}}`, market))
	putAsset(t, market, ".codebuddy-plugin/marketplace.json", `{"plugins":[{"name":"active","source":"./plugins/renamed"},{"name":"disabled","source":"./plugins/disabled"},{"name":"cached","source":"./plugins/cached"}]}`)
	for _, name := range []string{"renamed", "disabled", "cached"} {
		putAsset(t, market, "plugins/"+name+"/.codebuddy-plugin/plugin.json", fmt.Sprintf(`{"name":%q,"version":"1.0"}`, name))
		putAsset(t, market, "plugins/"+name+"/SKILL.md", "---\nname: sample\ndescription: test\n---\nSafe.")
	}
	project := filepath.Join(home, "project with spaces")
	putAsset(t, home, "Library/Application Support/CodeBuddy CN/User/workspaceStorage/test/workspace.json", fmt.Sprintf(`{"folder":"file://%s"}`, filepath.ToSlash(project)))
	putAsset(t, project, ".codebuddy/skills/project-skill/SKILL.md", "---\nname: project-skill\ndescription: Test project skill\n---\nSafe.")
	putAsset(t, project, ".mcp.json", `{"mcpServers":{"project-mcp":{"command":"python3","env":{"API_KEY":"SYNTHETIC_SECRET"}}}}`)
	var spec adapter
	for _, a := range adapters() {
		if a.agentType == "codebuddy" {
			spec = a
		}
	}
	agent, found, err := discoverAgent(home, spec, DefaultManifestOptions())
	if err != nil || !found {
		t.Fatal(err)
	}
	x := agent.AssetInventory
	if len(x.Plugins) != 3 || len(x.MCPServers) != 1 || len(agent.Skills) != 1 {
		t.Fatalf("plugins=%d mcp=%d skills=%d", len(x.Plugins), len(x.MCPServers), len(agent.Skills))
	}
	for _, p := range x.Plugins {
		if p.Name == "cached" {
			t.Fatal("market cache treated as installed")
		}
		if p.Name == "missing@official" && (p.State != "configured" || p.Path != "") {
			t.Fatal("missing plugin invented", p)
		}
		if p.Name == "disabled" && (p.Enabled == nil || *p.Enabled) {
			t.Fatal("disabled state lost")
		}
		if p.Name == "renamed" && (len(p.Skills) != 1 || p.State != "installed") {
			t.Fatal("catalog source not resolved")
		}
	}
	raw, _ := json.Marshal(agent)
	if strings.Contains(string(raw), "SYNTHETIC_SECRET") {
		t.Fatal("credential leaked")
	}
}
