package hooks

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestNativeUpdateVerifiesFilesAndPreservesDisabledPlugin(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("native shell fixture")
	}
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	source, err := BundledSource(root)
	if err != nil {
		t.Fatal(err)
	}
	market := filepath.Join(root, "market")
	if _, err = BuildMarketplace(source, market); err != nil {
		t.Fatal(err)
	}
	old := filepath.Join(root, "old")
	if err = os.MkdirAll(old, 0700); err != nil {
		t.Fatal(err)
	}
	for _, rel := range []string{".claude-plugin/plugin.json", "hooks/hooks.json", "scripts/bridge.sh"} {
		p := filepath.Join(old, rel)
		os.MkdirAll(filepath.Dir(p), 0700)
		data, _ := os.ReadFile(filepath.Join(market, "plugins/aidr-claude", rel))
		os.WriteFile(p, data, 0600)
	}
	os.WriteFile(filepath.Join(old, "scripts/bridge.sh"), []byte("old product bridge"), 0600)
	listed := func(path string) string {
		b, _ := json.Marshal([]any{map[string]any{"id": "aidr-claude@aidr-local", "version": BundledPluginVersion, "enabled": false, "installPath": path}})
		return string(b)
	}
	marker := filepath.Join(root, "updated")
	log := filepath.Join(root, "commands")
	binary := filepath.Join(root, "claude")
	script := "#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + shellQuote(log) + "\ncase \"$1 $2\" in\n'--version ') echo '2.1.999 (Claude Code)' ;;\n'plugin list') if [ -f " + shellQuote(marker) + " ]; then printf '%s' " + shellQuote(listed(filepath.Join(market, "plugins/aidr-claude"))) + "; else printf '%s' " + shellQuote(listed(old)) + "; fi ;;\n'plugin update') touch " + shellQuote(marker) + " ;;\nesac\n"
	if err = os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	s, err := UpdatePlugin(context.Background(), "claude", binary, root, market)
	if err != nil || s.Enabled == nil || *s.Enabled || s.FilesDigest == "" {
		t.Fatal(s, err)
	}
	commands, _ := os.ReadFile(log)
	if strings.Contains(string(commands), "plugin disable") || strings.Contains(string(commands), "plugin uninstall") {
		t.Fatal("native state not preserved", string(commands))
	}
	// Some native updates re-enable a plugin. Restore that observed change only.
	os.Remove(marker)
	disabled := filepath.Join(root, "disabled")
	enabledList := strings.Replace(listed(filepath.Join(market, "plugins/aidr-claude")), `"enabled":false`, `"enabled":true`, 1)
	reenabled := strings.Replace(script, "printf '%s' "+shellQuote(listed(filepath.Join(market, "plugins/aidr-claude"))), "if [ -f "+shellQuote(disabled)+" ]; then printf '%s' "+shellQuote(listed(filepath.Join(market, "plugins/aidr-claude")))+"; else printf '%s' "+shellQuote(enabledList)+"; fi", 1)
	reenabled = strings.Replace(reenabled, "'plugin update')", "'plugin disable') touch "+shellQuote(disabled)+" ;;\n'plugin update')", 1)
	os.WriteFile(binary, []byte(reenabled), 0700)
	if s, err = UpdatePlugin(context.Background(), "claude", binary, root, market); err != nil || s.Enabled == nil || *s.Enabled {
		t.Fatal("re-enabled native update not restored", s, err)
	}
	os.Remove(marker)
	os.WriteFile(binary, []byte(strings.Replace(script, "touch "+shellQuote(marker), "exit 1", 1)), 0700)
	if _, err = UpdatePlugin(context.Background(), "claude", binary, root, market); err == nil || err.Error() != "aidr_plugin_update_failed" {
		t.Fatal("failed native command reported as success", err)
	}
}
