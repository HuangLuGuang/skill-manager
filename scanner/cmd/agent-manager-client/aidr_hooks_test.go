package main

import (
	"bytes"
	"context"
	"crypto/elliptic"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func TestHookPrecheckFailuresReturnNativeDeny(t *testing.T) {
	for _, input := range []string{`{`, `{"hook_event_name":"PreToolUse"}`} {
		var out bytes.Buffer
		err := aidrHook([]string{"--agent", "codex", "--event", "PreToolUse", "--socket", "/nonexistent-aidr-test/socket"}, strings.NewReader(input), &out)
		if err != nil {
			t.Fatal(err)
		}
		var result struct {
			Output struct {
				Decision string `json:"permissionDecision"`
			} `json:"hookSpecificOutput"`
		}
		if json.Unmarshal(out.Bytes(), &result) != nil || result.Output.Decision != "deny" {
			t.Fatal("failure was not a blocking decision", out.String())
		}
	}
}

func TestHookUnavailableModeAndPersistentGap(t *testing.T) {
	for _, agent := range []string{"claude", "codex"} {
		for _, mode := range []string{"audit", "plugin_pre_tool", ""} {
			for _, event := range []string{"PreToolUse", "UserPromptSubmit"} {
				t.Run(agent+"/"+mode+"/"+event, func(t *testing.T) {
					home := shortDesktopTestHome(t)
					connection, gap := filepath.Join(home, "bridge.json"), filepath.Join(home, "bridge-gap.json")
					if err := writeDesktopJSON(connection, map[string]any{"socket": filepath.Join(home, "absent.sock"), "control_mode": mode, "gap_file": gap}); err != nil {
						t.Fatal(err)
					}
					var out, diagnostics bytes.Buffer
					started := time.Now()
					err := aidrHookWithDiagnostics([]string{"--agent", agent, "--event", event, "--connection-file", connection}, strings.NewReader(`{"command":"synthetic-do-not-store-secret"}`), &out, &diagnostics)
					if time.Since(started) > time.Second {
						t.Fatal("absent receiver unnecessarily delayed hook")
					}
					if mode == "audit" {
						if err != nil || out.String() != "{}\n" || !strings.Contains(diagnostics.String(), "aidr_hook_audit_gap aidr_hook_receiver_unavailable") {
							t.Fatalf("audit blocked or hid gap: %v %s %s", err, &out, &diagnostics)
						}
						data, err := os.ReadFile(gap)
						g, readErr := hooks.ReadBridgeGap(gap)
						if err != nil || readErr != nil || g == nil || g.Hook != event || g.Agent != agent || g.Cause != "aidr_hook_receiver_unavailable" || len(data) > 1024 || bytes.Contains(data, []byte("synthetic-do-not-store-secret")) {
							t.Fatal("missing or unsafe persistent diagnostic", err, readErr)
						}
						info, _ := os.Stat(gap)
						if info.Mode().Perm() != 0600 {
							t.Fatal("public diagnostic")
						}
					} else if event == "PreToolUse" {
						if err != nil || !strings.Contains(out.String(), `"permissionDecision":"deny"`) || !strings.Contains(out.String(), "aidr_hook_receiver_unavailable") {
							t.Fatalf("control/unknown failed open: %v %s", err, &out)
						}
					} else if err == nil {
						t.Fatal("unknown non-tool hook failure hidden")
					}
				})
			}
		}
	}
}

func TestHookLiveAuditOverloadAndControlOverride(t *testing.T) {
	home := shortDesktopTestHome(t)
	s, err := hooks.OpenStore(filepath.Join(home, "state"), "http://127.0.0.1:41901", "test-device", 1)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	socket, connection, gap := filepath.Join(home, "h.sock"), filepath.Join(home, "bridge.json"), filepath.Join(home, "bridge-gap.json")
	r, err := hooks.Listen(socket, s)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	t.Cleanup(func() { cancel(); <-done; r.Close() })
	if err := writeDesktopJSON(connection, map[string]any{"socket": socket, "control_mode": "audit", "gap_file": gap}); err != nil {
		t.Fatal(err)
	}
	input := `{"hook_event_name":"PreToolUse","session_id":"s","tool_use_id":"c","tool_name":"Bash","tool_input":{"command":"true"}}`
	invoke := func(raw string) (string, string) {
		t.Helper()
		var out, diag bytes.Buffer
		if err := aidrHookWithDiagnostics([]string{"--agent", "codex", "--event", "PreToolUse", "--connection-file", connection}, strings.NewReader(raw), &out, &diag); err != nil {
			t.Fatal(err)
		}
		return out.String(), diag.String()
	}
	if out, diag := invoke(input); out != "{}\n" || diag != "" {
		t.Fatal("healthy audit changed", out, diag)
	}
	if out, diag := invoke(input); out != "{}\n" || !strings.Contains(diag, "aidr_hook_audit_gap") {
		t.Fatal("overloaded audit blocked or gap hidden", out, diag)
	}
	status, err := s.Status(ctx)
	if err != nil || status.Queued != 1 {
		t.Fatal("overload rewrote queue", status, err)
	}
	frozen, err := s.Prepare(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 200; i++ {
		if out, _ := invoke(input); out != "{}\n" {
			t.Fatal("overload blocked audit", out)
		}
	}
	after, err := s.Prepare(ctx)
	if err != nil || after.Digest != frozen.Digest || !bytes.Equal(after.Payload, frozen.Payload) {
		t.Fatal("gap changed frozen batch", err)
	}
	entries, _ := os.ReadDir(home)
	if len(entries) != 4 {
		t.Fatal("gap reporting grew retained files", len(entries))
	}
	if err := s.Acknowledge(ctx, status.Device, status.Stream, frozen.Digest, frozen.Count, true); err != nil {
		t.Fatal(err)
	}
	if err := writeDesktopJSON(connection, map[string]any{"socket": socket, "control_mode": "plugin_pre_tool", "gap_file": gap}); err != nil {
		t.Fatal(err)
	}
	if out, _ := invoke(input); out != "{}\n" {
		t.Fatal("applied audit mode did not supersede stale bridge mode", out)
	}
	// ACK that audit record without rewriting it, then test a pinned receiver.
	frozen, err = s.Prepare(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Acknowledge(ctx, status.Device, status.Stream, frozen.Digest, frozen.Count, true); err != nil {
		t.Fatal(err)
	}
	if err := writeDesktopJSON(connection, map[string]any{"socket": socket, "control_mode": "audit", "gap_file": gap}); err != nil {
		t.Fatal(err)
	}
	// A live pinned control receiver must override a stale audit connection.
	x, y := elliptic.P256().ScalarBaseMult([]byte{1})
	if err := s.ConfigureControl(ctx, elliptic.Marshal(elliptic.P256(), x, y)); err != nil {
		t.Fatal(err)
	}
	if out, _ := invoke(input); !strings.Contains(out, `"permissionDecision":"deny"`) || !strings.Contains(out, "aidr_hook_policy_missing") {
		t.Fatal("missing control policy bypassed", out)
	}
}

func TestHookAuditInputFailureAndUntrustedConnection(t *testing.T) {
	home := shortDesktopTestHome(t)
	path, gap := filepath.Join(home, "bridge.json"), filepath.Join(home, "bridge-gap.json")
	if err := writeDesktopJSON(path, map[string]any{"socket": filepath.Join(home, "h.sock"), "control_mode": "audit", "gap_file": gap}); err != nil {
		t.Fatal(err)
	}
	var out, diag bytes.Buffer
	args := []string{"--agent", "claude", "--event", "PreToolUse", "--connection-file", path}
	if err := aidrHookWithDiagnostics(args, strings.NewReader("{"), &out, &diag); err != nil || out.String() != "{}\n" || !strings.Contains(diag.String(), "aidr_hook_record_invalid") {
		t.Fatal("invalid audit input did not expose gap", err, &out, &diag)
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	diag.Reset()
	if err := aidrHookWithDiagnostics(args, strings.NewReader("{}"), &out, &diag); err != nil || !strings.Contains(out.String(), `"permissionDecision":"deny"`) {
		t.Fatal("public audit declaration authorized failure", err, &out)
	}
}

func TestDesktopBridgeModeTracksExplicitControlAndQueueBinding(t *testing.T) {
	home := shortDesktopTestHome(t)
	paths := desktopPaths{Socket: filepath.Join(home, "h.sock"), State: filepath.Join(home, "state"), Connection: filepath.Join(home, "bridge.json")}
	for _, mode := range []string{"audit", "intercept"} {
		if err := writeDesktopConnection(paths, desktopPreferences{Enabled: true, PublicKey: "/private/operator-key", HookMode: mode}); err != nil {
			t.Fatal(err)
		}
		var cfg map[string]any
		if err := readDesktopJSON(paths.Connection, &cfg); err != nil {
			t.Fatal(err)
		}
		want := "audit"
		if mode == "intercept" {
			want = "plugin_pre_tool"
		}
		if cfg["control_mode"] != want || cfg["gap_file"] != filepath.Join(paths.State, "bridge-gap.json") {
			t.Fatal("connection mode or destination differs from receiver", cfg)
		}
	}
}

func TestLegacyDesktopConnectionResolvesOnlyMatchingPrivateBinding(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:41901", Token: "fictional"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(paths.State, 0700); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"", "/private/pinned-public-key"} {
		if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), desktopPreferences{Enabled: true, PublicKey: key}); err != nil {
			t.Fatal(err)
		}
		if err := writeDesktopJSON(paths.Connection, map[string]any{"socket": paths.Socket, "active": true}); err != nil {
			t.Fatal(err)
		}
		var out, diag bytes.Buffer
		if err := aidrHookWithDiagnostics([]string{"--agent", "codex", "--event", "PreToolUse", "--connection-file", paths.Connection}, strings.NewReader("{}"), &out, &diag); err != nil {
			t.Fatal(err)
		}
		if key == "" && (out.String() != "{}\n" || !strings.Contains(diag.String(), "aidr_hook_audit_gap")) {
			t.Fatal("existing audit connection remained blocking", &out, &diag)
		}
		if key != "" && !strings.Contains(out.String(), `"permissionDecision":"deny"`) {
			t.Fatal("existing control connection failed open", &out)
		}
	}
	if err := writeDesktopJSON(paths.Connection, map[string]any{"socket": filepath.Join(home, "other.sock"), "active": true}); err != nil {
		t.Fatal(err)
	}
	var out, diag bytes.Buffer
	if err := aidrHookWithDiagnostics([]string{"--agent", "codex", "--event", "PreToolUse", "--connection-file", paths.Connection}, strings.NewReader("{}"), &out, &diag); err != nil || !strings.Contains(out.String(), `"permissionDecision":"deny"`) {
		t.Fatal("unmatched legacy socket inherited audit mode", err, &out)
	}
}

func TestPausedAndManagedConnectionsDoNotDuplicateOrdinaryHooks(t *testing.T) {
	home := shortDesktopTestHome(t)
	path := filepath.Join(home, "bridge.json")
	for _, cfg := range []map[string]any{
		{"socket": "/nonexistent/socket", "active": false, "access_mode": "ordinary"},
		{"socket": "/nonexistent/socket", "active": true, "access_mode": "managed"},
		{"socket": "/nonexistent/socket", "active": true, "access_mode": "ordinary", "agents": []string{"claude"}},
	} {
		if err := writeDesktopJSON(path, cfg); err != nil {
			t.Fatal(err)
		}
		var out bytes.Buffer
		if err := aidrHook([]string{"--agent", "codex", "--event", "PreToolUse", "--connection-file", path}, strings.NewReader(`{"hook_event_name":"PreToolUse"}`), &out); err != nil || out.Len() != 0 {
			t.Fatal("inactive path should not collect or deny", err, out.String())
		}
	}
	var out bytes.Buffer
	if err := aidrManagedInstall([]string{"--agent", "codex", "--action", "install", "--path", "/other"}, &out); err == nil || err.Error() != "aidr_managed_action_invalid" {
		t.Fatal("arbitrary privileged path accepted", err)
	}
}
