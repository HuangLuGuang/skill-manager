package hooks

import (
	"bytes"
	"encoding/json"
	"reflect"
	"runtime"
	"sort"
	"strings"

	"github.com/BurntSushi/toml"
)

const managedConfigLimit = 256 << 10

type ManagedLayout struct {
	Root   string
	Binary string
	Config string
}

// Paths are product-owned system locations, never supplied by a task or CLI.
func SystemManagedLayout(agent string) (ManagedLayout, error) {
	root := "/Library/Application Support/AgentManagerRuntime/managed"
	config := "/etc/codex/requirements.toml"
	if runtime.GOOS == "linux" {
		root = "/opt/agent-manager/managed"
		if agent == "claude" {
			config = "/etc/claude-code/managed-settings.json"
		}
	} else if runtime.GOOS == "darwin" {
		if agent == "claude" {
			config = "/Library/Application Support/ClaudeCode/managed-settings.json"
		}
	} else {
		return ManagedLayout{}, code("aidr_managed_platform_unsupported")
	}
	if agent != "codex" && agent != "claude" {
		return ManagedLayout{}, code("aidr_plugin_host_unsupported")
	}
	return ManagedLayout{Root: root, Binary: root + "/agent-manager-client", Config: config}, nil
}

func managedCommand(layout ManagedLayout, agent, event string) string {
	return shellQuote(layout.Binary) + " aidr-hook --managed-connection --agent " + agent + " --event " + event
}

func managedEntries(layout ManagedLayout, agent string) map[string]map[string]any {
	result := map[string]map[string]any{}
	for event := range catalog[agent] {
		timeout := 60
		if agent == "codex" && (event == "SessionEnd" || event == "Interrupt") {
			timeout = 3
		}
		result[event] = map[string]any{"hooks": []any{map[string]any{"type": "command", "command": managedCommand(layout, agent, event), "timeout": timeout}}}
	}
	return result
}

// Semantic round trips preserve other administrators' values. Only exact,
// product-owned entries may be removed; later additions are retained.
func mergeManagedConfig(raw []byte, agent string, layout ManagedLayout, install bool, owned bool) ([]byte, bool, error) {
	if len(raw) > managedConfigLimit {
		return nil, false, code("aidr_managed_config_oversized")
	}
	data := map[string]any{}
	if len(bytes.TrimSpace(raw)) > 0 {
		if agent == "codex" {
			if _, err := toml.Decode(string(raw), &data); err != nil {
				return nil, false, code("aidr_managed_config_invalid")
			}
		} else if json.Unmarshal(raw, &data) != nil || data == nil {
			return nil, false, code("aidr_managed_config_invalid")
		}
	}
	hooks, err := managedTable(data, "hooks")
	if err != nil {
		return nil, false, err
	}
	entries := managedEntries(layout, agent)
	addedFeature := false
	if agent == "codex" {
		if dir, exists := hooks["managed_dir"]; exists && dir != layout.Root {
			return nil, false, code("aidr_managed_config_conflict")
		}
		features, err := managedTable(data, "features")
		if err != nil {
			return nil, false, err
		}
		if install {
			if value, present := features["hooks"]; present && value != true {
				return nil, false, code("aidr_managed_config_conflict")
			}
			_, present := features["hooks"]
			addedFeature = !present
			features["hooks"] = true
			hooks["managed_dir"] = layout.Root
		}
	}
	events := make([]string, 0, len(entries))
	for event := range entries {
		events = append(events, event)
	}
	sort.Strings(events)
	for _, event := range events {
		current, err := managedList(hooks[event])
		if err != nil {
			return nil, false, err
		}
		kept := make([]any, 0, len(current)+1)
		found := false
		for _, entry := range current {
			// Compare canonical JSON because TOML integer types differ from
			// the in-memory constructor, while their value is unchanged.
			a, _ := json.Marshal(entry)
			b, _ := json.Marshal(entries[event])
			matches := bytes.Equal(a, b)
			if !matches && agent == "codex" && (event == "SessionEnd" || event == "Interrupt") {
				// Previous installs used 60s for these native 3s events. Only
				// the exact previously emitted entry can migrate with ownership.
				legacy, _ := json.Marshal(map[string]any{"hooks": []any{map[string]any{"type": "command", "command": managedCommand(layout, agent, event), "timeout": 60}}})
				matches = bytes.Equal(a, legacy)
			}
			if matches {
				if !owned || found {
					return nil, false, code("aidr_managed_ownership_unknown")
				}
				found = true
				if install {
					kept = append(kept, entries[event])
				}
				continue
			}
			if managedEntryCommand(entry, managedCommand(layout, agent, event)) {
				return nil, false, code("aidr_managed_config_conflict")
			}
			kept = append(kept, entry)
		}
		if install && !found {
			kept = append(kept, entries[event])
		}
		if len(kept) == 0 {
			delete(hooks, event)
		} else {
			hooks[event] = kept
		}
	}
	if !install && agent == "codex" && hooks["managed_dir"] == layout.Root {
		// Keep this directory requirement while any administrator hook
		// still uses it. Removing our hooks never loosens another policy.
		remaining := false
		for key := range hooks {
			if key != "managed_dir" && key != "windows_managed_dir" {
				remaining = true
			}
		}
		if !remaining {
			delete(hooks, "managed_dir")
		}
	}
	if len(hooks) == 0 {
		delete(data, "hooks")
	}
	var out bytes.Buffer
	if agent == "codex" {
		if err = toml.NewEncoder(&out).Encode(data); err != nil {
			return nil, false, code("aidr_managed_config_invalid")
		}
		var validated map[string]any
		if _, err = toml.Decode(out.String(), &validated); err != nil {
			return nil, false, code("aidr_managed_config_invalid")
		}
	} else {
		encoded, err := json.MarshalIndent(data, "", "  ")
		if err != nil {
			return nil, false, code("aidr_managed_config_invalid")
		}
		out.Write(encoded)
		out.WriteByte('\n')
	}
	if out.Len() > managedConfigLimit {
		return nil, false, code("aidr_managed_config_oversized")
	}
	return out.Bytes(), addedFeature, nil
}

func managedEntryCommand(entry any, command string) bool {
	group, ok := entry.(map[string]any)
	if !ok {
		return false
	}
	list, err := managedList(group["hooks"])
	if err != nil {
		return false
	}
	for _, handler := range list {
		if handler.(map[string]any)["command"] == command {
			return true
		}
	}
	return false
}

func managedTable(data map[string]any, key string) (map[string]any, error) {
	if value, ok := data[key]; ok {
		if table, ok := value.(map[string]any); ok {
			return table, nil
		}
		return nil, code("aidr_managed_config_conflict")
	}
	table := map[string]any{}
	data[key] = table
	return table, nil
}

func managedList(value any) ([]any, error) {
	if value == nil {
		return nil, nil
	}
	v := reflect.ValueOf(value)
	if v.Kind() != reflect.Slice || v.Len() > 256 {
		return nil, code("aidr_managed_config_conflict")
	}
	result := make([]any, 0, v.Len())
	for i := 0; i < v.Len(); i++ {
		entry := v.Index(i).Interface()
		if _, ok := entry.(map[string]any); !ok {
			return nil, code("aidr_managed_config_invalid")
		}
		result = append(result, entry)
	}
	return result, nil
}

func managedContains(raw []byte, agent string, layout ManagedLayout) bool {
	merged, _, err := mergeManagedConfig(raw, agent, layout, true, true)
	if err != nil {
		return false
	}
	if agent == "claude" {
		var a, b any
		return json.Unmarshal(raw, &a) == nil && json.Unmarshal(merged, &b) == nil && reflect.DeepEqual(a, b)
	}
	var a, b map[string]any
	_, x := toml.Decode(string(raw), &a)
	_, y := toml.Decode(string(merged), &b)
	return x == nil && y == nil && reflect.DeepEqual(a, b)
}

func managedNativeEvent(name string) string { return strings.ToLower(name[:1]) + name[1:] }
