package hooks

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestWindowsHookCommandHelper(t *testing.T) {
	if os.Getenv("AGENT_MANAGER_WINDOWS_COMMAND_TEST") != "1" {
		return
	}
	if _, err := io.Copy(os.Stdout, os.Stdin); err != nil {
		os.Exit(1)
	}
	os.Exit(0)
}

func TestWindowsHookCommandPreservesInput(t *testing.T) {
	root := filepath.Join(t.TempDir(), "Windows 队列 & spaces")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	self, _ := os.Executable()
	data, err := os.ReadFile(self)
	if err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(root, "bridge.exe")
	if err := os.WriteFile(binary, data, 0700); err != nil {
		t.Fatal(err)
	}
	entry := settingsEntries("qoder-hooks", binary, filepath.Join(root, "bridge.json"))["PreToolUse"]
	if entry["command"] != binary {
		t.Fatal("Windows Qoder requires exec form")
	}
	args, ok := entry["args"].([]string)
	if !ok || len(args) != 7 || args[0] != "aidr-hook" {
		t.Fatal(entry)
	}
	cmd := exec.Command(entry["command"].(string), "-test.run=TestWindowsHookCommandHelper")
	cmd.Env = append(os.Environ(), "AGENT_MANAGER_WINDOWS_COMMAND_TEST=1")
	want := []byte(`{"tool_input":{"command":"echo Windows 中文 & spaces"}}`)
	cmd.Stdin = bytes.NewReader(want)
	got, err := cmd.CombinedOutput()
	if err != nil || !bytes.Equal(got, want) {
		t.Fatalf("native command input: %q %v", got, err)
	}
}

func TestWindowsQoderSettingsPreserveUnownedArguments(t *testing.T) {
	home := t.TempDir()
	dir := filepath.Join(home, ".qoder-cn")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(home, "Agent Manager", "bridge.exe")
	connection := filepath.Join(home, "bridge.json")
	unowned := map[string]any{"type": "command", "command": binary, "args": []string{"user-owned"}}
	doc := map[string]any{"custom": true, "hooks": map[string]any{"PreToolUse": []any{map[string]any{"hooks": []any{unowned}}}}}
	data, _ := json.Marshal(doc)
	path := filepath.Join(dir, "settings.json")
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	for _, remove := range []bool{false, false, true} {
		status, err := MergeSettingsHooks("qoder-hooks", home, binary, connection, remove)
		if err != nil || status.Installed == nil || *status.Installed == remove {
			t.Fatal(status, err)
		}
	}
	var after map[string]any
	data, _ = os.ReadFile(path)
	if json.Unmarshal(data, &after) != nil || after["custom"] != true {
		t.Fatal(string(data))
	}
	groups := after["hooks"].(map[string]any)["PreToolUse"].([]any)
	children := groups[0].(map[string]any)["hooks"].([]any)
	if len(groups) != 1 || len(children) != 1 || !ownedSettingsEntry(children[0].(map[string]any), unowned) {
		t.Fatal("user hook changed")
	}
	if _, err := os.Stat(filepath.Join(home, ".qoder", "settings.json")); !os.IsNotExist(err) {
		t.Fatal("wrote international settings for CN host")
	}
}
