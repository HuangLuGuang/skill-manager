package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestManualPlatformPolicyAllowsLocalSettingsInstallationWithoutEnablingCapture(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("WorkBuddy settings adapter is currently macOS")
	}
	home := shortDesktopTestHome(t)
	cfg := managedclient.Config{Server: "http://127.0.0.1:41901", Token: "fictional"}
	if err := managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Join(home, ".workbuddy"), 0700); err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{Hosts: map[string]desktopHost{}, ManagedTask: 7, ManagedServer: cfg.Server, ManagedDevice: paths.Device,
		RuntimePolicy: &desktopRuntimePolicy{Version: "1", Target: managedclient.RuntimeGovernancePolicy{
			Enabled: true, Hosts: []string{"codex"}, Installation: "manual", AccessMode: "ordinary", Updates: "manual",
			Retry: managedclient.ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 60},
		}}}
	for _, action := range []string{"connect", "connect", "upgrade", "disconnect"} {
		if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
			t.Fatal(err)
		}
		var out bytes.Buffer
		if err = aidrDesktop([]string{"--home", home, "--action", action, "--agent", "workbuddy"}, &out); err != nil {
			t.Fatal(action, err)
		}
		var result struct {
			Plugin struct {
				Installed bool `json:"installed"`
			} `json:"plugin"`
		}
		if err = json.Unmarshal(out.Bytes(), &result); err != nil || result.Plugin.Installed != (action != "disconnect") {
			t.Fatal(action, err)
		}
		after, err := loadDesktopPreferences(home)
		if err != nil || after.Enabled || after.ManagedTask != 7 || after.RuntimePolicy.Target.Hosts[0] != "codex" {
			t.Fatal("installation changed collection policy", err)
		}
		var bridge struct {
			Active bool     `json:"active"`
			Agents []string `json:"agents"`
		}
		if err = readDesktopJSON(paths.Connection, &bridge); err != nil || bridge.Active || len(bridge.Agents) != 1 || bridge.Agents[0] != "codex" {
			t.Fatal("installation expanded receiver scope", err)
		}
	}
	for _, mode := range []string{"automatic", "managed", "unknown"} {
		blocked := prefs
		policy := *prefs.RuntimePolicy
		blocked.RuntimePolicy = &policy
		if mode == "automatic" {
			policy.Target.Installation = "automatic"
		} else if mode == "managed" {
			policy.Target.AccessMode = "managed"
		} else {
			blocked.RuntimePolicy = nil
		}
		if localPluginInstallationAllowed(blocked, "connect") {
			t.Fatal("platform authority bypassed", mode)
		}
	}
	if localPluginInstallationAllowed(prefs, "enable") || localPluginInstallationAllowed(prefs, "disable") {
		t.Fatal("local receiver toggle bypassed platform target")
	}
}

func shortDesktopTestHome(t *testing.T) string {
	t.Helper()
	base := os.TempDir()
	if runtime.GOOS == "darwin" {
		base = "/private/tmp"
	}
	p, e := os.MkdirTemp(base, "aidr-go-")
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { os.RemoveAll(p) })
	p, e = filepath.EvalSymlinks(p)
	if e != nil {
		t.Fatal(e)
	}
	return p
}

func TestDesktopDestinationAndCredentialRotation(t *testing.T) {
	home := shortDesktopTestHome(t)
	var e error
	cfg := managedclient.Config{Server: "http://127.0.0.1:41901", Token: "synthetic-not-a-real-token"}
	if e = managedclient.SaveConfig(home, cfg); e != nil {
		t.Fatal(e)
	}
	_, before, e := desktopBinding(home)
	if e != nil {
		t.Fatal(e)
	}
	cfg.Token = "synthetic-rotated-token"
	if e = managedclient.SaveConfig(home, cfg); e != nil {
		t.Fatal(e)
	}
	_, after, e := desktopBinding(home)
	if e != nil || before.State != after.State || before.Device != after.Device {
		t.Fatal("credential rotation changed queue identity")
	}
	cfg.Server = "http://127.0.0.1:41902"
	if e = managedclient.SaveConfig(home, cfg); e != nil {
		t.Fatal(e)
	}
	_, other, e := desktopBinding(home)
	if e != nil || other.State == before.State {
		t.Fatal("platform switch reused old queue")
	}
	var out bytes.Buffer
	if e = aidrDesktop([]string{"--home", home, "--action", "status"}, &out); e != nil {
		t.Fatal(e)
	}
	if strings.Contains(out.String(), "synthetic-") {
		t.Fatal("credential exposed")
	}
}
func TestDesktopPreferencesAndPrivateConnection(t *testing.T) {
	home := shortDesktopTestHome(t)
	var e error
	if e = managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:41901", Token: "fictional"}); e != nil {
		t.Fatal(e)
	}
	for _, action := range []string{"enable", "disable", "enable"} {
		if e = aidrDesktop([]string{"--home", home, "--action", action}, &bytes.Buffer{}); e != nil {
			t.Fatal(e)
		}
		p, e := loadDesktopPreferences(home)
		if e != nil || p.Enabled != (action == "enable") {
			t.Fatal("restart did not recover enabled preference")
		}
	}
	p := filepath.Join(home, "connection.json")
	if e = writeDesktopJSON(p, map[string]string{"socket": "/invalid/not-running.sock"}); e != nil {
		t.Fatal(e)
	}
	var target map[string]string
	if e = readDesktopJSON(p, &target); e != nil {
		t.Fatal(e)
	}
	if e = os.Chmod(p, 0644); e != nil {
		t.Fatal(e)
	}
	if e = readDesktopJSON(p, &target); e == nil {
		t.Fatal("public connection accepted")
	}
}

func TestDesktopUnreadableConfigurationIsNotAnEmptyConfiguration(t *testing.T) {
	home := shortDesktopTestHome(t)
	if _, _, e := desktopBinding(home); e == nil || e.Error() != "aidr_desktop_not_configured" {
		t.Fatal("missing configuration not distinguished")
	}
	if e := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:41901", Token: "fictional"}); e != nil {
		t.Fatal(e)
	}
	if e := os.Chmod(filepath.Join(home, ".agent-manager", "config.json"), 0644); e != nil {
		t.Fatal(e)
	}
	if _, _, e := desktopBinding(home); e == nil || e.Error() != "aidr_desktop_config_unreadable" {
		t.Fatal("unreadable configuration treated as empty")
	}
}
