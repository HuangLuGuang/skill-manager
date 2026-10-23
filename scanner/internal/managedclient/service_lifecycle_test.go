package managedclient

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Opt in because this test loads a real, uniquely named user launch agent.
func TestMacLaunchAgentLifecycle(t *testing.T) {
	if runtime.GOOS != "darwin" || os.Getenv("AGENT_MANAGER_TEST_LAUNCHD") != "1" {
		t.Skip("set AGENT_MANAGER_TEST_LAUNCHD=1 on macOS to verify real launchd lifecycle")
	}
	home := t.TempDir()
	binary := filepath.Join(home, "client")
	build := exec.Command("go", "build", "-o", binary, "./cmd/agent-manager-client")
	build.Dir = filepath.Join("..", "..")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	if err := SaveConfig(home, Config{Server: "http://127.0.0.1:1", Token: "isolated-lifecycle-test"}); err != nil {
		t.Fatal(err)
	}
	path, body, err := ServiceDefinition(home, binary, "darwin")
	if err != nil {
		t.Fatal(err)
	}
	label := fmt.Sprintf("com.agent-manager.client.test-%d-%d", os.Getpid(), time.Now().UnixNano())
	body = strings.Replace(body, "<string>com.agent-manager.client</string>", "<string>"+label+"</string>", 1)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(home, ".agent-manager", "logs"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	if output, err := exec.Command("plutil", "-lint", path).CombinedOutput(); err != nil {
		t.Fatalf("invalid plist: %v %s", err, output)
	}
	domain := fmt.Sprintf("gui/%d", os.Getuid())
	service := domain + "/" + label
	loaded := false
	defer func() {
		if loaded {
			if output, err := exec.Command("launchctl", "bootout", service).CombinedOutput(); err != nil {
				t.Errorf("test service cleanup failed: %v %s", err, output)
			}
		}
	}()
	if output, err := exec.Command("launchctl", "bootstrap", domain, path).CombinedOutput(); err != nil {
		t.Fatalf("bootstrap: %v %s", err, output)
	}
	loaded = true
	pidPattern := regexp.MustCompile(`(?m)^\s*pid = (\d+)\s*$`)
	waitPID := func(previous int) int {
		t.Helper()
		deadline := time.Now().Add(25 * time.Second)
		for time.Now().Before(deadline) {
			output, err := exec.Command("launchctl", "print", service).CombinedOutput()
			match := pidPattern.FindSubmatch(output)
			if err == nil && len(match) == 2 && strings.Contains(string(output), "state = running") {
				pid, _ := strconv.Atoi(string(match[1]))
				if pid > 0 && pid != previous && daemonIsReady(home) {
					return pid
				}
			}
			time.Sleep(100 * time.Millisecond)
		}
		for _, name := range []string{"logs/client.log", "logs/client-error.log", "daemon-health.json", "client.lock"} {
			body, _ := os.ReadFile(filepath.Join(RuntimeRoot(home), name))
			if len(body) > 2000 {
				body = body[len(body)-2000:]
			}
			t.Logf("%s: %s", name, body)
		}
		if store, err := OpenStore(filepath.Join(RuntimeRoot(home), "client.db")); err == nil {
			for _, key := range []string{"sync:daemon_health:error", "sync:watcher:error", "diagnostics:daemon"} {
				value, _, _ := store.State(key)
				t.Logf("%s: %s", key, value)
			}
			store.Close()
		}
		t.Fatal("launchd did not start a new running process")
		return 0
	}
	first := waitPID(0)
	// The bootstrap command has exited; launchd owns the running process.
	if output, err := exec.Command("launchctl", "kill", "SIGKILL", service).CombinedOutput(); err != nil {
		t.Fatalf("terminate isolated child: %v %s", err, output)
	}
	second := waitPID(first)
	if second == first {
		t.Fatal("KeepAlive did not restart the client")
	}
	if output, err := exec.Command("launchctl", "bootout", service).CombinedOutput(); err != nil {
		t.Fatalf("bootout: %v %s", err, output)
	}
	loaded = false
	// bootout may return before launchd finishes removing the service record.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if err := exec.Command("launchctl", "print", service).Run(); err != nil {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("test launch agent remained loaded")
}
