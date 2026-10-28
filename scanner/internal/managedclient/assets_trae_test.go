package managedclient

import (
	"encoding/json"
	"fmt"
	"net/url"
	"path/filepath"
	"strings"
	"testing"
)

func TestTraeAssetsIncludePluginsExtensionsAndProjects(t *testing.T) {
	for _, kind := range []string{"trae", "trae-cn"} {
		home := t.TempDir()
		root := "." + kind
		data := traeDataRoot(home, kind)
		putAsset(t, data, "User/mcp.json", `{"mcpServers":{"global":{"url":"https://example.com/mcp?token=SECRET","headers":{"Authorization":"SECRET"},"disabled":true}}}`)
		project := filepath.Join(home, "project with spaces")
		u := url.URL{Scheme: "file", Path: project}
		putAsset(t, data, "User/workspaceStorage/a/workspace.json", fmt.Sprintf(`{"folder":%q}`, u.String()))
		putAsset(t, project, ".trae/mcp.json", `{"mcpServers":{"local":{"command":"node","args":["SECRET"]}}}`)
		plugin := filepath.Join(home, root, "plugins/official/example/1")
		putAsset(t, plugin, ".trae-plugin/plugin.json", `{"name":"example","version":"1","skills":"./skills/"}`)
		putAsset(t, plugin, "skills/demo/SKILL.md", "---\nname: demo\n---\nSynthetic skill")
		putAsset(t, plugin, ".mcp.json", `{"mcpServers":{"plugin-tool":{"command":"node"}}}`)
		putAsset(t, home, root+"/installed-plugins.json", fmt.Sprintf(`{"data":{"marketplaces":[{"plugins":[{"plugin_id":"official:example","source":{"path":%q}}]}]}}`, plugin))
		putAsset(t, home, root+"/plugin-config.json", `{"plugins":{"official:example":{"user_enabled":true,"app_origin_enabled":false}}}`)
		putAsset(t, home, root+"/extensions/test.ext-1/package.json", `{"publisher":"test","name":"ext","version":"1"}`)
		a := discoverAssets(home, kind, nil)
		if len(a.MCPServers) != 2 || len(a.Plugins) != 2 {
			t.Fatalf("%+v", a)
		}
		p := a.Plugins[0]
		if p.Enabled == nil || *p.Enabled || p.Format != "trae" || len(p.Skills) != 1 || len(p.MCPServers) != 1 {
			t.Fatalf("%+v", p)
		}
		if a.Plugins[1].Format != "vscode_extension" || a.Plugins[1].Enabled != nil {
			t.Fatal("extension state invented")
		}
		wire, _ := json.Marshal(a)
		if strings.Contains(string(wire), "SECRET") {
			t.Fatal("credential leaked")
		}
	}
}

func TestTraePluginCannotEscapeProductRoot(t *testing.T) {
	home := t.TempDir()
	outside := t.TempDir()
	putAsset(t, outside, ".trae-plugin/plugin.json", `{"name":"outside","version":"1"}`)
	putAsset(t, home, ".trae/installed-plugins.json", fmt.Sprintf(`{"data":{"marketplaces":[{"plugins":[{"plugin_id":"bad","source":{"path":%q}}]}]}}`, outside))
	a := discoverAssets(home, "trae", nil)
	if len(a.Plugins) != 1 || a.Plugins[0].Path != "" || a.Plugins[0].Name == "outside" {
		t.Fatalf("%+v", a)
	}
	if len(a.Issues) == 0 {
		t.Fatal("escape not reported")
	}
}
