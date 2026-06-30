package config

import "testing"

func TestParsePrefersScannerSpecificEnv(t *testing.T) {
	t.Setenv("SKILL_SCANNER_SERVER", "http://scanner.example")
	t.Setenv("SKILL_MANAGER_SERVER", "http://legacy.example")
	t.Setenv("SKILL_SCANNER_TOKEN", "scanner-token")
	t.Setenv("SKILL_MANAGER_TOKEN", "legacy-token")

	cfg, err := Parse([]string{"scan", "/tmp/skills"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Server != "http://scanner.example" {
		t.Fatalf("server = %q", cfg.Server)
	}
	if cfg.Token != "scanner-token" {
		t.Fatalf("token = %q", cfg.Token)
	}
}
