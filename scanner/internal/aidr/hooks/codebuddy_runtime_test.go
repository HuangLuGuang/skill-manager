package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"testing"
	"time"
)

// Opt-in receiver for a real IDE test. It signs its own isolated rules, stores
// locally, and removes only its generated project hooks when finished.
func TestCodeBuddyLocalRuntime(t *testing.T) {
	root, project, binary := os.Getenv("CODEBUDDY_TEST_OUTPUT"), os.Getenv("CODEBUDDY_TEST_PROJECT"), os.Getenv("CODEBUDDY_TEST_BINARY")
	if root == "" {
		t.Skip("real IDE test not requested")
	}
	for _, p := range []string{root, project, binary} {
		if !filepath.IsAbs(p) {
			t.Fatal("absolute test paths required")
		}
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	s, err := OpenStore(filepath.Join(root, "hook-state"), "http://127.0.0.1:1", "one", 1000)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	policy := agentlog.AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &agentlog.CaptureScope{Prompt: true, ToolOutput: true, FileBody: true, ModelResponse: true}}
	if err = s.SetPolicy(ctx, policy); err != nil {
		t.Fatal(err)
	}
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err = s.ConfigureControl(ctx, elliptic.Marshal(elliptic.P256(), key.X, key.Y)); err != nil {
		t.Fatal(err)
	}
	p := ToolPolicy{Schema: 3, Domain: "aidr.tool-policy/3", Device: "one", Revision: "1", Issued: fmt.Sprint(time.Now().Unix()), Default: "allow", Rules: []ToolRule{
		{ID: "deny-marker", Agent: "codebuddy", Tool: "Bash", Decision: "deny", Command: &CommandCondition{Executable: "touch", ArgsAny: []string{"blocked-marker.txt", filepath.Join(project, "blocked-marker.txt")}}},
		{ID: "deny-mcp", Agent: "codebuddy", Tool: "mcp__aidr_probe__deny_probe", Decision: "deny"},
	}}
	if err = s.ApplyToolPolicy(ctx, signGrant(t, key, p), time.Now()); err != nil {
		t.Fatal(err)
	}
	if err = s.SetControlMode("intercept"); err != nil {
		t.Fatal(err)
	}
	socketDir, err := os.MkdirTemp("/private/tmp", "cb-aidr-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(socketDir)
	socket := filepath.Join(socketDir, "hook.sock")
	r, err := Listen(socket, s)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	connection := filepath.Join(root, "bridge.json")
	raw, _ := json.Marshal(map[string]any{"socket": socket, "active": true, "agents": []string{"codebuddy"}, "control_mode": "plugin_pre_tool"})
	if err = os.WriteFile(connection, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Join(project, ".codebuddy"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err = MergeSettingsHooks("codebuddy", project, binary, connection, false); err != nil {
		t.Fatal(err)
	}
	defer MergeSettingsHooks("codebuddy", project, binary, connection, true)
	if err = os.WriteFile(filepath.Join(root, "ready.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	t.Log("CodeBuddy receiver ready")
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case err := <-done:
			t.Fatal("receiver ended", err)
		case <-ctx.Done():
			t.Fatal("real IDE test timed out")
		case <-ticker.C:
			if _, err := os.Stat(filepath.Join(root, "finish")); err == nil {
				batch, err := s.Prepare(ctx)
				if err != nil || batch == nil {
					t.Fatal("no real Hook records", err)
				}
				if err = os.WriteFile(filepath.Join(root, "hook-batch.json"), batch.Payload, 0600); err != nil {
					t.Fatal(err)
				}
				t.Logf("Captured %d Hook records", batch.Count)
				return
			}
		}
	}
}
