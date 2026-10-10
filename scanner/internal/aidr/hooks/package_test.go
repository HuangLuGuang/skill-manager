package hooks

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestConnectedBridgeNeedsNoEnvironmentAndKeepsArgumentBoundaries(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX bridge")
	}
	root, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	root = filepath.Join(root, "customer's client directory")
	if e = os.Mkdir(root, 0700); e != nil {
		t.Fatal(e)
	}
	source, _ := filepath.Abs("../../../../client/aidr-plugins")
	client := filepath.Join(root, "client executable")
	connection := filepath.Join(root, "private connection.json")
	if e = os.WriteFile(client, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\"\ncat\n"), 0700); e != nil {
		t.Fatal(e)
	}
	market := filepath.Join(root, "market")
	if _, e = BuildConnectedMarketplace(source, market, client, connection); e != nil {
		t.Fatal(e)
	}
	for _, agent := range []string{"claude", "codex"} {
		bridge := filepath.Join(market, "plugins", "aidr-"+agent, "scripts", "bridge.sh")
		cmd := exec.Command("/bin/sh", bridge, "PreToolUse")
		cmd.Env = []string{"PATH=/usr/bin:/bin"}
		cmd.Stdin = strings.NewReader("{\"synthetic\":true}")
		output, e := cmd.Output()
		if e != nil {
			t.Fatal(e)
		}
		want := "aidr-hook\n--connection-file\n" + connection + "\n--agent\n" + agent + "\n--event\nPreToolUse\n{\"synthetic\":true}"
		if string(output) != want {
			t.Fatal("clean-environment bridge changed argument or input boundaries")
		}
	}
}

func TestPackageDeclaredFilesAndExistingDestination(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	source, err := filepath.Abs("../../../../client/aidr-plugins")
	if err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(root, "package")
	hashes, err := BuildMarketplace(source, destination)
	if err != nil {
		t.Fatal(err)
	}
	if len(hashes) != 8 {
		t.Fatal("unexpected exported files")
	}
	if _, err = os.Stat(filepath.Join(destination, "aidr-package.json")); err != nil {
		t.Fatal(err)
	}
	if err = VerifyMarketplace(destination); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(destination, "plugins/aidr-codex/scripts/bridge.sh"), []byte("corrupt"), 0600); err != nil {
		t.Fatal(err)
	}
	if VerifyMarketplace(destination) == nil {
		t.Fatal("corrupt cached marketplace accepted")
	}
	if _, err = BuildMarketplace(source, destination); err == nil {
		t.Fatal("existing distribution overwritten")
	}
	link := filepath.Join(root, "source-link")
	if err = os.Symlink(source, link); err != nil {
		t.Fatal(err)
	}
	if _, err = BuildMarketplace(link, filepath.Join(root, "other")); err == nil {
		t.Fatal("symlink source accepted")
	}
}

// Exercise the exported files, including their actual shell entry points. This
// checks distribution wiring; it does not establish native host hook support.
func TestPackagedLifecycleWiringAndBridge(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("current distribution uses the POSIX bridge")
	}
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	source, err := filepath.Abs("../../../../client/aidr-plugins")
	if err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(root, "package with spaces")
	hashes, err := BuildMarketplace(source, destination)
	if err != nil {
		t.Fatal(err)
	}
	for name, expected := range hashes {
		data, err := os.ReadFile(filepath.Join(destination, name))
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(data)
		if hex.EncodeToString(sum[:]) != expected {
			t.Fatalf("exported bytes do not match digest: %s", name)
		}
	}
	client := filepath.Join(root, "client with spaces")
	if err := os.WriteFile(client, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\"\ncat\nexit 7\n"), 0700); err != nil {
		t.Fatal(err)
	}
	for _, host := range []string{"claude", "codex"} {
		t.Run(host, func(t *testing.T) {
			base := filepath.Join(destination, "plugins", "aidr-"+host)
			data, err := os.ReadFile(filepath.Join(base, "hooks/hooks.json"))
			if err != nil {
				t.Fatal(err)
			}
			var manifest struct {
				Hooks map[string][]struct {
					Hooks []struct {
						Type    string `json:"type"`
						Command string `json:"command"`
					} `json:"hooks"`
				} `json:"hooks"`
			}
			if err := json.Unmarshal(data, &manifest); err != nil {
				t.Fatal(err)
			}
			if len(manifest.Hooks) != len(catalog[host]) {
				t.Fatal("packaged lifecycle catalog differs from receiver")
			}
			variable := "PLUGIN_ROOT"
			if host == "claude" {
				variable = "CLAUDE_PLUGIN_ROOT"
			}
			for event := range catalog[host] {
				entries := manifest.Hooks[event]
				if len(entries) != 1 || len(entries[0].Hooks) != 1 {
					t.Fatalf("missing or duplicate packaged event: %s", event)
				}
				hook := entries[0].Hooks[0]
				if hook.Type != "command" || hook.Command != "sh \"${"+variable+"}/scripts/bridge.sh\" "+event {
					t.Fatalf("unexpected bridge routing: %s", event)
				}
				cmd := exec.Command("/bin/sh", "-c", hook.Command)
				cmd.Env = []string{"PATH=/usr/bin:/bin", variable + "=" + base, "AIDR_CLIENT_BIN=" + client}
				cmd.Stdin = strings.NewReader("{\"fixture\":\"bounded-synthetic-input\"}")
				output, err := cmd.Output()
				if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != 7 {
					t.Fatalf("bridge lost client exit status for %s: %v", event, err)
				}
				want := "aidr-hook\n--agent\n" + host + "\n--event\n" + event + "\n{\"fixture\":\"bounded-synthetic-input\"}"
				if string(output) != want {
					t.Fatalf("bridge changed arguments or stdin for %s", event)
				}
			}
			cmd := exec.Command("/bin/sh", filepath.Join(base, "scripts/bridge.sh"), "PreToolUse")
			cmd.Env = []string{"PATH=/usr/bin:/bin", "AIDR_CLIENT_BIN=" + filepath.Join(root, "missing-client")}
			output, err := cmd.Output()
			if err != nil {
				t.Fatal(err)
			}
			var denied struct {
				Output struct {
					Event    string `json:"hookEventName"`
					Decision string `json:"permissionDecision"`
					Reason   string `json:"permissionDecisionReason"`
				} `json:"hookSpecificOutput"`
			}
			if json.Unmarshal(output, &denied) != nil || denied.Output.Event != "PreToolUse" || denied.Output.Decision != "deny" || denied.Output.Reason != "aidr_hook_binary_unavailable" {
				t.Fatal("packaged pre-tool bridge did not deny missing client")
			}
		})
	}
}
