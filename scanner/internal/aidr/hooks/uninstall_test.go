package hooks

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestNativeRemovalRequiresOwnershipAndVerifiedAbsence(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell protocol fixture")
	}
	for _, agent := range []string{"claude", "codex"} {
		for _, outcome := range []string{"removed", "failed", "retained", "unreadable", "other-owner", "other-market"} {
			t.Run(agent+"/"+outcome, func(t *testing.T) {
				home := t.TempDir()
				connection := filepath.Join(home, "connection.json")
				bridge := filepath.Join(home, "scripts", "bridge.sh")
				os.MkdirAll(filepath.Dir(bridge), 0700)
				owner := connection
				if outcome == "other-owner" {
					owner += ".other"
				}
				os.WriteFile(bridge, []byte("client --connection-file "+shellQuote(owner)+" --agent "+agent), 0600)
				id := "aidr-" + agent + "@aidr-local"
				if outcome == "other-market" {
					id = "aidr-" + agent + "@user-market"
				}
				row := map[string]any{"id": id, "pluginId": id, "installed": true, "enabled": true, "version": "0.1.1", "installPath": home, "source": map[string]string{"source": "local", "path": home}}
				var inventory any = []any{row}
				absent := "[]"
				if agent == "codex" {
					inventory = map[string]any{"installed": inventory}
					absent = `{"installed":[]}`
				}
				raw, _ := json.Marshal(inventory)
				marker, log := filepath.Join(home, "removed"), filepath.Join(home, "commands")
				after := absent
				if outcome == "retained" {
					after = string(raw)
				}
				if outcome == "unreadable" {
					after = "null"
				}
				mutation := "touch " + shellQuote(marker)
				if outcome == "failed" {
					mutation = "exit 1"
				}
				binary := filepath.Join(home, "host")
				script := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + shellQuote(log) + "\ncase \"$1 $2\" in\n'--version ') echo 'fixture 0.999.1';;\n'plugin list') if [ -f " + shellQuote(marker) + " ]; then printf '%s' " + shellQuote(after) + "; else printf '%s' " + shellQuote(string(raw)) + "; fi;;\n'plugin remove'|'plugin uninstall') " + mutation + ";;\n'app-server --stdio') while IFS= read -r line; do case \"$line\" in *'\"method\":\"initialize\"'*) echo '{\"id\":1,\"result\":{}}';; *'\"id\":2'*) echo '{\"id\":2,\"error\":{\"code\":-32601}}';; esac; done;;\nesac\n"
				if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
					t.Fatal(err)
				}
				status, err := UninstallPlugin(context.Background(), agent, binary, home, connection)
				want := map[string]string{"failed": "aidr_plugin_remove_failed", "retained": "aidr_plugin_remove_not_applied", "unreadable": "aidr_plugin_remove_not_applied", "other-owner": "aidr_desktop_manual_migration_required", "other-market": "aidr_desktop_manual_migration_required"}[outcome]
				if want != "" {
					if err == nil || err.Error() != want {
						t.Fatalf("want %s, got %v", want, err)
					}
				} else if err != nil || status.Installed == nil || *status.Installed {
					t.Fatal(status, err)
				}
				commands, _ := os.ReadFile(log)
				remove := "plugin remove " + id
				if agent == "claude" {
					remove = "plugin uninstall " + id + " --scope user"
				}
				mutated := strings.Contains(string(commands), remove)
				if mutated != (outcome != "other-owner" && outcome != "other-market") {
					t.Fatal("ownership boundary violated")
				}
				if outcome == "removed" {
					if _, err := UninstallPlugin(context.Background(), agent, binary, home, connection); err != nil {
						t.Fatal("repeat removal", err)
					}
					commands, _ = os.ReadFile(log)
					if strings.Count(string(commands), remove) != 1 {
						t.Fatal("repeat removal mutated host")
					}
				}
			})
		}
	}
}

// Opt-in native commands use temporary config homes and never open a model session.
func TestNativeRemovalIsolatedInstalledHosts(t *testing.T) {
	if os.Getenv("AIDR_NATIVE_REMOVAL_ACCEPTANCE") != "1" {
		t.Skip("isolated native host acceptance opt-in")
	}
	for _, agent := range []string{"claude", "codex"} {
		t.Run(agent, func(t *testing.T) {
			binary, err := exec.LookPath(agent)
			if configured := os.Getenv("AIDR_NATIVE_" + strings.ToUpper(agent) + "_BIN"); configured != "" {
				binary, err = configured, nil
			}
			if err != nil {
				t.Fatal(err)
			}
			home, err := filepath.EvalSymlinks(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			source, err := BundledSource(home)
			if err != nil {
				t.Fatal(err)
			}
			connection, market := filepath.Join(home, "connection.json"), filepath.Join(home, "market")
			if _, err = BuildConnectedMarketplace(source, market, "/usr/bin/true", connection); err != nil {
				t.Fatal(err)
			}
			settings, content := "config.toml", "model = \"isolated-removal-check\"\n"
			if agent == "claude" {
				settings, content = "settings.json", `{"env":{"AIDR_ISOLATED_REMOVAL_CHECK":"preserved"}}`
			}
			path := filepath.Join(home, settings)
			if err = os.WriteFile(path, []byte(content), 0600); err != nil {
				t.Fatal(err)
			}
			ctx := context.Background()
			installed, err := InstallPlugin(ctx, agent, binary, home, market)
			if err != nil || installed.Installed == nil || !*installed.Installed {
				t.Fatal("native install", installed, err)
			}
			for i := 0; i < 2; i++ {
				after, err := UninstallPlugin(ctx, agent, binary, home, connection)
				if err != nil || after.Installed == nil || *after.Installed {
					t.Fatal("native remove", after, err)
				}
			}
			after, err := os.ReadFile(path)
			if err != nil || !strings.Contains(string(after), "isolated-removal-check") && !strings.Contains(string(after), "AIDR_ISOLATED_REMOVAL_CHECK") {
				t.Fatal("user configuration lost", err)
			}
			t.Logf("%s: native install → remove → absent inventory → repeat remove; user setting preserved", installed.HostVersion)
		})
	}
}
