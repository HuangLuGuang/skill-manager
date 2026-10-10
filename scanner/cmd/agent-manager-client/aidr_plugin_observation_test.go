package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/aidr/upload"
	"skill-manager/scanner/internal/managedclient"
)

func TestBackgroundPluginObservationDoesNotStartHost(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("desktop Unix fixture")
	}
	home := shortDesktopTestHome(t)
	marker := filepath.Join(home, "host-was-started")
	binary := filepath.Join(home, "codex")
	if err := os.WriteFile(binary, []byte(fmt.Sprintf("#!/bin/sh\ntouch %q\nexit 1\n", marker)), 0700); err != nil {
		t.Fatal(err)
	}
	configHome := filepath.Join(home, ".codex")
	if err := os.MkdirAll(configHome, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(configHome, "config.toml"), []byte("[plugins]\n"), 0600); err != nil {
		t.Fatal(err)
	}
	var received hooks.PluginReport
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/clients/device/aidr/hook-plugin-status" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		if err := json.NewDecoder(r.Body).Decode(&received); err != nil {
			t.Error(err)
		}
		json.NewEncoder(w).Encode(map[string]string{"code": "aidr_plugin_report_received", "stream_id": received.Stream, "report_sequence": received.Sequence})
	}))
	defer server.Close()
	client, err := upload.New(upload.Options{Server: server.URL, ClientID: "device", Token: "fixture"})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	store, err := hooks.OpenStore(filepath.Join(home, "test-hook-store"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if err := observePlugins(ctx, client, store, []pluginInspectionTarget{{"codex", binary, configHome}}, func(code string) {
		if code != "aidr_plugin_report_received" {
			t.Error(code)
		}
		cancel()
	}); err != nil {
		t.Fatal(err)
	}
	if received.Status.SourceCode != "aidr_plugin_not_installed" || received.Status.HookTrust != "unknown" || received.Status.VersionStatus != "adapter_available" {
		t.Fatal(received.Status)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("receiver inspection started host", err)
	}
	// An installed plugin must not cause the scheduled check to query native
	// hook trust either; that query also starts an App Server.
	market := filepath.Join(home, "market")
	for name, content := range map[string]string{
		".agents/plugins/marketplace.json":             `{"name":"aidr-local","plugins":[{"name":"aidr-codex","source":{"source":"local","path":"./plugins/aidr-codex"}}]}`,
		"plugins/aidr-codex/.codex-plugin/plugin.json": `{"name":"aidr-codex","version":"0.1.1"}`,
		"plugins/aidr-codex/hooks/hooks.json":          `{}`,
		"plugins/aidr-codex/scripts/bridge.sh":         "#!/bin/sh\n",
	} {
		path := filepath.Join(market, name)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	config := fmt.Sprintf("[marketplaces.aidr-local]\nsource_type='local'\nsource=%q\n[plugins.\"aidr-codex@aidr-local\"]\nenabled=true\n", market)
	if err := os.WriteFile(filepath.Join(configHome, "config.toml"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}

	if err := managedclient.SaveConfig(home, managedclient.Config{Server: server.URL, Token: "fixture"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{Hosts: map[string]desktopHost{"codex": {Binary: binary, Home: configHome}}}
	if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	target := managedclient.RuntimeGovernancePolicy{Enabled: true, Hosts: []string{"codex"}, Installation: "manual", AccessMode: "ordinary", Updates: "manual", Retry: managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 30}}
	policy := managedclient.Policy{Classification: &managedclient.ClassificationPolicy{RuntimeGovernanceConfigured: true, RuntimeGovernance: &target}}
	if err := inspectAIDRTarget(context.Background(), home, policy); err != nil {
		t.Fatal(err)
	}
	var observed struct {
		Plugin hooks.PluginStatus `json:"plugin"`
		Trust  string             `json:"hook_trust"`
	}
	if err := readDesktopJSON(filepath.Join(paths.Root, "observed-codex.json"), &observed); err != nil {
		t.Fatal(err)
	}
	if observed.Plugin.Installed == nil || !*observed.Plugin.Installed || observed.Trust != "unknown" {
		t.Fatal(observed)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("runtime inspection started host", err)
	}
}
