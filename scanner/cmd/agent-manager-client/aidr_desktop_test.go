package main

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

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
