package hooks

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWindowsSettingsUpgradePreservesUserHooks(t *testing.T) {
	for _, agent := range []string{"workbuddy", "qwenwork", "trae", "trae-cn"} {
		t.Run(agent, func(t *testing.T) {
			home := t.TempDir()
			binary, connection := filepath.Join(home, "bridge.exe"), filepath.Join(home, "bridge.json")
			groups := map[string]any{}
			for event := range settingsEntries(agent, binary, connection) {
				legacy := map[string]any{"type": "command", "command": windowsHookScript(binary, []string{"aidr-hook", "--agent", agent, "--event", event, "--connection-file", connection}), "timeout": 60}
				if agent == "workbuddy" || agent == "qwenwork" {
					legacy["shell"] = "powershell"
				}
				groups[event] = []any{map[string]any{"hooks": []any{legacy, map[string]any{"type": "command", "command": "echo user-owned"}}}}
				if agent == "workbuddy" {
					args := []string{"aidr-hook", "--agent", agent, "--event", event, "--connection-file", connection}
					command := windowsEncodedCommand(windowsCapturedHookScript(binary, args))
					groups[event] = append(groups[event].([]any), map[string]any{"hooks": []any{map[string]any{"type": "command", "command": command, "timeout": 60}}})
				}
			}
			path, _ := settingsPath(agent, home)
			os.MkdirAll(filepath.Dir(path), 0700)
			raw, _ := json.Marshal(map[string]any{"version": 1, "hooks": groups})
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			for _, remove := range []bool{false, false, true} {
				status, err := MergeSettingsHooks(agent, home, binary, connection, remove)
				if err != nil || status.Installed == nil || *status.Installed == remove {
					t.Fatal(status, err)
				}
			}
			raw, _ = os.ReadFile(path)
			if strings.Contains(string(raw), "bridge.exe") || !strings.Contains(string(raw), "user-owned") {
				t.Fatal(string(raw))
			}
			if agent == "workbuddy" || agent == "qwenwork" {
				for _, entry := range settingsEntries(agent, binary, connection) {
					if entry["shell"] != nil || !strings.HasPrefix(entry["command"].(string), "powershell.exe ") {
						t.Fatal(entry)
					}
				}
			}
		})
	}
}
