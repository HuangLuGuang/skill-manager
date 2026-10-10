package hooks

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func localPluginFixture(t *testing.T, agent string) (string, string) {
	t.Helper()
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(home, "market", "plugins", "aidr-"+agent)
	putLocalMetadata(t, filepath.Join(root, "."+agent+"-plugin/plugin.json"), `{"name":"aidr-`+agent+`","version":"0.1.1"}`)
	putLocalMetadata(t, filepath.Join(root, "hooks/hooks.json"), `{}`)
	putLocalMetadata(t, filepath.Join(root, "scripts/bridge.sh"), "#!/bin/sh\n")
	if agent == "codex" {
		putLocalMetadata(t, filepath.Join(home, "config.toml"), fmt.Sprintf("[marketplaces.aidr-local]\nsource_type = 'local'\nsource = %q\n[plugins.\"aidr-codex@aidr-local\"]\nenabled = true\n[marketplaces.ponytail]\nsource_type = 'git'\nsource = 'https://example.invalid/unused.git'\n[plugins.\"ponytail@ponytail\"]\nenabled = false\n", filepath.Join(home, "market")))
		putLocalMetadata(t, filepath.Join(home, "market/.agents/plugins/marketplace.json"), `{"name":"aidr-local","plugins":[{"name":"aidr-codex","source":{"source":"local","path":"./plugins/aidr-codex"}}]}`)
	} else {
		putLocalMetadata(t, filepath.Join(home, "plugins/installed_plugins.json"), fmt.Sprintf(`{"version":2,"plugins":{"aidr-claude@aidr-local":[{"scope":"user","installPath":%q,"version":"0.1.1"}]}}`, root))
		putLocalMetadata(t, filepath.Join(home, "settings.json"), `{"enabledPlugins":{"aidr-claude@aidr-local":true},"env":{"PRIVATE":"NOT-FOR-REPORT"}}`)
	}
	return home, root
}

func putLocalMetadata(t *testing.T, path, data string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestLocalPluginChangesAndEvidence(t *testing.T) {
	for _, agent := range []string{"codex", "claude"} {
		t.Run(agent, func(t *testing.T) {
			home, root := localPluginFixture(t, agent)
			inspect := func() PluginStatus {
				s, err := InspectLocalPlugin(context.Background(), agent, home, "")
				if err != nil {
					t.Fatal(err)
				}
				return s
			}
			first := inspect()
			if first.Installed == nil || !*first.Installed || first.Enabled == nil || !*first.Enabled || first.PluginVersion != "0.1.1" || first.FilesDigest == "" || first.ConfigurationDigest == "" {
				t.Fatalf("missing local evidence: %+v", first)
			}
			if first.HookTrust != "unknown" || first.HostVersion != "" || first.VersionStatus != "adapter_available" {
				t.Fatal(first)
			}
			out, _ := json.Marshal(first)
			if strings.Contains(string(out), home) || strings.Contains(string(out), "NOT-FOR-REPORT") {
				t.Fatal("private configuration leaked")
			}
			putLocalMetadata(t, filepath.Join(root, "scripts/bridge.sh"), "#!/bin/sh\necho changed\n")
			changed := inspect()
			if d := ComparePluginStatus(first, changed); len(d.Fields) != 1 || d.Fields[0] != "declared_files" {
				t.Fatal(d)
			}
			if err := os.Remove(filepath.Join(root, "hooks/hooks.json")); err != nil {
				t.Fatal(err)
			}
			missing := inspect()
			if missing.Installed == nil || !*missing.Installed || missing.FilesCode != "aidr_plugin_files_unreadable" {
				t.Fatal(missing)
			}
			if agent == "codex" {
				path := filepath.Join(home, "config.toml")
				raw, _ := os.ReadFile(path)
				putLocalMetadata(t, path, strings.Replace(string(raw), "enabled = true", "enabled = false", 1))
			} else {
				putLocalMetadata(t, filepath.Join(home, "settings.json"), `{"enabledPlugins":{"aidr-claude@aidr-local":false}}`)
			}
			disabled := inspect()
			if disabled.Enabled == nil || *disabled.Enabled || disabled.SourceCode != "aidr_plugin_disabled" || disabled.ConfigurationDigest == first.ConfigurationDigest {
				t.Fatal(disabled)
			}
		})
	}
}

func TestLocalPluginUnreadableIsNotRemoval(t *testing.T) {
	for _, agent := range []string{"codex", "claude"} {
		t.Run(agent, func(t *testing.T) {
			home, root := localPluginFixture(t, agent)
			path := filepath.Join(home, "config.toml")
			if agent == "claude" {
				path = filepath.Join(home, "settings.json")
			}
			good, _ := os.ReadFile(path)
			for _, invalid := range []string{"{invalid", strings.Repeat("x", 2<<20+1)} {
				putLocalMetadata(t, path, invalid)
				s, err := InspectLocalPlugin(context.Background(), agent, home, "")
				if err != nil || s.Installed != nil || s.Enabled != nil || s.ConfigurationDigest != "" || s.SourceCode != "aidr_plugin_source_unreadable" {
					t.Fatal(s, err)
				}
			}
			putLocalMetadata(t, path, string(good))
			if err := os.Remove(filepath.Join(root, "."+agent+"-plugin/plugin.json")); err != nil {
				t.Fatal(err)
			}
			s, _ := InspectLocalPlugin(context.Background(), agent, home, "")
			if s.Installed != nil || s.SourceCode != "aidr_plugin_source_unreadable" {
				t.Fatal(s)
			}
		})
	}
}

func TestLocalPluginEmptyInventoryAndUnsupportedSources(t *testing.T) {
	home, _ := localPluginFixture(t, "codex")
	for _, config := range []string{
		"[plugins.\"aidr-codex@remote\"]\nenabled = true\n[marketplaces.remote]\nsource_type = 'git'\nsource = 'https://example.invalid/repo.git'\n",
		"[plugins.\"aidr-codex@missing\"]\nenabled = true\n",
	} {
		putLocalMetadata(t, filepath.Join(home, "config.toml"), config)
		s, _ := InspectLocalPlugin(context.Background(), "codex", home, "")
		if s.Installed != nil || s.SourceCode != "aidr_plugin_source_unreadable" {
			t.Fatal(s)
		}
	}
	putLocalMetadata(t, filepath.Join(home, "config.toml"), "[plugins]\n")
	s, _ := InspectLocalPlugin(context.Background(), "codex", home, "")
	if s.Installed == nil || *s.Installed || s.SourceCode != "aidr_plugin_not_installed" {
		t.Fatal(s)
	}
	claude, _ := localPluginFixture(t, "claude")
	putLocalMetadata(t, filepath.Join(claude, "plugins/installed_plugins.json"), `{"version":2,"plugins":{}}`)
	s, _ = InspectLocalPlugin(context.Background(), "claude", claude, "")
	if s.Installed != nil {
		t.Fatal("dangling configuration treated as removal", s)
	}
	putLocalMetadata(t, filepath.Join(claude, "settings.json"), `{}`)
	s, _ = InspectLocalPlugin(context.Background(), "claude", claude, "")
	if s.Installed == nil || *s.Installed {
		t.Fatal(s)
	}
}
