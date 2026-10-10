//go:build !windows

package hooks

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestNativeQueryTimeoutStopsDescendants(t *testing.T) {
	for _, query := range []string{"rpc", "cli"} {
		t.Run(query, func(t *testing.T) {
			home := t.TempDir()
			binary := filepath.Join(home, "host")
			// The detached standard streams reproduce the child that survives
			// CommandContext's default parent-only kill.
			script := "#!/bin/sh\n(sleep 0.6; touch \"$CODEX_HOME/child-wrote\") </dev/null >/dev/null 2>&1 &\ntouch \"$CODEX_HOME/ready\"\nsleep 10\n"
			if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			unrelated := exec.Command("sh", "-c", "sleep 0.6; touch \"$1\"", "sh", filepath.Join(home, "unrelated-wrote"))
			if err := unrelated.Start(); err != nil {
				t.Fatal(err)
			}
			defer unrelated.Wait()
			ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
			defer cancel()
			start := time.Now()
			var err error
			if query == "rpc" {
				_, err = nativeCodexCallsChecked(ctx, binary, home, []nativeCodexRequest{{method: "plugin/list"}})
			} else {
				_, err = hostCommand(ctx, binary, "codex", home, "--version")
			}
			if err == nil {
				t.Fatal("expected query timeout")
			}
			if time.Since(start) > 2*time.Second {
				t.Fatal("timeout did not unblock query")
			}
			if _, err := os.Stat(filepath.Join(home, "ready")); err != nil {
				t.Fatal("fixture did not spawn child", err)
			}
			time.Sleep(800 * time.Millisecond)
			if _, err := os.Stat(filepath.Join(home, "child-wrote")); !os.IsNotExist(err) {
				t.Fatal("query child survived cancellation", err)
			}
			if _, err := os.Stat(filepath.Join(home, "unrelated-wrote")); err != nil {
				t.Fatal("unrelated process was affected", err)
			}
		})
	}
}

func TestNativeCommandSuccessStopsLeftoverDescendants(t *testing.T) {
	home := t.TempDir()
	binary := filepath.Join(home, "host")
	script := "#!/bin/sh\n(sleep 0.4; touch \"$CODEX_HOME/child-wrote\") </dev/null >/dev/null 2>&1 &\nprintf 'version'\n"
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	out, err := hostCommand(context.Background(), binary, "codex", home, "--version")
	if err != nil || string(out) != "version" {
		t.Fatal(string(out), err)
	}
	time.Sleep(700 * time.Millisecond)
	if _, err := os.Stat(filepath.Join(home, "child-wrote")); !os.IsNotExist(err) {
		t.Fatal("child survived successful query", err)
	}
}
