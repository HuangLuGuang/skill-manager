package config

import "testing"

func TestParseUsesScannerSpecificEnv(t *testing.T) {
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

func TestParseIgnoresLegacyScannerEnv(t *testing.T) {
	t.Setenv("SKILL_MANAGER_SERVER", "http://legacy.example")
	t.Setenv("SKILL_MANAGER_TOKEN", "legacy-token")

	cfg, err := Parse([]string{"scan", "/tmp/skills"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Server != "" {
		t.Fatalf("server = %q", cfg.Server)
	}
	if cfg.Token != "" {
		t.Fatalf("token = %q", cfg.Token)
	}
}

// 页面上传示例按配置项选择来源；显式空地址保证本地示例不受环境影响。
func TestParseDocumentedUploadSources(t *testing.T) {
	t.Setenv("SKILL_SCANNER_SERVER", "https://env.example")
	t.Setenv("SKILL_SCANNER_TOKEN", "env-token")
	cases := []struct {
		name   string
		args   []string
		server string
		token  string
		upload bool
	}{
		{"environment", nil, "https://env.example", "env-token", true},
		{"cli", []string{"--server", "https://cli.example", "--token", "cli-token"}, "https://cli.example", "cli-token", true},
		{"cli server", []string{"--server", "https://cli.example"}, "https://cli.example", "env-token", true},
		{"cli token", []string{"--token", "cli-token"}, "https://env.example", "cli-token", true},
		{"local override", []string{"--server="}, "", "env-token", false},
		{"address enables upload", []string{"--upload=false"}, "https://env.example", "env-token", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg, err := Parse(append([]string{"scan", "/tmp/skills"}, tc.args...))
			if err != nil {
				t.Fatal(err)
			}
			if cfg.Server != tc.server || cfg.Token != tc.token || cfg.Upload != tc.upload {
				t.Fatal("unexpected configuration source or upload mode")
			}
		})
	}
}

func TestParseDocumentedDefaults(t *testing.T) {
	for _, key := range []string{"SKILL_SCANNER_SERVER", "SKILL_SCANNER_TOKEN", "SKILL_SCANNER_HOST_ID", "SKILL_SCANNER_JUDGEMENT_MODE"} {
		t.Setenv(key, "")
	}
	cfg, err := Parse([]string{"scan", "/tmp/skills"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Upload || cfg.UseBehavioral || cfg.UseSkillspector || cfg.UseSandbox || cfg.UseLLM {
		t.Fatal("upload and analysis switches should default to off")
	}
	if cfg.Output != "skill-scan-report.json" || cfg.Timeout.Seconds() != 120 || cfg.HostID != "" || cfg.JudgementMode != "" {
		t.Fatal("unexpected report, timeout or optional metadata defaults")
	}
	if cfg.MaxFileBytes != 20*1024*1024 || cfg.MaxTotalBytes != 50*1024*1024 || cfg.MaxFiles != 2000 {
		t.Fatal("unexpected documented packaging limits")
	}
	for _, name := range []string{".git", ".venv", "node_modules", "__pycache__", "dist", "build"} {
		if !cfg.IgnoreDirs[name] {
			t.Fatalf("missing default ignore name: %s", name)
		}
	}
}

func TestParseDocumentedOptionalOverrides(t *testing.T) {
	t.Setenv("SKILL_SCANNER_SERVER", "")
	t.Setenv("SKILL_SCANNER_HOST_ID", "env-host")
	t.Setenv("SKILL_SCANNER_JUDGEMENT_MODE", "strict")
	cfg, err := Parse([]string{"scan", "/tmp/skills", "--host-id", "cli-host", "--judgement-mode", "balanced", "--timeout", "2m", "--ignore", "custom", "--behavioral", "--deep-scan", "--sandbox", "--llm"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.HostID != "cli-host" || cfg.JudgementMode != "balanced" || cfg.Timeout.Seconds() != 120 {
		t.Fatal("CLI metadata and duration overrides should apply")
	}
	if !cfg.IgnoreDirs["custom"] || cfg.IgnoreDirs[".git"] || len(cfg.IgnoreDirs) != 1 {
		t.Fatal("custom ignore list should replace defaults")
	}
	if !cfg.UseBehavioral || !cfg.UseSkillspector || !cfg.UseSandbox || !cfg.UseLLM || cfg.Upload {
		t.Fatal("analysis switches combine independently without enabling upload")
	}
}
