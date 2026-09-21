package managedclient

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func installFakeClaude(t *testing.T, valid bool) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("fake native Agent fixture uses a POSIX shell")
	}
	bin := filepath.Join(t.TempDir(), "bin")
	if err := os.MkdirAll(bin, 0o700); err != nil {
		t.Fatal(err)
	}
	result := `$marker`
	if !valid {
		result = "WRONG_MARKER"
	}
	script := "#!/bin/sh\n" +
		"marker=$(printf '%s\\n' \"$@\" | grep -Eo 'AM_VERIFY_[0-9a-f-]+' | head -n 1)\n" +
		"printf '{\"type\":\"result\",\"result\":\"%s\",\"is_error\":false}\\n' \"" + result + "\"\n"
	if err := os.WriteFile(filepath.Join(bin, "claude"), []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
}

func applyExternalClaudeConfig(t *testing.T, home string) ModelChange {
	t.Helper()
	change, err := ApplyModelConfigRevision(
		home,
		"https://external.example.test:8080",
		"claude-code",
		"claude-code",
		"external-model",
		"external-secret",
		"",
		map[string]any{},
		map[string]any{
			"gateway_source":    "external",
			"credential_source": "external_gateway",
			"verification_mode": "client_call",
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	return change
}

func TestExternalClientCallVerificationDoesNotRequirePlatformGatewayEvidence(t *testing.T) {
	home := t.TempDir()
	installFakeClaude(t, true)
	applyExternalClaudeConfig(t, home)
	evidenceRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		evidenceRequests++
		http.Error(w, "internal gateway evidence must not be queried", http.StatusBadRequest)
	}))
	defer server.Close()
	evidence, err := VerifyModelConfig(context.Background(), home, "claude-code", "claude-code", NewAPI(server.URL, "client-token", time.Second), Inventory{ClientID: "host-1"})
	if err != nil {
		t.Fatal(err)
	}
	if evidenceRequests != 0 {
		t.Fatalf("external verification queried internal gateway evidence %d times", evidenceRequests)
	}
	if len(evidence) != 1 || evidence[0].Status != "success" || evidence[0].VerificationMode != "client_call" {
		t.Fatalf("unexpected client-call evidence: %#v", evidence)
	}
	state := InspectModelConfig(home, "claude-code")
	if state.Status != "verified" || state.VerificationMode != "client_call" {
		t.Fatalf("external model was not marked client-call verified: %#v", state)
	}
}

func TestExternalClientCallFailureRestoresOriginalConfiguration(t *testing.T) {
	home := t.TempDir()
	settingsPath := filepath.Join(home, ".claude", "settings.json")
	if err := os.MkdirAll(filepath.Dir(settingsPath), 0o700); err != nil {
		t.Fatal(err)
	}
	original := []byte(`{"env":{"ANTHROPIC_MODEL":"original"},"keep":true}`)
	if err := os.WriteFile(settingsPath, original, 0o600); err != nil {
		t.Fatal(err)
	}
	installFakeClaude(t, false)
	change := applyExternalClaudeConfig(t, home)
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		http.Error(w, "unexpected platform request", http.StatusBadRequest)
	}))
	defer server.Close()
	task := Task{ID: 9, TaskType: "verify_model_config", Payload: map[string]any{
		"agent_type": "claude-code", "local_agent_id": "claude-code",
		"change_id": change.ID, "expected_revision": change.AppliedRevision,
	}}
	err = executeTask(context.Background(), home, Inventory{ClientID: "host-1"}, Policy{}, NewAPI(server.URL, "client-token", time.Second), store, task)
	if err == nil || !strings.Contains(err.Error(), "model_config.agent_response_missing") {
		t.Fatalf("invalid client response unexpectedly verified: %v", err)
	}
	restored, readErr := os.ReadFile(settingsPath)
	if readErr != nil || string(restored) != string(original) {
		t.Fatalf("failed external verification did not restore exact original config: %q, %v", restored, readErr)
	}
	if task.Payload["restored_after_failure"] != true {
		t.Fatalf("automatic restoration was not reported: %#v", task.Payload)
	}
	state := InspectModelConfig(home, "claude-code")
	if state.Status != "restored" {
		t.Fatalf("restored model state not visible: %#v", state)
	}
}
