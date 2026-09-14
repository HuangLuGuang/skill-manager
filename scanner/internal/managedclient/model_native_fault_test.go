package managedclient

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Native executables with a loopback fault server, never an upstream inference
// test. No real credentials or working Agent configuration are used.
func nativeFaultCommand(t *testing.T, kind, server string, parameters map[string]any) (*exec.Cmd, context.CancelFunc) {
	t.Helper()
	if os.Getenv("AM_TEST_NATIVE_FAULTS") != "1" {
		t.Skip("native fault tests require explicit opt-in")
	}
	binary, err := exec.LookPath(modelAdapters[kind].Binary)
	if err != nil {
		t.Skipf("Agent binary unavailable: %v", err)
	}
	home := t.TempDir()
	if _, err := ApplyModelConfigRevision(home, server, kind, kind, "connection-fixture", "fixture-not-a-secret", "", parameters); err != nil {
		t.Fatal(err)
	}
	args, err := modelProbeCommand(kind, "Reply with OK.")
	if err != nil {
		t.Fatal(err)
	}
	if kind == "codex" {
		instructions := filepath.Join(home, "connection-check.md")
		if err := os.WriteFile(instructions, []byte(modelProbeInstructions), 0o600); err != nil {
			t.Fatal(err)
		}
		// Disable the separate stream reconnect loop to measure the selected
		// request retry count, rather than multiplying two retry mechanisms.
		args = append([]string{"-c", "model_providers.agent_manager.stream_max_retries=0", "-c", "model_instructions_file=" + fmt.Sprintf("%q", instructions)}, args...)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	command := exec.CommandContext(ctx, binary, args...)
	command.Dir, command.Env = home, modelProbeEnvironment(home)
	command.Stdout, command.Stderr = io.Discard, io.Discard
	command.WaitDelay = time.Second
	return command, cancel
}

func TestNativeCodexRequestRetries(t *testing.T) {
	for _, retries := range []int{0, 2} {
		t.Run(fmt.Sprintf("retries_%d", retries), func(t *testing.T) {
			var requests atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == "POST" && strings.HasSuffix(r.URL.Path, "/responses") {
					requests.Add(1)
					_, _ = io.Copy(io.Discard, r.Body)
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusServiceUnavailable)
				_, _ = io.WriteString(w, `{"error":{"message":"isolated retry fixture","type":"server_error"}}`)
			}))
			defer server.Close()
			command, cancel := nativeFaultCommand(t, "codex", server.URL, map[string]any{"request_max_retries": retries})
			defer cancel()
			started := time.Now()
			err := command.Run()
			t.Logf("native Codex fault server: retries=%d requests=%d elapsed=%s process_failed=%t", retries, requests.Load(), time.Since(started).Round(time.Millisecond), err != nil)
			if err == nil || requests.Load() != int32(retries+1) {
				t.Fatalf("retry count not effective: got %d requests, want %d", requests.Load(), retries+1)
			}
		})
	}
}

func TestNativeModelTimeouts(t *testing.T) {
	for _, kind := range []string{"claude-code", "codex"} {
		for _, timeout := range []int{1000, 2500} {
			t.Run(fmt.Sprintf("%s_%dms", kind, timeout), func(t *testing.T) {
				observed := make(chan time.Duration, 8)
				requestStarted := make(chan time.Time, 1)
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if r.Method != "POST" || !(strings.HasSuffix(r.URL.Path, "/responses") || strings.HasSuffix(r.URL.Path, "/messages")) {
						http.NotFound(w, r)
						return
					}
					_, _ = io.Copy(io.Discard, r.Body)
					started := time.Now()
					select {
					case requestStarted <- started:
					default:
					}
					if kind == "codex" {
						w.Header().Set("Content-Type", "text/event-stream")
						w.WriteHeader(http.StatusOK)
						w.(http.Flusher).Flush()
					}
					select {
					case <-r.Context().Done():
					case <-time.After(20 * time.Second):
						return
					}
					select {
					case observed <- time.Since(started):
					default:
					}
				}))
				defer server.Close()
				defer server.CloseClientConnections()
				parameter := "timeout_ms"
				if kind == "codex" {
					parameter = "stream_idle_timeout_ms"
				}
				command, cancel := nativeFaultCommand(t, kind, server.URL, map[string]any{parameter: timeout})
				defer cancel()
				var output modelProbeOutput
				command.Stdout, command.Stderr = &output, &output
				if err := command.Start(); err != nil {
					t.Fatal(err)
				}
				done := make(chan error, 1)
				go func() { done <- command.Wait() }()
				var elapsed time.Duration
				finished := false
				select {
				case elapsed = <-observed:
				case err := <-done:
					finished = true
					if kind != "codex" || err == nil || !strings.Contains(output.String(), "idle timeout waiting for SSE") {
						t.Fatalf("native process ended without the expected timeout: %v; %s", err, output.String())
					}
					select {
					case started := <-requestStarted:
						elapsed = time.Since(started)
					default:
						t.Fatal("timeout reported without an observed request")
					}
				case <-time.After(15 * time.Second):
					cancel()
					<-done
					t.Fatal("native request did not time out")
				}
				cancel()
				if !finished {
					<-done
				}
				want := time.Duration(timeout) * time.Millisecond
				t.Logf("native %s fault server: %s=%d timeout_observed_after=%s", kind, parameter, timeout, elapsed.Round(time.Millisecond))
				if elapsed < want*8/10 || elapsed > want+time.Second {
					t.Fatalf("timeout not effective: observed %s, configured %s", elapsed, want)
				}
			})
		}
	}

}
