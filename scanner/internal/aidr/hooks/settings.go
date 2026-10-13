package hooks

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	products "skill-manager/scanner/internal/aidr/catalog"
	"strings"
	"time"
)

func SettingsAdapter(agent string) bool { return hookAdapters[agent].Settings != nil }
func settingsPath(agent, home string) (string, error) {
	product, _ := products.Get(agent)
	format := hookAdapters[agent].Settings
	if format == nil || !products.SupportedHookOS(product) || !filepath.IsAbs(home) {
		return "", code("aidr_plugin_host_unsupported")
	}
	return filepath.Join(home, filepath.FromSlash(format.Path)), nil
}
func shellArg(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\"'\"'") + "'" }
func settingsEntries(agent, binary, connection string) map[string]map[string]any {
	p, _ := products.Get(agent)
	out := map[string]map[string]any{}
	for event := range p.HookEvents {
		out[event] = map[string]any{"command": shellArg(binary) + " aidr-hook --agent " + shellArg(agent) + " --event " + shellArg(event) + " --connection-file " + shellArg(connection), "timeout": hookAdapters[agent].Settings.Timeout}
		if hookAdapters[agent].Settings.Nested {
			out[event]["type"] = "command"
		}
	}
	return out
}
func readSettings(path string) (map[string]json.RawMessage, []byte, os.FileMode, error) {
	for p := filepath.Dir(path); ; p = filepath.Dir(p) {
		st, err := os.Lstat(p)
		if err != nil {
			return nil, nil, 0, err
		}
		if st.Mode()&os.ModeSymlink != 0 {
			return nil, nil, 0, code("aidr_plugin_config_invalid")
		}
		if filepath.Dir(p) == p {
			break
		}
	}
	st, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return map[string]json.RawMessage{}, nil, 0600, nil
	}
	if err != nil {
		return nil, nil, 0, err
	}
	if !st.Mode().IsRegular() || st.Size() > 1<<20 {
		return nil, nil, 0, code("aidr_plugin_config_invalid")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, 0, err
	}
	var doc map[string]json.RawMessage
	if json.Unmarshal(b, &doc) != nil || doc == nil {
		return nil, nil, 0, code("aidr_plugin_config_invalid")
	}
	return doc, b, st.Mode().Perm(), nil
}

// The exact generated command identifies owned entries. Preserve unrelated
// events, hooks, matcher fields and settings, including on repeated installation.
func MergeSettingsHooks(agent, home, binary, connection string, remove bool) (PluginStatus, error) {
	path, err := settingsPath(agent, home)
	if err != nil {
		return PluginStatus{}, err
	}
	if !filepath.IsAbs(binary) || !filepath.IsAbs(connection) {
		return PluginStatus{}, code("aidr_plugin_config_invalid")
	}
	doc, before, mode, err := readSettings(path)
	if err != nil {
		return PluginStatus{}, code("aidr_plugin_source_unreadable")
	}
	if remove && before == nil {
		return InspectSettingsHooks(agent, home, binary, connection)
	}
	var version int
	if raw, ok := doc["version"]; hookAdapters[agent].Settings.Version != 0 && ok && (json.Unmarshal(raw, &version) != nil || version != hookAdapters[agent].Settings.Version) {
		return PluginStatus{}, code("aidr_plugin_interface_unavailable")
	}
	var groups map[string][]map[string]any
	if raw, ok := doc["hooks"]; ok {
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		if decoder.Decode(&groups) != nil || groups == nil {
			return PluginStatus{}, code("aidr_plugin_config_invalid")
		}
	}
	if groups == nil {
		groups = map[string][]map[string]any{}
	}
	changed := false
	for event, entry := range settingsEntries(agent, binary, connection) {
		kept := []map[string]any{}
		for _, existing := range groups[event] {
			if hookAdapters[agent].Settings.Nested {
				children, ok := existing["hooks"].([]any)
				if !ok {
					return PluginStatus{}, code("aidr_plugin_config_invalid")
				}
				remaining := []any{}
				removed := false
				for _, child := range children {
					h, ok := child.(map[string]any)
					if !ok {
						return PluginStatus{}, code("aidr_plugin_config_invalid")
					}
					if h["command"] != entry["command"] {
						remaining = append(remaining, child)
					} else {
						changed = true
						removed = true
					}
				}
				if !removed {
					kept = append(kept, existing)
				} else if len(remaining) > 0 {
					existing["hooks"] = remaining
					kept = append(kept, existing)
				}
				continue
			}
			if existing["command"] != entry["command"] {
				kept = append(kept, existing)
			} else {
				changed = true
			}
		}
		if !remove {
			if hookAdapters[agent].Settings.Nested {
				kept = append(kept, map[string]any{"hooks": []any{entry}})
			} else {
				kept = append(kept, entry)
			}
		}
		if len(kept) == 0 {
			delete(groups, event)
		} else {
			groups[event] = kept
		}
	}
	if remove && !changed {
		return InspectSettingsHooks(agent, home, binary, connection)
	}
	if hookAdapters[agent].Settings.Version != 0 {
		doc["version"], _ = json.Marshal(hookAdapters[agent].Settings.Version)
	}
	doc["hooks"], _ = json.Marshal(groups)
	after, _ := json.MarshalIndent(doc, "", "  ")
	after = append(after, '\n')
	if !bytes.Equal(before, after) {
		f, err := os.CreateTemp(filepath.Dir(path), ".agent-manager-hooks-*")
		if err != nil {
			return PluginStatus{}, code("aidr_plugin_config_write_failed")
		}
		name := f.Name()
		defer os.Remove(name)
		if err = f.Chmod(mode); err == nil {
			_, err = f.Write(after)
		}
		if err == nil {
			err = f.Sync()
		}
		closeErr := f.Close()
		if err != nil || closeErr != nil {
			return PluginStatus{}, code("aidr_plugin_config_write_failed")
		}
		_, current, _, err := readSettings(path)
		if err != nil || !bytes.Equal(before, current) {
			return PluginStatus{}, code("aidr_plugin_config_changed")
		}
		if os.Rename(name, path) != nil {
			return PluginStatus{}, code("aidr_plugin_config_write_failed")
		}
	}
	return InspectSettingsHooks(agent, home, binary, connection)
}

func InspectSettingsHooks(agent, home, binary, connection string) (PluginStatus, error) {
	status := PluginStatus{Agent: agent, VersionStatus: "adapter_available", HookTrust: "unknown", SourceKind: "settings", ReportedAt: time.Now().UTC().Format(time.RFC3339Nano), SourceCode: "aidr_plugin_not_installed"}
	path, err := settingsPath(agent, home)
	if err != nil {
		return status, err
	}
	doc, _, _, err := readSettings(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return status, code("aidr_desktop_host_missing")
		}
		return status, code("aidr_plugin_source_unreadable")
	}
	var groups map[string][]map[string]any
	if raw, ok := doc["hooks"]; ok && json.Unmarshal(raw, &groups) != nil {
		return status, code("aidr_plugin_config_invalid")
	}
	installed := true
	for event, entry := range settingsEntries(agent, binary, connection) {
		count := 0
		for _, existing := range groups[event] {
			if hookAdapters[agent].Settings.Nested {
				children, _ := existing["hooks"].([]any)
				for _, child := range children {
					h, _ := child.(map[string]any)
					if h["command"] == entry["command"] {
						count++
					}
				}
				continue
			}
			if existing["command"] == entry["command"] {
				count++
			}
		}
		if count != 1 {
			installed = false
		}
	}
	status.Installed = &installed
	if installed {
		status.PluginVersion = BundledPluginVersion
		status.PluginID = "agent-manager-settings"
		status.SourceCode = "aidr_hook_configuration_present"
	}
	// Configuration is observable; host trust and actual delivery require events.
	return status, nil
}
