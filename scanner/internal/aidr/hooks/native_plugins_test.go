package hooks

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestNativeLocalInventoryPreservesActualVersionAndAmbiguity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "package with spaces")
	if e := os.MkdirAll(filepath.Join(path, ".codex-plugin"), 0700); e != nil {
		t.Fatal(e)
	}
	manifest := filepath.Join(path, ".codex-plugin/plugin.json")
	if e := os.WriteFile(manifest, []byte(`{"name":"aidr-codex","version":"0.1.0"}`), 0600); e != nil {
		t.Fatal(e)
	}
	row := func(id string) map[string]any {
		return map[string]any{"id": id, "installed": true, "enabled": false, "version": nil,
			"source": map[string]string{"type": "local", "path": path}}
	}
	list := func(rows []map[string]any, errors []string) []byte {
		b, _ := json.Marshal(map[string]any{"marketplaces": []any{map[string]any{"plugins": rows}}, "marketplaceLoadErrors": errors})
		return b
	}
	config := []byte(`{"config":{"plugins":{"aidr-codex@aidr-local":{"enabled":false}}}}`)
	data, e := projectNativeCodexPlugins(list([]map[string]any{row("aidr-codex@aidr-local")}, nil), config)
	if e != nil {
		t.Fatal(e)
	}
	s, e := ParsePluginStatus("codex", data)
	if e != nil || s.PluginVersion != "0.1.0" || s.Enabled == nil || *s.Enabled || s.HookTrust != "unknown" {
		t.Fatalf("native version/state changed: %+v %v", s, e)
	}
	data, e = projectNativeCodexPlugins(list([]map[string]any{row("aidr-codex@aidr-local"), row("aidr-codex@other")}, nil), config)
	if e != nil {
		t.Fatal(e)
	}
	s, _ = ParsePluginStatus("codex", data)
	if s.SourceCode != "aidr_plugin_multiple_sources" || s.Installed != nil {
		t.Fatal("multiple native sources lost")
	}
	for _, tc := range []struct{ list, config []byte }{
		{[]byte(`{}`), config},
		{[]byte(`{"marketplaces":[{}]}`), []byte(`{"config":{}}`)},
		{list([]map[string]any{}, nil), config},
		{list([]map[string]any{row("aidr-codex@aidr-local")}, []string{"source failed"}), config},
		{list([]map[string]any{row("aidr-codex@aidr-local")}, nil), []byte(`{}`)},
		{list([]map[string]any{row("aidr-codex@aidr-local"), row("aidr-codex@aidr-local")}, nil), config},
	} {
		if _, e := projectNativeCodexPlugins(tc.list, tc.config); e == nil {
			t.Fatal("incomplete inventory treated as readable")
		}
	}
	if e := os.WriteFile(manifest, []byte(`{"name":"unrelated","version":"0.1.1"}`), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e := projectNativeCodexPlugins(list([]map[string]any{row("aidr-codex@aidr-local")}, nil), config); e == nil {
		t.Fatal("unrelated manifest supplied version")
	}
}

func TestNativeLocalInventoryEmptyIsDistinctFromMissing(t *testing.T) {
	data, e := projectNativeCodexPlugins([]byte(`{"marketplaces":[],"marketplaceLoadErrors":[]}`), []byte(`{"config":{}}`))
	if e != nil {
		t.Fatal(e)
	}
	s, _ := ParsePluginStatus("codex", data)
	if s.Installed == nil || *s.Installed || s.SourceCode != "aidr_plugin_not_installed" {
		t.Fatal("explicit empty inventory not recognized")
	}
}

func TestCodexInspectionUsesLocalProtocolWithoutCatalogOrConfigLeak(t *testing.T) {
	for _, version := range []string{"codex-cli 0.159.0", "codex-cli 0.159.2", "codex-cli 0.160.0"} {
		t.Run(version, func(t *testing.T) { checkCodexLocalInspection(t, version) })
	}
}

func checkCodexLocalInspection(t *testing.T, version string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("native shell protocol fixture")
	}
	root := t.TempDir()
	path := filepath.Join(root, "native package")
	if e := os.MkdirAll(filepath.Join(path, ".codex-plugin"), 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(path, ".codex-plugin/plugin.json"), []byte(`{"name":"aidr-codex","version":"0.1.0"}`), 0600); e != nil {
		t.Fatal(e)
	}
	response := func(id int, result any) string {
		b, _ := json.Marshal(map[string]any{"id": id, "result": result})
		return string(b)
	}
	plugin := map[string]any{"id": "aidr-codex@aidr-local", "installed": true, "enabled": false,
		"version": nil, "source": map[string]string{"type": "local", "path": path}}
	inventory := response(2, map[string]any{"marketplaces": []any{map[string]any{"plugins": []any{plugin}}}, "marketplaceLoadErrors": []any{}})
	settings := response(3, map[string]any{"config": map[string]any{"plugins": map[string]any{"aidr-codex@aidr-local": map[string]bool{"enabled": false}}, "unrelated_private_setting": "PRIVATE-CONFIG-CANARY"}})
	log := filepath.Join(root, "requests")
	binary := filepath.Join(root, "codex with spaces")
	script := "#!/bin/sh\ncase \"$1\" in\n--version) echo " + shellQuote(version) + "; exit 0 ;;\napp-server) ;;\n*) exit 77 ;;\nesac\n" +
		"while IFS= read -r line; do\nprintf '%s\\n' \"$line\" >> " + shellQuote(log) + "\ncase \"$line\" in\n" +
		"*'\"method\":\"initialize\"'*) printf '%s\\n' " + shellQuote(response(1, map[string]any{})) + " ;;\n" +
		"*'\"method\":\"plugin/list\"'*) printf '%s\\n' " + shellQuote(inventory) + " ;;\n" +
		"*'\"method\":\"config/read\"'*) printf '%s\\n' " + shellQuote(settings) + " ;;\nesac\ndone\n"
	if e := os.WriteFile(binary, []byte(script), 0700); e != nil {
		t.Fatal(e)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	s, e := InspectPlugin(ctx, "codex", binary, root, "")
	wantVersionStatus := "adapter_target"
	if e != nil || s.Installed == nil || !*s.Installed || s.Enabled == nil || *s.Enabled || s.PluginVersion != "0.1.0" || s.VersionStatus != wantVersionStatus {
		t.Fatalf("local protocol state incorrect: %+v %v", s, e)
	}
	projection, _ := json.Marshal(s)
	if strings.Contains(string(projection), "PRIVATE-CONFIG-CANARY") {
		t.Fatal("unrelated native configuration escaped projection")
	}
	requests, e := os.ReadFile(log)
	if e != nil {
		t.Fatal(e)
	}
	methods := map[string]int{}
	for _, line := range strings.Split(strings.TrimSpace(string(requests)), "\n") {
		var request struct {
			Method string `json:"method"`
			Params struct {
				Kinds         []string `json:"marketplaceKinds"`
				Refetch       bool     `json:"forceRefetch"`
				IncludeLayers bool     `json:"includeLayers"`
			} `json:"params"`
		}
		if json.Unmarshal([]byte(line), &request) != nil {
			t.Fatal("invalid native request")
		}
		methods[request.Method]++
		if request.Method == "plugin/list" && (len(request.Params.Kinds) != 1 || request.Params.Kinds[0] != "local" || request.Params.Refetch) {
			t.Fatal("inspection requested a remote catalog")
		}
		if request.Method == "config/read" && request.Params.IncludeLayers {
			t.Fatal("inspection requested unnecessary configuration layers")
		}
	}
	if methods["plugin/list"] != 1 || methods["config/read"] != 1 || len(methods) != 4 {
		t.Fatal("unexpected native requests", methods)
	}
	failed := strings.Replace(script, shellQuote(settings), shellQuote(`{"id":3,"error":{"code":-32603}}`), 1)
	if e := os.WriteFile(binary, []byte(failed), 0700); e != nil {
		t.Fatal(e)
	}
	s, e = InspectPlugin(ctx, "codex", binary, root, "")
	if e != nil || s.Installed != nil || s.Enabled != nil || s.SourceCode != "aidr_plugin_source_unreadable" {
		t.Fatal("native config failure became a usable installation", s, e)
	}
}

func TestVerifiedPluginHostVersions(t *testing.T) {
	for _, tc := range []struct {
		agent, version string
		verified       bool
	}{
		{"codex", "codex-cli 0.158.0-alpha.2.1", true},
		{"codex", "codex-cli 0.159.0", true},
		{"codex", "codex-cli 0.159.2", true},
		{"codex", "codex-cli 0.159.1", false},
		{"claude", "2.1.220 (Claude Code)", true},
		{"codex", "codex-cli 0.160.0", true},
		{"codex", "codex-cli 0.160.1", false},
		{"codex", "codex-cli 0.159.0-alpha.1", false},
		{"codex", "", false},
		{"claude", "2.1.221 (Claude Code)", false},
		{"claude", "codex-cli 0.159.0", false},
		{"other", "codex-cli 0.159.0", false},
	} {
		if got := verifiedPluginHost(tc.agent, tc.version); got != tc.verified {
			t.Errorf("%s %s: got %t want %t", tc.agent, tc.version, got, tc.verified)
		}
	}
}
