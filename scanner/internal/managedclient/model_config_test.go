package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
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
	if err := ApplyModelConfig(home, "https://agent-manager.example.com", "gemini-default", "gemini", "model", ""); err == nil {
		t.Fatal("expected unsupported Agent error")
	}
	if _, err := os.Stat(filepath.Join(home, ".gemini", "settings.json")); !os.IsNotExist(err) {
		t.Fatalf("unsupported config was written: %v", err)
	}
}

func TestApplyCodexModelConfigPreservesUnrelatedSettings(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, ".codex", "config.toml")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	original := []byte("# keep this comment\nmodel = \"old\"\napproval_policy = \"on-request\"\n\n[model_providers.other]\nname = \"Other\"\nbase_url = \"https://other.example/v1\"\n")
	if err := os.WriteFile(path, original, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(home, "https://agent-manager.example.com", "codex", "codex", "gpt-managed", "amat_agent_secret"); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	text := string(body)
	for _, expected := range []string{
		`model = "gpt-managed"`,
		`model_provider = "agent_manager"`,
		`approval_policy = "on-request"`,
		`[model_providers.other]`,
		`base_url = "https://agent-manager.example.com/v1"`,
		`wire_api = "responses"`,
		`experimental_bearer_token = "amat_agent_secret"`,
	} {
		if !strings.Contains(text, expected) {
			t.Fatalf("generated config is missing %q:\n%s", expected, text)
		}
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("secret-bearing Codex config mode = %v, err=%v", info.Mode().Perm(), err)
	}
	state := InspectModelConfig(home, "codex")
	if state.Model != "gpt-managed" || state.GatewayURL != "https://agent-manager.example.com/v1" {
		t.Fatalf("unexpected live Codex state: %#v", state)
	}
}

func TestApplyHermesModelConfigPreservesYamlAndWritesSecretEnv(t *testing.T) {
	home := t.TempDir()
	configPath := filepath.Join(home, ".hermes", "config.yaml")
	if err := os.MkdirAll(filepath.Dir(configPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, []byte("theme: dark\nmodel:\n  temperature: 0.2\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(home, "https://agent-manager.example.com/", "hermes", "hermes", "hermes-managed", "amat_agent_secret"); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatal(err)
	}
	text := string(body)
	for _, expected := range []string{"theme: dark", "temperature: 0.2", "default: hermes-managed", "provider: custom", "base_url: https://agent-manager.example.com/v1"} {
		if !strings.Contains(text, expected) {
			t.Fatalf("generated Hermes config is missing %q:\n%s", expected, text)
		}
	}
	envBody, err := os.ReadFile(filepath.Join(home, ".hermes", ".env"))
	if err != nil || string(envBody) != "OPENAI_API_KEY=amat_agent_secret\n" {
		t.Fatalf("unexpected Hermes env: %q %v", envBody, err)
	}
	state := InspectModelConfig(home, "hermes")
	if state.Model != "hermes-managed" || state.GatewayURL != "https://agent-manager.example.com/v1" {
		t.Fatalf("unexpected live Hermes state: %#v", state)
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
