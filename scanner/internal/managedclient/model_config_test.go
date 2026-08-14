package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestApplyClaudeCodeModelConfigPreservesSettingsAndDoesNotWriteCredential(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, ".claude", "settings.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	original := []byte(`{"permissions":{"allow":["Read"]},"env":{"ANTHROPIC_AUTH_TOKEN":"existing-secret"}}`)
	if err := os.WriteFile(path, original, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(home, "https://agent-manager.example.com/", "claude-default", "claude-code", "managed-model", ""); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var settings map[string]any
	if err := json.Unmarshal(body, &settings); err != nil {
		t.Fatal(err)
	}
	env := settings["env"].(map[string]any)
	if env["ANTHROPIC_BASE_URL"] != "https://agent-manager.example.com" || env["ANTHROPIC_MODEL"] != "managed-model" {
		t.Fatalf("unexpected model config: %#v", env)
	}
	if env["ANTHROPIC_AUTH_TOKEN"] != "existing-secret" {
		t.Fatalf("existing credential was changed: %#v", env)
	}
	if _, ok := settings["permissions"]; !ok {
		t.Fatalf("existing settings were lost: %#v", settings)
	}
	backups, err := filepath.Glob(filepath.Join(home, ".agent-manager", "config-backups", "*", "claude-default", "settings.json"))
	if err != nil || len(backups) != 1 {
		t.Fatalf("expected one backup, got %v (%v)", backups, err)
	}
}

func TestApplyModelConfigRejectsUnsupportedAgentWithoutWriting(t *testing.T) {
	home := t.TempDir()
	if err := ApplyModelConfig(home, "https://agent-manager.example.com", "codex-default", "codex", "model", ""); err == nil {
		t.Fatal("expected unsupported Agent error")
	}
	if _, err := os.Stat(filepath.Join(home, ".codex", "config.toml")); !os.IsNotExist(err) {
		t.Fatalf("unsupported config was written: %v", err)
	}
}

func TestApplyClaudeCodeModelConfigWritesTaskIssuedAgentCredential(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, ".claude", "settings.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"env":{"EXISTING":"value"}}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(
		home,
		"https://agent-manager.example.com",
		"claude-default",
		"claude-code",
		"managed-model",
		"amat_agent_runtime_secret",
	); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var settings map[string]any
	if err := json.Unmarshal(body, &settings); err != nil {
		t.Fatal(err)
	}
	env, _ := settings["env"].(map[string]any)
	if env["ANTHROPIC_AUTH_TOKEN"] != "amat_agent_runtime_secret" {
		t.Fatalf("issued credential was not stored: %#v", env)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := info.Mode().Perm(); got != 0o600 {
		t.Fatalf("secret-bearing settings mode = %o, want 600", got)
	}
}
