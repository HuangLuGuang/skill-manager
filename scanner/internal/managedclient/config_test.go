package managedclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
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
	if len(loaded.Connections) != 1 || loaded.Connections[0].Server != "http://manager" || loaded.Connections[0].Token != "secret" {
		t.Fatalf("active connection was not migrated into saved connections: %#v", loaded.Connections)
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
}

func TestWindowsServiceRegistrationUsesDirectUnicodeAction(t *testing.T) {
	executable := `C:\Users\测试用户\AppData\Local\智能体生命周期管理系统客户端\agent-manager-client.exe`
	home := `C:\Users\测试用户`
	script := windowsServiceRegistrationScript(windowsServiceTaskName, executable, home, `DESKTOP\测试用户`, true)
	for _, expected := range []string{
		"New-ScheduledTaskAction -Execute '" + executable + "'",
		`-Argument 'run --home "C:\Users\测试用户"'`,
		"New-ScheduledTaskPrincipal -UserId 'DESKTOP\\测试用户' -LogonType Interactive -RunLevel Limited",
		"New-ScheduledTaskTrigger -AtLogOn -User 'DESKTOP\\测试用户'",
		"Start-ScheduledTask",
	} {
		if !strings.Contains(script, expected) {
			t.Fatalf("Windows registration script missing %q: %s", expected, script)
		}
	}
	if strings.Contains(strings.ToLower(script), ".cmd") {
		t.Fatalf("Windows registration retained a batch-file action: %s", script)
	}
}

func TestPowerShellLiteralEscapesApostrophe(t *testing.T) {
	if got := powershellLiteral(`C:\Users\O'Brien`); got != `'C:\Users\O''Brien'` {
		t.Fatalf("unexpected PowerShell literal %q", got)
	}
}

func TestSaveConfigPreservesAndDeduplicatesConnections(t *testing.T) {
	home := t.TempDir()
	config := Config{
		Server: " https://manager-a.example/ ", Token: " token-a ", Name: " Manager A ",
		Connections: []SavedConnection{
			{Server: "https://manager-b.example/", Token: "token-b", Name: "Manager B"},
			{Server: "https://manager-a.example", Token: "stale-token", Name: "Stale"},
		},
	}
	if err := SaveConfig(home, config); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadConfig(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(loaded.Connections) != 2 {
		t.Fatalf("unexpected saved connections: %#v", loaded.Connections)
	}
	if loaded.Connections[0].Server != "https://manager-a.example" || loaded.Connections[0].Token != "token-a" || loaded.Connections[0].Name != "Manager A" {
		t.Fatalf("active connection was not normalized and kept first: %#v", loaded.Connections[0])
	}
	if saved, ok := loaded.FindConnection("https://manager-b.example/"); !ok || saved.Token != "token-b" {
		t.Fatalf("saved connection lookup failed: %#v ok=%v", saved, ok)
	}
}

func TestStopServiceForUpdateIsNoopWhenServiceIsNotInstalled(t *testing.T) {
	state, err := StopServiceForUpdate(t.TempDir())
	if err != nil {
		t.Fatalf("stop service without installation: %v", err)
	}
	if state.Installed || state.Running {
		t.Fatalf("unexpected service state: %+v", state)
	}
}

func TestServiceRegistrationDetectsExecutableChanges(t *testing.T) {
	home := t.TempDir()
	executable := filepath.Join(t.TempDir(), "agent-manager-client")
	if err := os.WriteFile(executable, []byte("first build"), 0o700); err != nil {
		t.Fatal(err)
	}
	if matches, err := serviceRegistrationMatches(home, executable); err != nil || matches {
		t.Fatalf("missing registration should not match: %v %v", matches, err)
	}
	if err := writeServiceRegistration(home, executable); err != nil {
		t.Fatal(err)
	}
	if recent, err := serviceRecentlyRestarted(home, 10*time.Second); err != nil || !recent {
		t.Fatalf("fresh service registration did not record its restart: %v %v", recent, err)
	}
	if matches, err := serviceRegistrationMatches(home, executable); err != nil || !matches {
		t.Fatalf("fresh registration should match: %v %v", matches, err)
	}
	if err := os.WriteFile(executable, []byte("second build"), 0o700); err != nil {
		t.Fatal(err)
	}
	if matches, err := serviceRegistrationMatches(home, executable); err != nil || matches {
		t.Fatalf("changed executable should require restart: %v %v", matches, err)
	}
}

func TestServiceReconcileDecision(t *testing.T) {
	tests := []struct {
		name       string
		state      ServiceState
		matches    bool
		force      bool
		recent     bool
		restart    bool
		reasonWant string
	}{
		{name: "first_connection", state: ServiceState{}, restart: true, reasonWant: "not_installed"},
		{name: "stopped", state: ServiceState{Installed: true}, matches: true, restart: true, reasonWant: "not_running"},
		{name: "changed", state: ServiceState{Installed: true, Running: true}, restart: true, reasonWant: "binary_changed"},
		{name: "current", state: ServiceState{Installed: true, Running: true}, matches: true, reasonWant: "already_current"},
		{name: "forced", state: ServiceState{Installed: true, Running: true}, matches: true, force: true, restart: true, reasonWant: "forced"},
		{name: "coalesced", state: ServiceState{Installed: true, Running: true}, matches: true, force: true, recent: true, reasonWant: "recently_restarted"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			restart, reason := serviceReconcileDecision(test.state, test.matches, test.force, test.recent)
			if restart != test.restart || reason != test.reasonWant {
				t.Fatalf("unexpected decision: restart=%v reason=%s", restart, reason)
			}
		})
	}
}

func TestServiceCommandRequiresAnActuallyRunningProcess(t *testing.T) {
	if !serviceCommandIsRunning("darwin", []byte("state = running\npid = 42"), nil) {
		t.Fatal("running launchd service was not detected")
	}
	if serviceCommandIsRunning("darwin", []byte("state = waiting"), nil) {
		t.Fatal("loaded but stopped launchd service was reported as running")
	}
	if !serviceCommandIsRunning("linux", []byte("active\n"), nil) {
		t.Fatal("active systemd service was not detected")
	}
	if !serviceCommandIsRunning("windows", []byte("Running\r\n"), nil) {
		t.Fatal("running scheduled task was not detected")
	}
}

func TestDarwinServiceDefinitionMustMatchCurrentHome(t *testing.T) {
	expected := "/Users/example/Library/LaunchAgents/com.agent-manager.client.plist"
	matching := []byte("path = " + expected + "\nstate = running\n")
	if !darwinServiceDefinitionMatches(matching, expected) {
		t.Fatal("current launch agent definition was not recognized")
	}
	stale := []byte("path = /private/tmp/old-home/Library/LaunchAgents/com.agent-manager.client.plist\nstate = running\n")
	if darwinServiceDefinitionMatches(stale, expected) {
		t.Fatal("launch agent from another home was accepted as current")
	}
	if darwinServiceDefinitionMatches([]byte("state = running\n"), expected) {
		t.Fatal("launch agent without a definition path was accepted as current")
	}
}

func TestDarwinServiceDefinitionAcceptsEquivalentSymlinkPath(t *testing.T) {
	root := t.TempDir()
	realRoot := filepath.Join(root, "real")
	if err := os.MkdirAll(realRoot, 0o700); err != nil {
		t.Fatal(err)
	}
	aliasRoot := filepath.Join(root, "alias")
	if err := os.Symlink(realRoot, aliasRoot); err != nil {
		t.Fatal(err)
	}
	expected := filepath.Join(aliasRoot, "com.agent-manager.client.plist")
	if err := os.WriteFile(filepath.Join(realRoot, "com.agent-manager.client.plist"), []byte("test"), 0o600); err != nil {
		t.Fatal(err)
	}
	loaded := []byte("path = " + filepath.Join(realRoot, "com.agent-manager.client.plist") + "\nstate = running\n")
	if !darwinServiceDefinitionMatches(loaded, expected) {
		t.Fatal("equivalent symlinked launch agent path was rejected")
	}
}
