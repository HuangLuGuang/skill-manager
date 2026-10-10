package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestNativeDesktopRemovalWithdrawsOnlyVerifiedEnrollment(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("desktop shell fixture")
	}
	for _, fail := range []bool{false, true} {
		home := shortDesktopTestHome(t)
		cfg := managedclient.Config{Server: "http://127.0.0.1:41901", Token: "fictional"}
		if err := managedclient.SaveConfig(home, cfg); err != nil {
			t.Fatal(err)
		}
		_, paths, err := desktopBinding(home)
		if err != nil {
			t.Fatal(err)
		}
		quote := func(s string) string { raw, _ := json.Marshal(s); return string(raw) }
		bridge := filepath.Join(home, "plugin/scripts/bridge.sh")
		os.MkdirAll(filepath.Dir(bridge), 0700)
		// The connection path is generated from a private temporary home.
		os.WriteFile(bridge, []byte("--connection-file '"+paths.Connection+"' --agent claude"), 0600)
		listed, _ := json.Marshal([]any{map[string]any{"id": "aidr-claude@aidr-local", "enabled": true, "version": "0.1.1", "installPath": filepath.Dir(filepath.Dir(bridge))}})
		marker := filepath.Join(home, "removed")
		binary := filepath.Join(home, "claude")
		mutation := "touch " + quote(marker)
		if fail {
			mutation = "exit 1"
		}
		script := "#!/bin/sh\ncase \"$1 $2\" in\n'--version ') echo 'fixture';;\n'plugin list') if [ -f " + quote(marker) + " ]; then echo '[]'; else cat <<'INVENTORY'\n" + string(listed) + "\nINVENTORY\nfi;;\n'plugin uninstall') " + mutation + ";;\nesac\n"
		if err = os.WriteFile(binary, []byte(script), 0700); err != nil {
			t.Fatal(err)
		}
		yes := true
		prefs := desktopPreferences{Enabled: true, Hosts: map[string]desktopHost{"claude": {Binary: binary, Home: home}}, ManagedTask: 7, ManagedServer: cfg.Server, ManagedDevice: paths.Device,
			Enrollment:    &desktopHookEnrollment{Server: cfg.Server, Device: paths.Device, Hosts: []string{"claude", "workbuddy"}},
			RuntimePolicy: &desktopRuntimePolicy{Version: "1", Target: managedclient.RuntimeGovernancePolicy{AllowUserEnrollment: &yes, Enabled: true, Hosts: []string{"claude", "workbuddy"}, Installation: "manual", AccessMode: "ordinary", Updates: "manual", Retry: managedclient.ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 60}}}}
		if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
			t.Fatal(err)
		}
		err = aidrDesktop([]string{"--home", home, "--action", "disconnect", "--agent", "claude"}, &bytes.Buffer{})
		if fail && (err == nil || err.Error() != "aidr_plugin_remove_failed") || !fail && err != nil {
			t.Fatal(err)
		}
		after, err := loadDesktopPreferences(home)
		if err != nil || !after.Enabled || after.ManagedTask != 7 || len(after.RuntimePolicy.Target.Hosts) != 2 {
			t.Fatal("shared runtime or platform target changed", err)
		}
		want := 1
		if fail {
			want = 2
		}
		if after.Enrollment == nil || len(after.Enrollment.Hosts) != want || after.Enrollment.Hosts[want-1] != "workbuddy" {
			t.Fatal("wrong enrollment withdrawal")
		}
	}
}
