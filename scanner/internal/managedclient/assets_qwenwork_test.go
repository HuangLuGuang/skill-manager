package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestQwenWorkLocalInventory(t *testing.T) {
	output := os.Getenv("QWENWORK_TEST_OUTPUT")
	if output == "" {
		t.Skip("requires local QwenWork acceptance")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}
	for _, spec := range adapters() {
		if spec.agentType != "qwenwork" {
			continue
		}
		agent, found, err := discoverAgent(home, spec, DefaultManifestOptions())
		if err != nil || !found || agent.Version != "1.4.0" {
			t.Fatal("local product not discovered", err, agent.Version)
		}
		raw, err := json.MarshalIndent(agent, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(output, "inventory.json"), raw, 0600); err != nil {
			t.Fatal(err)
		}
		return
	}
	t.Fatal("adapter missing")
}

func TestQwenWorkInstalledPackagesKeepEnablementUnknown(t *testing.T) {
	home := t.TempDir()
	putAsset(t, home, ".qwenworkcn/plugins-custom/probe/.qoder-plugin/plugin.json", `{"name":"probe","version":"1"}`)
	putAsset(t, home, ".qwenworkcn/plugins-custom/probe/skills/probe/SKILL.md", "---\nname: probe\ndescription: test\n---\nTest.")
	putAsset(t, home, ".qwenworkcn/plugins/cache/cached/.qoder-plugin/plugin.json", `{"name":"cached"}`)
	putAsset(t, home, "Library/Application Support/QwenWorkCN/identities/test/connectors/config.enc", "DO_NOT_READ")
	x := discoverAssets(home, "qwenwork", nil)
	if !x.PluginSupported || x.MCPSupported || len(x.Plugins) != 1 || x.Plugins[0].Enabled != nil || x.Plugins[0].State != "installed" || len(x.Plugins[0].Skills) != 1 {
		t.Fatal("package state or capability overstated", x)
	}
	raw, _ := json.Marshal(x)
	if strings.Contains(string(raw), "DO_NOT_READ") {
		t.Fatal("encrypted connector store read")
	}
}
