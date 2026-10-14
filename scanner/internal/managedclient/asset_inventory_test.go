package managedclient

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func putAsset(t *testing.T, home, relative, content string) string {
	t.Helper()
	path := filepath.Join(home, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestAssetDiscoveryMCPProductFormatsAndSecrets(t *testing.T) {
	cases := []struct{ kind, path, body string }{
		{"codex", ".codex/config.toml", "[mcp_servers.docs]\nurl='https://user:URL_SECRET@example.com/private/PATH_SECRET?key=QUERY_SECRET'\nhttp_headers={Authorization='HEADER_SECRET'}\nenabled=false\n"},
		{"claude-code", ".claude.json", `{"mcpServers":{"docs":{"command":"node","args":["--token","ARG_SECRET"],"env":{"TOKEN":"ENV_SECRET"}}}}`},
		{"cursor", ".cursor/mcp.json", `{"mcpServers":{"docs":{"url":"https://example.com/mcp","headers":{"Authorization":"HEADER_SECRET"}}}}`},
		{"gemini", ".gemini/settings.json", `{"mcpServers":{"docs":{"command":"node","args":["ARG_SECRET"]}}}`},
		{"opencode", ".config/opencode/opencode.jsonc", `{// comment
"mcp":{"docs":{"type":"local","command":["node","ARG_SECRET"],"environment":{"TOKEN":"ENV_SECRET"}}},}`},
		{"qoder", ".qoder/mcp.json", `{"mcpServers":{"docs":{"url":"https://example.com/mcp"}}}`},
		{"codebuddy", ".codebuddy/.mcp.json", `{"mcpServers":{"docs":{"command":"node"}}}`},
	}
	for _, tc := range cases {
		t.Run(tc.kind, func(t *testing.T) {
			home := t.TempDir()
			putAsset(t, home, tc.path, tc.body)
			inventory := discoverAssets(home, tc.kind, nil)
			if len(inventory.MCPServers) != 1 || inventory.MCPServers[0].Name != "docs" || len(inventory.Issues) != 0 {
				t.Fatalf("unexpected discovery: %+v", inventory)
			}
			body, _ := json.Marshal(inventory)
			if strings.Contains(string(body), "SECRET") {
				t.Fatalf("credential or arguments leaked: %s", body)
			}
			if tc.kind == "codex" && (inventory.MCPServers[0].Enabled == nil || *inventory.MCPServers[0].Enabled || inventory.MCPServers[0].EndpointOrigin != "https://example.com") {
				t.Fatal("state/origin lost")
			}
		})
	}
}

func TestAssetPluginNestedComponentsAndOwnership(t *testing.T) {
	home := t.TempDir()
	pluginRoot := filepath.Join(home, ".claude/plugins/cache/market/example/1")
	putAsset(t, pluginRoot, ".claude-plugin/plugin.json", `{"name":"example","version":"1","mcpServers":{"inline":{"command":"node","env":{"SECRET":"DO_NOT_UPLOAD"}}}}`)
	putAsset(t, pluginRoot, "skills/report/SKILL.md", "---\nname: report\n---\nExample")
	putAsset(t, pluginRoot, ".mcp.json", `{"mcpServers":{"remote":{"url":"https://example.com/mcp?token=DO_NOT_UPLOAD"}}}`)
	putAsset(t, home, ".claude/plugins/installed_plugins.json", fmt.Sprintf(`{"version":2,"plugins":{"example@market":[{"scope":"user","installPath":%q}]}}`, pluginRoot))
	putAsset(t, home, ".claude/settings.json", `{"enabledPlugins":{"example@market":false}}`)
	claude := discoverAssets(home, "claude-code", nil)
	if len(claude.Plugins) != 1 {
		t.Fatalf("registry/cache duplicate: %+v", claude.Plugins)
	}
	plugin := claude.Plugins[0]
	if plugin.State != "installed" || plugin.Enabled == nil || *plugin.Enabled || len(plugin.Skills) != 1 || len(plugin.MCPServers) != 2 {
		t.Fatalf("missing components/state: %+v", plugin)
	}
	if len(claude.MCPServers) != 0 {
		t.Fatal("plugin MCP copied into standalone inventory")
	}
	if len(discoverAssets(home, "cursor", nil).Plugins) != 0 {
		t.Fatal("assets leaked to another Agent")
	}
	body, _ := json.Marshal(claude)
	if strings.Contains(string(body), "DO_NOT_UPLOAD") {
		t.Fatal("plugin secret leaked")
	}
	second := discoverAssets(home, "claude-code", nil)
	if second.Plugins[0].ID != plugin.ID {
		t.Fatal("unstable plugin identity")
	}
}

func TestAssetPluginProductManifests(t *testing.T) {
	for _, tc := range []struct{ kind, root, manifest string }{
		{"codex", ".codex/plugins/cache/vendor/test/1", "plugin.json"},
		{"cursor", ".cursor/plugins/cache/vendor/test/1", ".cursor-plugin/plugin.json"},
		{"qoder", ".qoder/plugins/test", ".qoder-plugin/plugin.json"},
		{"workbuddy", ".workbuddy/plugins/test", ".workbuddy-plugin/plugin.json"},
		{"gemini", ".gemini/extensions/test", "gemini-extension.json"},
		{"openclaw", ".openclaw/extensions/test", "openclaw.plugin.json"},
	} {
		t.Run(tc.kind, func(t *testing.T) {
			home := t.TempDir()
			putAsset(t, home, tc.root+"/"+tc.manifest, `{"name":"test","version":"1"}`)
			putAsset(t, home, tc.root+"/skills/nested/SKILL.md", "# Nested")
			putAsset(t, home, tc.root+"/mcp.json", `{"mcpServers":{"remote":{"url":"https://example.com"}}}`)
			inventory := discoverAssets(home, tc.kind, nil)
			if len(inventory.Plugins) != 1 || len(inventory.Plugins[0].Skills) != 1 || len(inventory.Plugins[0].MCPServers) != 1 {
				t.Fatalf("missing plugin: %+v", inventory)
			}
		})
	}
}

func TestAssetDiscoveryPartialUnsupportedAndBounds(t *testing.T) {
	home := t.TempDir()
	putAsset(t, home, ".cursor/mcp.json", "{bad json")
	partial := discoverAssets(home, "cursor", nil)
	if len(partial.Issues) != 1 || partial.Issues[0].Code != "invalid_config" {
		t.Fatal("parse failure hidden", partial)
	}
	unsupported := discoverAssets(home, "custom-product", nil)
	if unsupported.MCPSupported || unsupported.PluginSupported {
		t.Fatal("unsupported product claimed supported")
	}
	servers := map[string]any{}
	for i := 0; i < assetLimit+1; i++ {
		servers[fmt.Sprint(i)] = map[string]any{"command": "node"}
	}
	body, _ := json.Marshal(map[string]any{"mcpServers": servers})
	putAsset(t, home, ".cursor/mcp.json", string(body))
	bounded := discoverAssets(home, "cursor", nil)
	if len(bounded.MCPServers) != assetLimit || len(bounded.Issues) == 0 {
		t.Fatal("limit silently dropped records")
	}
}

func TestAssetPluginPathEscapeAndNoExecution(t *testing.T) {
	home := t.TempDir()
	outside := t.TempDir()
	putAsset(t, outside, "SKILL.md", "secret outside")
	pluginRoot := filepath.Join(home, ".cursor/plugins/test")
	putAsset(t, pluginRoot, ".cursor-plugin/plugin.json", fmt.Sprintf(`{"name":"test","skills":%q,"mcpServers":"../../../private.json"}`, outside))
	putAsset(t, pluginRoot, "hooks/hooks.json", `{"hooks":{"sessionStart":[{"command":"touch SHOULD_NEVER_RUN"}]}}`)
	result := discoverAssets(home, "cursor", nil)
	if len(result.Plugins) != 1 || len(result.Plugins[0].Skills) != 0 || len(result.Issues) == 0 {
		t.Fatal("outside package traversed", result)
	}
	if _, err := os.Stat(filepath.Join(pluginRoot, "SHOULD_NEVER_RUN")); !os.IsNotExist(err) {
		t.Fatal("hook executed")
	}
}

func TestAssetHomeProjectDoesNotDuplicateUserMCP(t *testing.T) {
	home := t.TempDir()
	project := t.TempDir()
	putAsset(t, home, ".codex/config.toml", fmt.Sprintf("[mcp_servers.docs]\ncommand='node'\n[projects.%q]\ntrust_level='trusted'\n[projects.%q]\ntrust_level='trusted'\n", home, project))
	putAsset(t, project, ".codex/config.toml", "[mcp_servers.docs]\ncommand='python'\n")
	inventory := discoverAssets(home, "codex", nil)
	if len(inventory.MCPServers) != 2 || inventory.MCPServers[0].Scope != "user" || inventory.MCPServers[1].Scope != project {
		t.Fatalf("user config must be counted once while distinct project config remains: %+v", inventory.MCPServers)
	}
}

func TestAssetProjectScopeAndCodexMarketplace(t *testing.T) {
	home := t.TempDir()
	project := filepath.Join(home, "work")
	putAsset(t, home, ".claude.json", fmt.Sprintf(`{"projects":{%q:{"mcpServers":{"local":{"command":"node"}}}}}`, project))
	putAsset(t, project, ".mcp.json", `{"mcpServers":{"project":{"command":"python"}}}`)
	result := discoverAssets(home, "claude-code", nil)
	if len(result.MCPServers) != 2 {
		t.Fatal("project sources missing", result)
	}
	for _, mcp := range result.MCPServers {
		if mcp.Scope != project {
			t.Fatal("project attribution missing")
		}
	}
	market := filepath.Join(home, "market")
	putAsset(t, market, ".agents/plugins/marketplace.json", `{"plugins":[{"name":"test","source":{"source":"local","path":"./plugins/test"}}]}`)
	putAsset(t, market, "plugins/test/.codex-plugin/plugin.json", `{"name":"test"}`)
	putAsset(t, market, "plugins/test/skills/example/SKILL.md", "# Skill")
	putAsset(t, market, "plugins/test/.app.json", `{"apps":{"issues":{"id":"registered-issues","required":true}}}`)
	putAsset(t, home, ".codex/config.toml", fmt.Sprintf("[plugins.\"test@local\"]\nenabled=true\n[marketplaces.local]\nsource_type='local'\nsource=%q\n", market))
	codex := discoverAssets(home, "codex", nil)
	if len(codex.Plugins) != 1 || len(codex.Plugins[0].Skills) != 1 || codex.Plugins[0].Enabled == nil || !*codex.Plugins[0].Enabled {
		t.Fatal("marketplace plugin missing", codex)
	}
	if len(codex.Plugins[0].MCPServers) != 1 || codex.Plugins[0].MCPServers[0].Transport != "registered" || codex.Plugins[0].MCPServers[0].ServerReference != "registered-issues" {
		t.Fatal("registered MCP dependency missing")
	}
}

func TestDiscoverReportsMCPOnlyAgent(t *testing.T) {
	home := t.TempDir()
	putAsset(t, home, ".cursor/mcp.json", `{"mcpServers":{"docs":{"command":"node"}}}`)
	result, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	agent, ok := findAgent(result, "cursor")
	if !ok || agent.AssetInventory == nil || len(agent.AssetInventory.MCPServers) != 1 {
		t.Fatal("MCP-only Agent was not discovered")
	}
}
