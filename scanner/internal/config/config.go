package config

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Config struct {
	Root            string
	Server          string
	Token           string
	Output          string
	HostID          string
	Upload          bool
	UseBehavioral   bool
	UseSkillspector bool
	UseSandbox      bool
	UseLLM          bool
	NoCache         bool
	JudgementMode   string
	Timeout         time.Duration
	MaxFileBytes    int64
	MaxTotalBytes   int64
	MaxFiles        int
	IgnoreDirs      map[string]bool
}

func Parse(args []string) (Config, error) {
	var cfg Config
	if len(args) == 0 {
		return cfg, fmt.Errorf("missing command")
	}
	if args[0] != "scan" {
		return cfg, fmt.Errorf("unknown command %q", args[0])
	}

	fs := flag.NewFlagSet("scan", flag.ContinueOnError)
	fs.StringVar(&cfg.Server, "server", getenvAny("SKILL_SCANNER_SERVER", "SKILL_MANAGER_SERVER"), "Skill Manager server URL")
	fs.StringVar(&cfg.Token, "token", getenvAny("SKILL_SCANNER_TOKEN", "SKILL_MANAGER_TOKEN"), "Bearer token for Skill Manager")
	fs.StringVar(&cfg.Output, "output", "skill-scan-report.json", "JSON report output path")
	fs.StringVar(&cfg.HostID, "host-id", getenv("SKILL_SCANNER_HOST_ID", ""), "host identifier sent to Skill Manager")
	fs.BoolVar(&cfg.Upload, "upload", false, "upload discovered skills to Skill Manager")
	fs.BoolVar(&cfg.UseBehavioral, "behavioral", false, "request rule-based analysis")
	fs.BoolVar(&cfg.UseSkillspector, "deep-scan", false, "request deep scan analysis")
	fs.BoolVar(&cfg.UseSandbox, "sandbox", false, "request sandbox analysis")
	fs.BoolVar(&cfg.UseLLM, "llm", false, "request LLM analysis")
	fs.BoolVar(&cfg.NoCache, "no-cache", false, "force server-side rescan without cache")
	fs.StringVar(&cfg.JudgementMode, "judgement-mode", getenv("SKILL_SCANNER_JUDGEMENT_MODE", ""), "judgement mode: strict, balanced, or permissive")
	timeout := fs.Duration("timeout", 120*time.Second, "HTTP timeout")
	maxFileMB := fs.Int64("max-file-mb", 20, "maximum single file size included in package")
	maxTotalMB := fs.Int64("max-total-mb", 50, "maximum total skill package size")
	fs.IntVar(&cfg.MaxFiles, "max-files", 2000, "maximum file count included in package")
	ignore := fs.String("ignore", DefaultIgnoreList(), "comma-separated ignored directory names")

	flagArgs, rootArg, err := splitScanArgs(args[1:])
	if err != nil {
		return cfg, err
	}
	if err := fs.Parse(flagArgs); err != nil {
		return cfg, err
	}
	if rootArg == "" {
		return cfg, fmt.Errorf("usage: skill-scanner scan <path> [--server URL] [--token TOKEN] [--upload]")
	}

	root, err := filepath.Abs(rootArg)
	if err != nil {
		return cfg, err
	}
	cfg.Root = root
	cfg.Timeout = *timeout
	cfg.MaxFileBytes = *maxFileMB * 1024 * 1024
	cfg.MaxTotalBytes = *maxTotalMB * 1024 * 1024
	cfg.IgnoreDirs = ParseIgnoreDirs(*ignore)
	if cfg.Server != "" {
		cfg.Upload = true
	}
	if cfg.Upload && cfg.Server == "" {
		return cfg, fmt.Errorf("--upload requires --server or SKILL_SCANNER_SERVER")
	}
	return cfg, nil
}

func splitScanArgs(args []string) ([]string, string, error) {
	valueFlags := map[string]bool{
		"server":         true,
		"token":          true,
		"output":         true,
		"host-id":        true,
		"timeout":        true,
		"max-file-mb":    true,
		"max-total-mb":   true,
		"max-files":      true,
		"ignore":         true,
		"judgement-mode": true,
	}
	var flagArgs []string
	var root string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if strings.HasPrefix(arg, "-") {
			flagArgs = append(flagArgs, arg)
			name := strings.TrimLeft(arg, "-")
			if idx := strings.Index(arg, "="); idx >= 0 {
				name = strings.TrimLeft(arg[:idx], "-")
			}
			if valueFlags[name] && !strings.Contains(arg, "=") {
				if i+1 >= len(args) {
					return nil, "", fmt.Errorf("missing value for %s", arg)
				}
				i++
				flagArgs = append(flagArgs, args[i])
			}
			continue
		}
		if root != "" {
			return nil, "", fmt.Errorf("only one scan path is supported: %s", arg)
		}
		root = arg
	}
	return flagArgs, root, nil
}

func Usage() string {
	return strings.TrimSpace(`
Usage:
  skill-scanner scan <path> [options]

Options:
  --server URL        Skill Manager server URL. If set, upload is enabled.
  --token TOKEN       Bearer token. Can also use SKILL_SCANNER_TOKEN.
  --output PATH       JSON report output path. Default: skill-scan-report.json.
  --host-id ID        Host identifier. Can also use SKILL_SCANNER_HOST_ID.
  --upload            Upload discovered skills to Skill Manager.
  --behavioral        Request rule-based analysis.
  --deep-scan         Request deep scan analysis.
  --sandbox           Request sandbox analysis.
  --llm               Request LLM analysis.
  --no-cache          Force server-side rescan without cache.
  --judgement-mode M  Judgement mode: strict, balanced, or permissive. Can also use SKILL_SCANNER_JUDGEMENT_MODE.
  --max-file-mb N     Maximum single file size. Default: 20.
  --max-total-mb N    Maximum total skill size. Default: 50.
  --max-files N       Maximum file count. Default: 2000.
  --ignore LIST       Comma-separated ignored directory names.
`)
}

func getenv(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func getenvAny(keys ...string) string {
	for _, key := range keys {
		value := strings.TrimSpace(os.Getenv(key))
		if value != "" {
			return value
		}
	}
	return ""
}

func DefaultIgnoreList() string {
	return ".git,.venv,node_modules,__pycache__,dist,build"
}

func ParseIgnoreDirs(raw string) map[string]bool {
	result := map[string]bool{}
	for _, item := range strings.Split(raw, ",") {
		name := strings.TrimSpace(item)
		if name != "" {
			result[name] = true
		}
	}
	return result
}
