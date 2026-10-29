package managedclient

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestZcodeNativeInventory(t *testing.T) {
	home := os.Getenv("ZCODE_TEST_HOME")
	if home == "" {
		t.Skip("requires isolated native runtime")
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	agent, ok := findAgent(inventory, "zcode")
	if !ok {
		t.Fatal("native ZCode missing")
	}
	if len(agent.AssetInventory.MCPServers) != 1 || agent.AssetInventory.MCPServers[0].Name != "aidr_probe" {
		t.Fatal("native MCP config not discovered")
	}
	found := false
	for _, skill := range agent.Skills {
		if skill.Name == "aidr-probe" {
			found = true
		}
	}
	if !found {
		t.Fatal("native Skill not discovered")
	}
	raw, _ := json.MarshalIndent(agent, "", "  ")
	if path := os.Getenv("ZCODE_INVENTORY_EVIDENCE"); path != "" {
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestZcodeAssetsSeparateConfiguredInstalledEnabled(t *testing.T) {
	home, _ := filepath.EvalSymlinks(t.TempDir())
	root := filepath.Join(home, ".zcode/cli")
	plugin := filepath.Join(home, "test-plugin")
	os.MkdirAll(filepath.Join(root, "plugins"), 0700)
	os.MkdirAll(filepath.Join(plugin, ".zcode-plugin"), 0700)
	os.WriteFile(filepath.Join(plugin, ".zcode-plugin/plugin.json"), []byte(`{"name":"probe","version":"1.0"}`), 0600)
	os.WriteFile(filepath.Join(root, "config.json"), []byte(`{"plugins":{"enabledPlugins":{"probe@test":false}},"mcp":{"servers":{"probe":{"command":"python3","args":["local.py"],"env":{"TEST_TOKEN":"must-not-appear"}}}}}`), 0600)
	registry, _ := json.Marshal(map[string]any{"plugins": []any{map[string]any{"id": "probe@test", "installPath": plugin, "scope": "user"}}})
	os.WriteFile(filepath.Join(root, "plugins/installed_plugins.json"), registry, 0600)
	got := discoverAssets(home, "zcode", nil)
	if len(got.Plugins) != 1 || got.Plugins[0].Enabled == nil || *got.Plugins[0].Enabled || len(got.MCPServers) != 1 || got.MCPServers[0].Enabled != nil {
		t.Fatalf("states: %+v", got)
	}
	data, _ := json.Marshal(got)
	if bytes.Contains(data, []byte("must-not-appear")) {
		t.Fatal("credential value leaked")
	}
	for _, b := range got.MCPServers[0].CredentialKeys {
		if b != "env.TEST_TOKEN" {
			t.Fatal(b)
		}
	}
	if got.Plugins[0].Format != "zcode" {
		t.Fatal(got.Plugins[0])
	}
}
