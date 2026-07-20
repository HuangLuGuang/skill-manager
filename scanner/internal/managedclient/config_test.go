package managedclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestConfigAndServiceDefinitions(t *testing.T) {
	home := t.TempDir()
	config := Config{Server: "http://manager/", Token: "secret", Name: "Dev Mac"}
	if err := SaveConfig(home, config); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadConfig(home)
	if err != nil || loaded.Server != "http://manager" || loaded.Token != "secret" {
		t.Fatalf("unexpected config %#v %v", loaded, err)
	}
	info, err := os.Stat(filepath.Join(home, ".agent-manager", "config.json"))
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("config permissions are not private: %v %v", info, err)
	}
	macPath, macBody, err := ServiceDefinition(home, "/Applications/Agent Manager Client/client", "darwin")
	if err != nil || !strings.Contains(macPath, "LaunchAgents") || !strings.Contains(macBody, "<key>KeepAlive</key>") {
		t.Fatalf("invalid macOS service: %s %s %v", macPath, macBody, err)
	}
	linuxPath, linuxBody, err := ServiceDefinition(home, "/opt/agent manager/client", "linux")
	if err != nil || !strings.Contains(linuxPath, "systemd") || !strings.Contains(linuxBody, `"/opt/agent manager/client" run`) {
		t.Fatalf("invalid Linux service: %s %s %v", linuxPath, linuxBody, err)
	}
	windowsPath, windowsBody, err := ServiceDefinition(home, `C:\Program Files\Agent Manager\client.exe`, "windows")
	if err != nil || !strings.HasSuffix(windowsPath, "agent-manager-client.cmd") || !strings.Contains(windowsBody, "client.exe\"") {
		t.Fatalf("invalid Windows service: %s %s %v", windowsPath, windowsBody, err)
	}
}
