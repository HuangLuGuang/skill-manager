package hooks

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
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

func TestWindowsShellHookHelper(t *testing.T) {
	if os.Getenv("AGENT_MANAGER_WINDOWS_SHELL_TEST") != "1" {
		return
	}
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"input": string(data), "args": os.Args[3:]})
	if os.Getenv("AGENT_MANAGER_WINDOWS_SHELL_DENY") == "1" {
		os.Exit(2)
	}
	os.Exit(0)
}

func TestWindowsShellHooksPreserveJSONAndExitStatus(t *testing.T) {
	root := filepath.Join(t.TempDir(), "客户's & $data directory")
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
	argument := filepath.Join(root, "connection.json")
	command := windowsHookCommand(binary, []string{"-test.run=^TestWindowsShellHookHelper$", "--", argument})
	for _, deny := range []string{"0", "1"} {
		for _, shell := range []string{"cmd.exe", "powershell.exe", "captured"} {
			t.Run(shell+deny, func(t *testing.T) {
				args := []string{"/d", "/s", "/c", command}
				if shell == "powershell.exe" {
					args = []string{"-NoProfile", "-NonInteractive", "-Command", windowsHookScript(binary, []string{"-test.run=^TestWindowsShellHookHelper$", "--", argument})}
				}
				executable := shell
				if shell == "captured" {
					executable = "powershell.exe"
					args = []string{"-NoProfile", "-NonInteractive", "-Command", windowsCapturedHookScript(binary, []string{"-test.run=^TestWindowsShellHookHelper$", "--", argument})}
				}
				cmd := exec.Command(executable, args...)
				cmd.Env = append(os.Environ(), "AGENT_MANAGER_WINDOWS_SHELL_TEST=1", "AGENT_MANAGER_WINDOWS_SHELL_DENY="+deny)
				want := `{"tool_input":{"command":"echo 中文 & $value"}}`
				cmd.Stdin = strings.NewReader(want)
				out, err := cmd.CombinedOutput()
				if deny == "0" && err != nil {
					t.Fatalf("%s: %s %v", shell, out, err)
				}
				if deny == "1" {
					if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != 2 {
						t.Fatalf("lost denial exit: %s %v", out, err)
					}
				}
				var got struct {
					Input string
					Args  []string
				}
				if json.Unmarshal(out, &got) != nil || strings.TrimSpace(got.Input) != want || len(got.Args) != 1 || got.Args[0] != argument {
					t.Fatalf("changed input/arguments: %s", out)
				}
			})
		}
	}
}

func TestWindowsAllSettingsInstallInspectRemove(t *testing.T) {
	for _, agent := range []string{"workbuddy", "codebuddy", "qwenwork", "zcode", "trae", "trae-cn", "qoder-hooks"} {
		t.Run(agent, func(t *testing.T) {
			home := t.TempDir()
			path, err := settingsPath(agent, home)
			if err != nil {
				t.Fatal(err)
			}
			if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(path, []byte(`{"custom":true}`), 0600); err != nil {
				t.Fatal(err)
			}
			binary, connection := filepath.Join(home, "客户端", "bridge.exe"), filepath.Join(home, "bridge.json")
			for _, remove := range []bool{false, false, true} {
				s, err := MergeSettingsHooks(agent, home, binary, connection, remove)
				if err != nil || s.Installed == nil || *s.Installed == remove {
					t.Fatal(s, err)
				}
			}
			after, _ := os.ReadFile(path)
			if !bytes.Contains(after, []byte(`"custom": true`)) || bytes.Contains(after, []byte("EncodedCommand")) || bytes.Contains(after, []byte("bridge.exe")) {
				t.Fatal(string(after))
			}
		})
	}
}

func TestWindowsMissingPreToolBridgeDenies(t *testing.T) {
	for _, shell := range []string{"cmd.exe", "powershell.exe"} {
		t.Run(shell, func(t *testing.T) {
			binary := filepath.Join(t.TempDir(), "missing.exe")
			args := []string{"aidr-hook", "--agent", "claude", "--event", "PreToolUse"}
			command := exec.Command(shell, "/d", "/s", "/c", windowsHookCommand(binary, args))
			if shell == "powershell.exe" {
				command = exec.Command(shell, "-NoProfile", "-NonInteractive", "-Command", windowsHookScript(binary, args))
			}
			command.Stdin = strings.NewReader(`{}`)
			data, err := command.CombinedOutput()
			var reply struct {
				Output struct {
					Decision string `json:"permissionDecision"`
				} `json:"hookSpecificOutput"`
			}
			if err != nil || json.Unmarshal(data, &reply) != nil || reply.Output.Decision != "deny" {
				t.Fatalf("missing binary did not deny: %s %v", data, err)
			}
		})
	}
}

func TestWindowsConnectedMarketplaceUsesNativeBridge(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	source, err := BundledSource(root)
	if err != nil {
		t.Fatal(err)
	}
	binary, connection := filepath.Join(root, "客户's & data", "bridge.exe"), filepath.Join(root, "connection.json")
	market := filepath.Join(root, "market")
	if _, err = BuildConnectedMarketplace(source, market, binary, connection); err != nil {
		t.Fatal(err)
	}
	if err = VerifyMarketplace(market); err != nil {
		t.Fatal(err)
	}
	for _, agent := range []string{"claude", "codex"} {
		data, err := os.ReadFile(filepath.Join(market, "plugins", "aidr-"+agent, "hooks", "hooks.json"))
		if err != nil {
			t.Fatal(err)
		}
		var doc struct {
			Hooks map[string][]struct {
				Hooks []struct {
					Command string
					Timeout int
				}
			}
		}
		if json.Unmarshal(data, &doc) != nil {
			t.Fatal(string(data))
		}
		for event, groups := range doc.Hooks {
			for _, group := range groups {
				for _, handler := range group.Hooks {
					args := []string{"aidr-hook", "--connection-file", connection, "--agent", agent, "--event", event}
					want := windowsHookCommand(binary, args)
					if agent == "claude" {
						want = windowsHookScript(binary, args)
					}
					if handler.Command != want {
						t.Fatal("POSIX hook in Windows plugin", agent, event)
					}
					if event == "PreToolUse" && handler.Timeout != 315 {
						t.Fatal("approval timeout lost")
					}
				}
			}
		}
	}
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
