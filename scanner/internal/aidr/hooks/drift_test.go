package hooks

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPluginDriftRetainsUnknownAndDistinguishesEvidence(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	raw := func(enabled bool, path string) []byte {
		v, _ := json.Marshal(map[string]any{"installed": []any{map[string]any{"pluginId": "aidr-codex@local", "installed": true, "enabled": enabled, "version": "0.1.0", "source": map[string]string{"source": "local", "path": path}}}})
		return v
	}
	first, err := ParsePluginStatus("codex", raw(true, root))
	if err != nil {
		t.Fatal(err)
	}
	if first.SourceKind != "declared_local_source" || first.ConfigurationDigest == "" {
		t.Fatal("missing listing provenance")
	}
	serialized, _ := json.Marshal(first)
	if strings.Contains(string(serialized), root) {
		t.Fatal("native source path leaked")
	}
	for _, tc := range []struct {
		body     []byte
		expected string
	}{
		{raw(true, root), "aidr_plugin_drift_unchanged"},
		{raw(false, root), "aidr_plugin_drift_changed"},
		{raw(true, root+"/other"), "aidr_plugin_drift_changed"},
		{[]byte(`{"installed":[]}`), "aidr_plugin_drift_changed"},
		{[]byte(`{}`), "aidr_plugin_drift_unknown"},
	} {
		current, _ := ParsePluginStatus("codex", tc.body)
		if ComparePluginStatus(first, current).Code != tc.expected {
			t.Fatalf("wrong state %s", tc.expected)
		}
	}
	for _, name := range []string{".codex-plugin/plugin.json", "hooks/hooks.json", "scripts/bridge.sh"} {
		p := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(p), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte("synthetic-original"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	first.FilesDigest, first.FilesCode = pluginFilesDigest("codex", root)
	if first.FilesCode != "aidr_plugin_files_observed" {
		t.Fatal("not observed")
	}
	if err := os.WriteFile(filepath.Join(root, "scripts/bridge.sh"), []byte("synthetic-changed"), 0600); err != nil {
		t.Fatal(err)
	}
	current := first
	current.FilesDigest, current.FilesCode = pluginFilesDigest("codex", root)
	d := ComparePluginStatus(first, current)
	if d.Code != "aidr_plugin_drift_changed" || len(d.Fields) != 1 || d.Fields[0] != "declared_files" {
		t.Fatal(d)
	}
	if err := os.Remove(filepath.Join(root, "scripts/bridge.sh")); err != nil {
		t.Fatal(err)
	}
	current.FilesDigest, current.FilesCode = pluginFilesDigest("codex", root)
	if ComparePluginStatus(first, current).Code != "aidr_plugin_drift_incomplete" || current.Installed == nil || !*current.Installed {
		t.Fatal("read failure became removal")
	}
	if err := os.Symlink(filepath.Join(root, "hooks/hooks.json"), filepath.Join(root, "scripts/bridge.sh")); err != nil {
		t.Fatal(err)
	}
	if _, code := pluginFilesDigest("codex", root); code != "aidr_plugin_files_unreadable" {
		t.Fatal("followed link")
	}
}
