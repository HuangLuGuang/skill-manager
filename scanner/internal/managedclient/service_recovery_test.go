package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// Exercise the production reconciliation path against a private service-manager
// fixture. No real per-user service is stopped or replaced by this test.
func TestServiceActivationFailureRollsBackAndChecksRecovery(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("macOS service-manager fixture")
	}
	for _, failures := range []string{"1", "2"} {
		t.Run(failures, func(t *testing.T) {
			home := t.TempDir()
			if err := SaveConfig(home, Config{Server: "http://127.0.0.1:1", Token: "fixture"}); err != nil {
				t.Fatal(err)
			}
			source := filepath.Join(home, "bundled-worker")
			if err := os.WriteFile(source, []byte("old"), 0700); err != nil {
				t.Fatal(err)
			}
			old, err := stageServiceBinary(home, source)
			if err != nil {
				t.Fatal(err)
			}
			if err = writeServiceRegistration(home, old); err != nil {
				t.Fatal(err)
			}
			plist, body, _ := ServiceDefinition(home, old, "darwin")
			if err = os.MkdirAll(filepath.Dir(plist), 0700); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(plist, []byte(body), 0600); err != nil {
				t.Fatal(err)
			}
			release, err := AcquireRunLock(home)
			if err != nil {
				t.Fatal(err)
			}
			defer release()
			if err = writeDaemonHealth(home); err != nil {
				t.Fatal(err)
			}
			bin := filepath.Join(home, "mock-bin")
			if err = os.MkdirAll(bin, 0700); err != nil {
				t.Fatal(err)
			}
			script := `#!/bin/sh
case "$1" in
print)
  test -f "$TEST_SERVICE_HOME/running" || exit 1
  printf 'state = running\npath = %s/Library/LaunchAgents/com.agent-manager.client.plist\n' "$TEST_SERVICE_HOME"
  ;;
bootout) rm -f "$TEST_SERVICE_HOME/running" ;;
bootstrap)
  left=$(cat "$TEST_SERVICE_HOME/failures")
  if test "$left" -gt 0; then
    echo $((left - 1)) > "$TEST_SERVICE_HOME/failures"
    exit 1
  fi
  touch "$TEST_SERVICE_HOME/running"
  ;;
*) exit 2 ;;
esac
`
			if err = os.WriteFile(filepath.Join(bin, "launchctl"), []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
			t.Setenv("TEST_SERVICE_HOME", home)
			if err = os.WriteFile(filepath.Join(home, "running"), nil, 0600); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(filepath.Join(home, "failures"), []byte(failures), 0600); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(source, []byte("new"), 0700); err != nil {
				t.Fatal(err)
			}
			_, err = ReconcileService(home, source, false)
			want := "client_service_update_rolled_back"
			if failures == "2" {
				want = "client_service_recovery_failed"
			}
			if err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("recovery result: %v", err)
			}
			if failures == "1" {
				var registration serviceRegistration
				data, _ := os.ReadFile(serviceRegistrationPath(home))
				if json.Unmarshal(data, &registration) != nil || registration.Executable != old || !daemonIsReady(home) {
					t.Fatal("old worker was not verified after rollback")
				}
			}
		})
	}
}
