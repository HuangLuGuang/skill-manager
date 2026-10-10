package hooks

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func nativeCodexLocalPlugins(ctx context.Context, binary, home string) ([]byte, error) {
	// On-demand native diagnostics can refresh Git marketplaces during startup
	// even with this filter. Periodic inspection uses InspectLocalPlugin instead.
	results, err := nativeCodexCallsChecked(ctx, binary, home, []nativeCodexRequest{
		{"plugin/list", map[string]any{"cwds": []string{home}, "forceRefetch": false, "marketplaceKinds": []string{"local"}}},
		{"config/read", map[string]any{"cwd": home, "includeLayers": false}},
	})
	if err != nil {
		return nil, err
	}
	return projectNativeCodexPlugins(results[0], results[1])
}

// Project only our native plugin metadata. Configured IDs absent from the local
// inventory remain unreadable, rather than being mistaken for an empty install.
func projectNativeCodexPlugins(list, config []byte) ([]byte, error) {
	var inventory struct {
		Marketplaces []struct {
			Plugins []struct {
				ID        string  `json:"id"`
				Installed *bool   `json:"installed"`
				Enabled   *bool   `json:"enabled"`
				Version   *string `json:"version"`
				Source    struct {
					Type string `json:"type"`
					Path string `json:"path"`
				} `json:"source"`
			} `json:"plugins"`
		} `json:"marketplaces"`
		Errors []json.RawMessage `json:"marketplaceLoadErrors"`
	}
	var settings struct {
		Config *struct {
			Plugins map[string]json.RawMessage `json:"plugins"`
		} `json:"config"`
	}
	bad := func() ([]byte, error) { return nil, code("aidr_plugin_source_unreadable") }
	if json.Unmarshal(list, &inventory) != nil || inventory.Marketplaces == nil || len(inventory.Marketplaces) > 64 ||
		len(inventory.Errors) > 0 || json.Unmarshal(config, &settings) != nil || settings.Config == nil || len(settings.Config.Plugins) > 512 {
		return bad()
	}
	rows := make([]map[string]any, 0)
	seen := map[string]bool{}
	count := 0
	for _, market := range inventory.Marketplaces {
		if market.Plugins == nil {
			return bad()
		}
		count += len(market.Plugins)
		if count > 512 {
			return bad()
		}
		for _, plugin := range market.Plugins {
			if !strings.HasPrefix(plugin.ID, "aidr-codex@") {
				continue
			}
			if plugin.Installed == nil || plugin.Enabled == nil || seen[plugin.ID] {
				return bad()
			}
			seen[plugin.ID] = true
			if !*plugin.Installed {
				continue
			}
			if plugin.Source.Type != "local" || !filepath.IsAbs(plugin.Source.Path) {
				return bad()
			}
			version := plugin.Version
			if version == nil {
				// This native API reports null for local versions. Read the native
				// reported package manifest; never substitute the bundled version.
				path := filepath.Join(plugin.Source.Path, ".codex-plugin", "plugin.json")
				info, e := os.Lstat(path)
				if e != nil || !info.Mode().IsRegular() {
					return bad()
				}
				file, e := os.Open(path)
				if e != nil {
					return bad()
				}
				data, e := io.ReadAll(io.LimitReader(file, 65537))
				file.Close()
				var manifest struct{ Name, Version string }
				if e != nil || len(data) > 65536 || json.Unmarshal(data, &manifest) != nil || manifest.Name != "aidr-codex" || manifest.Version == "" {
					return bad()
				}
				version = &manifest.Version
			}
			rows = append(rows, map[string]any{"pluginId": plugin.ID, "installed": plugin.Installed, "enabled": plugin.Enabled,
				"version": version, "source": map[string]string{"source": "local", "path": plugin.Source.Path}})
		}
	}
	for id := range settings.Config.Plugins {
		if strings.HasPrefix(id, "aidr-codex@") && !seen[id] {
			return bad()
		}
	}
	return json.Marshal(map[string]any{"installed": rows})
}
