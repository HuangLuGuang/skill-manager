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

func probeHost(t *testing.T, response string) (string, string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("shell protocol fixture")
	}
	home := t.TempDir()
	binary := filepath.Join(home, "host")
	script := "#!/bin/sh\ncase \"$1\" in\n--version) echo 'codex-cli 0.999.42'; exit 0;;\nplugin) echo '{\"installed\":[]}'; exit 0;;\nesac\nwhile IFS= read -r line; do\ncase \"$line\" in\n*'\"method\":\"initialize\"'*) echo '{\"id\":1,\"result\":{}}';;\n*'\"id\":2'*) printf '%s\\n' " + shellQuote(response) + ";;\n*'\"id\":3'*) echo '{\"id\":3,\"result\":{\"config\":{}}}';;\nesac\ndone\n"
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	return binary, home
}

func TestPluginNegotiationFallsBackOnlyForMissingNativeMethod(t *testing.T) {
	for _, tc := range []struct {
		reply      string
		compatible bool
	}{
		{`{"id":2,"error":{"code":-32601}}`, true},
		{`{"id":2,"error":{"code":-32603}}`, false},
		{`{"id":2,"result":null}`, false},
		{`{"id":2,"result":{}}`, false},
	} {
		binary, home := probeHost(t, tc.reply)
		status, err := InspectPlugin(context.Background(), "codex", binary, home, "")
		if err != nil || (status.VersionStatus == "interface_compatible") != tc.compatible {
			t.Fatal(status, err)
		}
		if !tc.compatible && status.Installed != nil {
			t.Fatal("unreadable native state masked by CLI")
		}
	}
}

func TestVersionMetadataFailureDoesNotBlockReadableInterface(t *testing.T) {
	binary, home := probeHost(t, `{"id":2,"error":{"code":-32601}}`)
	script, err := os.ReadFile(binary)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(binary, []byte(strings.Replace(string(script), "echo 'codex-cli 0.999.42'; exit 0", "exit 1", 1)), 0700); err != nil {
		t.Fatal(err)
	}
	status, err := InspectPlugin(context.Background(), "codex", binary, home, "")
	if err != nil || status.VersionStatus != "interface_compatible" || status.HostVersion != "" {
		t.Fatal("version metadata became an access gate", status, err)
	}
}

func TestNativeConfigWriterAcceptsEmptySuccess(t *testing.T) {
	binary, home := probeHost(t, `{"id":2,"result":null}`)
	if !preserveCodexDisabled(context.Background(), binary, home, "aidr-codex@aidr-local") {
		t.Fatal("successful native config write rejected")
	}
}

func TestManagedPreflightAndEffectiveLoadingAreSeparate(t *testing.T) {
	layout, err := SystemManagedLayout("codex")
	if err != nil {
		t.Skip("system managed layout unavailable")
	}
	items := []map[string]any{}
	for event := range catalog["codex"] {
		items = append(items, map[string]any{"command": managedCommand(layout, "codex", event), "eventName": managedNativeEvent(event), "enabled": true, "isManaged": true, "trustStatus": "managed", "source": "system", "sourcePath": layout.Root})
	}
	for _, tc := range []struct {
		hooks   []map[string]any
		applied bool
	}{{[]map[string]any{}, false}, {items[:11], false}, {items, true}} {
		raw, _ := json.Marshal(map[string]any{"id": 2, "result": map[string]any{"data": []any{map[string]any{"hooks": tc.hooks, "errors": []any{}, "warnings": []any{}}}}})
		binary, home := probeHost(t, string(raw))
		if err := ManagedHostReady(context.Background(), "codex", binary, home, false); err != nil {
			t.Fatal("readable native interface rejected", err)
		}
		err := ManagedHostReady(context.Background(), "codex", binary, home, true)
		if (err == nil) != tc.applied {
			t.Fatal("installation mistaken for effective loading", err)
		}
	}
	for _, raw := range []string{`{}`, `null`, `{"data":[]}`, `{"data":[{}]}`, `{"data":[{"hooks":[],"warnings":["unreadable"]}]}`} {
		if managedInventoryReadable([]byte(raw)) {
			t.Fatal("invalid inventory accepted", raw)
		}
	}
}

// Explicit opt-in read-only probe against an installed host; no model session,
// installation, system configuration or native trust changes.
func TestInstalledCodexCompatibilityProbe(t *testing.T) {
	binary, home := os.Getenv("AIDR_TEST_CODEX_BINARY"), os.Getenv("AIDR_TEST_CODEX_HOME")
	if binary == "" || home == "" {
		t.Skip("native host probe not requested")
	}
	status, err := InspectPlugin(context.Background(), "codex", binary, home, "")
	if err != nil || status.VersionStatus != "interface_compatible" {
		t.Fatal("native plugin interface unavailable", err)
	}
	if err := ManagedHostReady(context.Background(), "codex", binary, home, false); err != nil {
		t.Fatal(err)
	}
	t.Log("native version:", strings.TrimSpace(status.HostVersion), "plugin interface and managed preflight passed; effective system installation not tested")
}
