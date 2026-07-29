package config

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/localize"
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
		return cfg, fmt.Errorf("%s", localize.Text("缺少命令", "missing command"))
	}
	if args[0] != "scan" {
		return cfg, fmt.Errorf(localize.Text("未知命令 %q", "unknown command %q"), args[0])
	}

	fs := flag.NewFlagSet("scan", flag.ContinueOnError)
	fs.StringVar(&cfg.Server, "server", getenv("SKILL_SCANNER_SERVER", ""), "Skill Manager server URL")
	fs.StringVar(&cfg.Token, "token", getenv("SKILL_SCANNER_TOKEN", ""), "Bearer token for Skill Manager")
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
		return cfg, fmt.Errorf(
			"%s",
			localize.Text(
				"用法：skill-scanner scan <path> [--server URL] [--token TOKEN] [--upload]",
				"usage: skill-scanner scan <path> [--server URL] [--token TOKEN] [--upload]",
			),
		)
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
		return cfg, fmt.Errorf(
			"%s",
			localize.Text(
				"--upload 需要 --server 或 SKILL_SCANNER_SERVER",
				"--upload requires --server or SKILL_SCANNER_SERVER",
			),
		)
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
					return nil, "", fmt.Errorf(
						localize.Text("%s 缺少参数值", "missing value for %s"),
						arg,
					)
				}
				i++
				flagArgs = append(flagArgs, args[i])
			}
			continue
		}
		if root != "" {
			return nil, "", fmt.Errorf(
				localize.Text("只支持一个扫描路径：%s", "only one scan path is supported: %s"),
				arg,
			)
		}
		root = arg
	}
	return flagArgs, root, nil
}

func Usage() string {
	if localize.Locale() == "zh-CN" {
		return strings.TrimSpace(`
用法：
  skill-scanner scan <path> [选项]

选项：
  --server URL        Agent Manager 地址；设置后自动上传。
  --token TOKEN       接入凭证，也可使用 SKILL_SCANNER_TOKEN。
  --output PATH       JSON 报告路径，默认 skill-scan-report.json。
  --host-id ID        主机标识，也可使用 SKILL_SCANNER_HOST_ID。
  --upload            上传发现的 Skill。
  --behavioral        启用规则分析。
  --deep-scan         启用深度扫描。
  --sandbox           启用 Sandbox 分析。
  --llm               启用 LLM 分析。
  --no-cache          禁用服务端缓存并重新扫描。
  --judgement-mode M  判定模式：strict、balanced 或 permissive。
  --max-file-mb N     单文件大小上限，默认 20。
  --max-total-mb N    Skill 总大小上限，默认 50。
  --max-files N       文件数量上限，默认 2000。
  --ignore LIST       逗号分隔的忽略目录。
`)
	}
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
