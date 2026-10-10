package main

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestHookEnrollmentOfflineDurabilityAndAuthority(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("WorkBuddy adapter is macOS")
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
	yes := true
	prefs := desktopPreferences{Hosts: map[string]desktopHost{}, ManagedTask: 7, ManagedServer: cfg.Server, ManagedDevice: paths.Device,
		RuntimePolicy: &desktopRuntimePolicy{Version: "1", Target: managedclient.RuntimeGovernancePolicy{
			AllowUserEnrollment: &yes, Enabled: true, Hosts: []string{"codex"}, Installation: "automatic", AccessMode: "ordinary", Updates: "manual",
			Retry: managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 60},
		}}}
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		var out bytes.Buffer
		args := []string{"--home", home, "--action", "enroll", "--agent", "workbuddy"}
		if i == 1 {
			args = []string{"--home", home, "--agent", "workbuddy", "--action=enroll"}
		}
		if err = aidrDesktop(args, &out); err != nil {
			t.Fatal(err)
		}
	}
	after, err := loadDesktopPreferences(home)
	if err != nil || len(after.Enrollment.Hosts) != 1 || after.Enrollment.Hosts[0] != "workbuddy" || after.Enabled || len(after.RuntimePolicy.Target.Hosts) != 1 {
		t.Fatal("enrollment must wait for platform scope", err)
	}
	request, ok := aidrRuntimeSnapshot(home)["user_hook_hosts"].([]string)
	if !ok || len(request) != 1 || request[0] != "workbuddy" {
		t.Fatal("durable heartbeat request absent")
	}
	other := cfg
	other.Server = "http://127.0.0.1:41902"
	if len(desktopEnrollmentHosts(after, other, paths)) != 0 {
		t.Fatal("enrollment leaked to another server")
	}
	if err = aidrDesktop([]string{"--home", home, "--action", "disconnect", "--agent", "workbuddy"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	after, _ = loadDesktopPreferences(home)
	if len(after.Enrollment.Hosts) != 0 {
		t.Fatal("uninstall left enrollment active")
	}
	no := false
	prefs.RuntimePolicy.Target.AllowUserEnrollment = &no
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	if err = aidrDesktop([]string{"--home", home, "--action", "enroll", "--agent", "workbuddy"}, &bytes.Buffer{}); err == nil || err.Error() != "aidr_enrollment_policy_blocked" {
		t.Fatal("admin range bypassed", err)
	}
}
