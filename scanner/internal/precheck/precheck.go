package precheck

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"skill-manager/scanner/internal/manifest"
)

type Finding struct {
	Severity string `json:"severity"`
	Rule     string `json:"rule"`
	File     string `json:"file"`
	Message  string `json:"message"`
}

type patternRule struct {
	severity string
	rule     string
	re       *regexp.Regexp
	message  string
}

var rules = []patternRule{
	{"HIGH", "dynamic_code_execution", regexp.MustCompile(`\b(eval|exec)\s*\(`), "发现动态代码执行函数"},
	{"HIGH", "process_execution", regexp.MustCompile(`\b(subprocess|os\.system|popen)\b`), "发现进程或命令执行调用"},
	{"MEDIUM", "network_post", regexp.MustCompile(`\b(requests|httpx|urllib|fetch)\b|\.post\s*\(`), "发现网络请求相关代码"},
	{"MEDIUM", "environment_secret_access", regexp.MustCompile(`\b(os\.getenv|process\.env|API_KEY|SECRET|TOKEN|PASSWORD)\b`), "发现环境变量或敏感名称访问"},
	{"MEDIUM", "sensitive_file_access", regexp.MustCompile(`(/etc/passwd|\.ssh|id_rsa|credentials|keychain)`), "发现敏感文件路径特征"},
}

var suspiciousExtensions = map[string]bool{
	".sh":    true,
	".bash":  true,
	".zsh":   true,
	".ps1":   true,
	".exe":   true,
	".dll":   true,
	".dylib": true,
	".so":    true,
}

func Run(root string, m manifest.Manifest) []Finding {
	var findings []Finding
	for _, file := range m.Files {
		ext := strings.ToLower(filepath.Ext(file.Path))
		if suspiciousExtensions[ext] {
			findings = append(findings, Finding{
				Severity: "MEDIUM",
				Rule:     "suspicious_file_type",
				File:     file.Path,
				Message:  "发现需要重点审查的文件类型",
			})
		}
		if !isTextCandidate(ext, file.Path) || file.Size > 1024*1024 {
			continue
		}
		content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(file.Path)))
		if err != nil || bytes.IndexByte(content, 0) >= 0 {
			continue
		}
		text := string(content)
		for _, rule := range rules {
			if rule.re.MatchString(text) {
				findings = append(findings, Finding{
					Severity: rule.severity,
					Rule:     rule.rule,
					File:     file.Path,
					Message:  rule.message,
				})
			}
		}
	}
	return findings
}

func isTextCandidate(ext string, path string) bool {
	if path == "SKILL.md" {
		return true
	}
	switch ext {
	case ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".sh", ".bash", ".zsh":
		return true
	default:
		return false
	}
}
