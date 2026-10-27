package main

import (
	"os"
	"path/filepath"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestDesktopConfigCacheInvalidationAndPrivatePermissions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "preferences.json")
	write := func(value string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(`{"value":"`+value+`"}`), 0600); err != nil {
			t.Fatal(err)
		}
	}
	read := func(want string) {
		t.Helper()
		var value map[string]string
		if err := readDesktopJSON(path, &value); err != nil || value["value"] != want {
			t.Fatal(value, err)
		}
	}
	write("first")
	read("first")
	read("first")
	info, _ := os.Stat(path)
	write("other")
	if err := os.Chtimes(path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	read("other")
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if err := readDesktopJSON(path, &map[string]string{}); err == nil {
		t.Fatal("cached private data bypassed permission check")
	}
	if err := os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	read("other")
	if err := os.Rename(path, path+".old"); err != nil {
		t.Fatal(err)
	}
	write("third")
	read("third")
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := readDesktopJSON(path, &map[string]string{}); err == nil {
		t.Fatal("deleted config reused cached data")
	}
	if err := os.Symlink(path+".old", path); err != nil {
		t.Fatal(err)
	}
	if err := readDesktopJSON(path, &map[string]string{}); err == nil {
		t.Fatal("symlink config accepted")
	}
}

func TestDesktopBindingNormalizesValidatedConfiguration(t *testing.T) {
	home := shortDesktopTestHome(t)
	path := filepath.Join(home, ".agent-manager", "config.json")
	if err := writeDesktopJSON(path, managedclient.Config{Server: " https://manager.invalid/ ", Token: " test-token "}); err != nil {
		t.Fatal(err)
	}
	cfg, _, err := desktopBinding(home)
	if err != nil || cfg.Server != "https://manager.invalid" || cfg.Token != "test-token" || len(cfg.Connections) != 1 {
		t.Fatal("validated config was not normalized", err)
	}
}
