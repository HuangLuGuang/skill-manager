package hooks

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
)

// InspectLocalPlugin observes user-scoped configuration and product files without
// starting the host. It does not establish native interface compatibility or trust.
func InspectLocalPlugin(ctx context.Context, agent, home, socket string) (PluginStatus, error) {
	s := PluginStatus{Agent: agent, HookTrust: "unknown", VersionStatus: "unverified", SourceCode: "aidr_plugin_source_unreadable", SourceKind: "unknown", FilesCode: "aidr_plugin_files_unknown", ReceiverCode: "aidr_hook_receiver_not_checked", ReportedAt: time.Now().UTC().Format(time.RFC3339Nano)}
	if home == "" {
		key := "CODEX_HOME"
		if agent == "claude" {
			key = "CLAUDE_CONFIG_DIR"
		}
		home = os.Getenv(key)
		if home == "" {
			userHome, err := os.UserHomeDir()
			if err != nil {
				return s, code("aidr_plugin_config_invalid")
			}
			home = filepath.Join(userHome, "."+agent)
		}
	}
	if (agent != "codex" && agent != "claude") || !filepath.IsAbs(home) {
		return s, code("aidr_plugin_config_invalid")
	}
	if err := ctx.Err(); err != nil {
		return s, err
	}
	scope, _ := json.Marshal([]any{agent, os.Geteuid(), filepath.Clean(home)})
	sum := sha256.Sum256(scope)
	s.ScopeDigest = hex.EncodeToString(sum[:])
	var raw []byte
	var err error
	if agent == "codex" {
		raw, err = localCodexPlugins(home)
	} else {
		raw, err = localClaudePlugins(home)
	}
	if err == nil {
		parsed, e := ParsePluginStatus(agent, raw)
		if e == nil {
			parsed.ScopeDigest, parsed.ReportedAt, parsed.ReceiverCode = s.ScopeDigest, s.ReportedAt, s.ReceiverCode
			parsed.VersionStatus = "adapter_available"
			s = parsed
			if s.Installed != nil && *s.Installed && s.sourcePath != "" {
				s.FilesDigest, s.FilesCode = pluginFilesDigest(agent, s.sourcePath)
			}
		}
	}
	if socket != "" {
		reply, e := Exchange(ctx, socket, IPCRequest{Version: 1, Method: "GetHealth"})
		if e != nil {
			s.ReceiverCode = "aidr_hook_receiver_unavailable"
		} else {
			s.ReceiverCode = reply.Code
		}
	}
	return s, nil
}

func readPluginMetadata(path string) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return nil, code("aidr_plugin_source_unreadable")
	}
	raw, err := io.ReadAll(io.LimitReader(f, 2<<20+1))
	if err != nil || len(raw) > 2<<20 {
		return nil, code("aidr_plugin_source_unreadable")
	}
	return raw, nil
}

func localPluginVersion(agent, root string) (string, error) {
	raw, err := readPluginMetadata(filepath.Join(root, "."+agent+"-plugin", "plugin.json"))
	if err != nil {
		return "", err
	}
	var manifest struct{ Name, Version string }
	if json.Unmarshal(raw, &manifest) != nil || manifest.Name != "aidr-"+agent || manifest.Version == "" || len(manifest.Version) > 80 {
		return "", code("aidr_plugin_source_unreadable")
	}
	return manifest.Version, nil
}

func localCodexPlugins(home string) ([]byte, error) {
	raw, err := readPluginMetadata(filepath.Join(home, "config.toml"))
	if err != nil {
		return nil, err
	}
	var config struct {
		Plugins      map[string]struct{ Enabled *bool }
		Marketplaces map[string]struct {
			SourceType string `toml:"source_type"`
			Source     string
		}
	}
	if _, err = toml.Decode(string(raw), &config); err != nil {
		return nil, err
	}
	rows := []map[string]any{}
	for id, plugin := range config.Plugins {
		market, ours := strings.CutPrefix(id, "aidr-codex@")
		if !ours {
			continue
		}
		source, ok := config.Marketplaces[market]
		if !ok || source.SourceType != "local" || !filepath.IsAbs(source.Source) || plugin.Enabled == nil {
			return nil, code("aidr_plugin_source_unreadable")
		}
		raw, err := readPluginMetadata(filepath.Join(source.Source, ".agents/plugins/marketplace.json"))
		if err != nil {
			return nil, err
		}
		var catalog struct {
			Name    string
			Plugins []struct {
				Name   string
				Source struct{ Source, Path string }
			}
		}
		if json.Unmarshal(raw, &catalog) != nil || catalog.Name != market || catalog.Plugins == nil {
			return nil, code("aidr_plugin_source_unreadable")
		}
		root := ""
		for _, entry := range catalog.Plugins {
			if entry.Name != "aidr-codex" {
				continue
			}
			if root != "" || entry.Source.Source != "local" || entry.Source.Path == "" {
				return nil, code("aidr_plugin_source_unreadable")
			}
			root = entry.Source.Path
			if !filepath.IsAbs(root) {
				root = filepath.Join(source.Source, root)
			}
		}
		if root == "" {
			return nil, code("aidr_plugin_source_unreadable")
		}
		version, err := localPluginVersion("codex", root)
		if err != nil {
			return nil, err
		}
		rows = append(rows, map[string]any{"pluginId": id, "installed": true, "enabled": *plugin.Enabled, "version": version,
			"source": map[string]string{"source": "local", "path": root}})
	}
	return json.Marshal(map[string]any{"installed": rows})
}

func localClaudePlugins(home string) ([]byte, error) {
	raw, err := readPluginMetadata(filepath.Join(home, "plugins/installed_plugins.json"))
	if err != nil {
		return nil, err
	}
	var inventory struct {
		Version int
		Plugins map[string][]struct{ Scope, InstallPath, Version string }
	}
	if json.Unmarshal(raw, &inventory) != nil || inventory.Version != 2 || inventory.Plugins == nil {
		return nil, code("aidr_plugin_source_unreadable")
	}
	raw, err = readPluginMetadata(filepath.Join(home, "settings.json"))
	if err != nil {
		return nil, err
	}
	var settings struct{ EnabledPlugins map[string]*bool }
	if json.Unmarshal(raw, &settings) != nil || strings.TrimSpace(string(raw)) == "null" {
		return nil, code("aidr_plugin_source_unreadable")
	}
	rows := []map[string]any{}
	seen := map[string]bool{}
	for id, installs := range inventory.Plugins {
		if !strings.HasPrefix(id, "aidr-claude@") {
			continue
		}
		for _, install := range installs {
			if install.Scope != "user" {
				continue
			}
			if !filepath.IsAbs(install.InstallPath) || settings.EnabledPlugins[id] == nil {
				return nil, code("aidr_plugin_source_unreadable")
			}
			version, err := localPluginVersion("claude", install.InstallPath)
			if err != nil || version != install.Version {
				return nil, code("aidr_plugin_source_unreadable")
			}
			seen[id] = true
			rows = append(rows, map[string]any{"id": id, "enabled": *settings.EnabledPlugins[id], "version": version, "installPath": install.InstallPath})
		}
	}
	for id := range settings.EnabledPlugins {
		if strings.HasPrefix(id, "aidr-claude@") && !seen[id] {
			return nil, code("aidr_plugin_source_unreadable")
		}
	}
	return json.Marshal(rows)
}
