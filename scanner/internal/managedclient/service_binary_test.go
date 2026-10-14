package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestServiceVersionsSurviveBundleReplacement(t *testing.T) {
	home := t.TempDir()
	source := filepath.Join(home, "bundle-client")
	if err := os.WriteFile(source, []byte("old worker"), 0700); err != nil {
		t.Fatal(err)
	}
	old, err := stageServiceBinary(home, source)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(source, []byte("new worker"), 0700); err != nil {
		t.Fatal(err)
	}
	current, err := stageServiceBinary(home, source)
	if err != nil || old == current {
		t.Fatal("versions were overwritten", err)
	}
	if err = os.Remove(source); err != nil {
		t.Fatal(err)
	}
	for path, want := range map[string]string{old: "old worker", current: "new worker"} {
		body, err := os.ReadFile(path)
		if err != nil || string(body) != want {
			t.Fatal("bundle removal destroyed worker/rollback", path, err)
		}
	}
	if _, err := stageServiceBinary(home, source); err == nil {
		t.Fatal("missing source staged")
	}
	if body, err := os.ReadFile(old); err != nil || string(body) != "old worker" {
		t.Fatal("failed staging damaged old worker")
	}
}

func TestDaemonReadinessRequiresFreshHealthAndLiveLock(t *testing.T) {
	home := t.TempDir()
	release, err := AcquireRunLock(home)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	if err = writeDaemonHealth(home); err != nil {
		t.Fatal(err)
	}
	if !daemonIsReady(home) {
		t.Fatal("live daemon not ready")
	}
	body, _ := json.Marshal(daemonHealth{PID: os.Getpid(), UpdatedAt: time.Now().Add(-time.Minute)})
	if err = os.WriteFile(filepath.Join(RuntimeRoot(home), "daemon-health.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
	if daemonIsReady(home) {
		t.Fatal("stale daemon marked ready")
	}
	if err = writeDaemonHealth(home); err != nil {
		t.Fatal(err)
	}
	release()
	if daemonIsReady(home) {
		t.Fatal("unlocked daemon marked ready")
	}
}
