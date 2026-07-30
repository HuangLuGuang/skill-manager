package runner

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/client"
	"skill-manager/scanner/internal/config"
	"skill-manager/scanner/internal/discovery"
	"skill-manager/scanner/internal/manifest"
	"skill-manager/scanner/internal/packager"
	"skill-manager/scanner/internal/precheck"
	"skill-manager/scanner/internal/report"
)

const Version = "0.1.0"

type Options struct {
	SelectedPaths map[string]bool
	OnProgress    func(report.Report, report.SkillResult)
}

func ensureDir(path string) error {
	return os.MkdirAll(path, 0o755)
}

func Scan(cfg config.Config, opts Options) (report.Report, string, error) {
	skills, err := discovery.Find(cfg.Root, cfg.IgnoreDirs)
	if err != nil {
		return report.Report{}, "", err
	}
	if len(opts.SelectedPaths) > 0 {
		filtered := skills[:0]
		for _, skill := range skills {
			if opts.SelectedPaths[skill.Path] {
				filtered = append(filtered, skill)
			}
		}
		skills = filtered
	}

	outputAbs, err := filepath.Abs(cfg.Output)
	if err != nil {
		return report.Report{}, "", err
	}
	workDir := strings.TrimSuffix(outputAbs, filepath.Ext(outputAbs)) + "-packages"
	if err := ensureDir(workDir); err != nil {
		return report.Report{}, "", err
	}

	apiClient := client.New(cfg.Server, cfg.Token, cfg.Timeout)
	result := report.Report{
		GeneratedAt: time.Now().UTC(),
		Root:        cfg.Root,
		Found:       len(skills),
		Skills:      []report.SkillResult{},
	}

	for _, skill := range skills {
		item, err := ScanOne(cfg, apiClient, skill.Path, workDir)
		if err != nil {
			item = report.SkillResult{
				Path:        skill.Path,
				SubmitError: err.Error(),
			}
		}
		if item.Submitted {
			result.Submitted++
		}
		if item.SubmitError != "" {
			result.Failed++
		}
		result.Skills = append(result.Skills, item)
		if opts.OnProgress != nil {
			opts.OnProgress(result, item)
		}
	}

	if err := report.Write(outputAbs, result); err != nil {
		return result, outputAbs, err
	}
	return result, outputAbs, nil
}

func ScanOne(cfg config.Config, apiClient client.Client, skillPath string, workDir string) (report.SkillResult, error) {
	m, err := manifest.Build(skillPath, manifest.Options{
		IgnoreDirs:    cfg.IgnoreDirs,
		MaxFileBytes:  cfg.MaxFileBytes,
		MaxTotalBytes: cfg.MaxTotalBytes,
		MaxFiles:      cfg.MaxFiles,
	})
	if err != nil {
		return report.SkillResult{Path: skillPath}, err
	}
	findings := precheck.Run(skillPath, m)
	packageName := SafePackageName(m.Name)
	if packageName == "" {
		packageName = SafePackageName(filepath.Base(skillPath))
	}
	zipPath := filepath.Join(workDir, packageName+"-"+strings.TrimPrefix(m.Fingerprint, "sha256:")[:12]+".zip")
	if err := packager.CreateZip(skillPath, m, zipPath); err != nil {
		return report.SkillResult{Path: skillPath, Manifest: m}, err
	}

	item := report.SkillResult{
		Path:          skillPath,
		Name:          m.Name,
		Description:   m.Description,
		Fingerprint:   m.Fingerprint,
		FileCount:     len(m.Files),
		TotalBytes:    m.TotalBytes,
		LocalFindings: findings,
		PackagePath:   zipPath,
		Manifest:      m,
	}
	if cfg.Upload {
		manifestPayload, err := json.Marshal(m)
		if err != nil {
			item.SubmitError = err.Error()
			return item, nil
		}
		ctx, cancel := context.WithTimeout(context.Background(), cfg.Timeout)
		defer cancel()
		submission, err := apiClient.SubmitZip(ctx, zipPath, client.SubmitOptions{
			UseBehavioral:   cfg.UseBehavioral,
			UseSkillspector: cfg.UseSkillspector,
			UseSandbox:      cfg.UseSandbox,
			UseLLM:          cfg.UseLLM,
			JudgementMode:   cfg.JudgementMode,
			ManifestJSON:    string(manifestPayload),
			ScannerVersion:  Version,
			HostID:          cfg.HostID,
		})
		if err != nil {
			item.SubmitError = err.Error()
			return item, nil
		}
		item.Submitted = true
		item.Submission = submission
	}
	return item, nil
}

func SafePackageName(value string) string {
	value = strings.TrimSpace(strings.ToLower(value))
	var b strings.Builder
	for _, r := range value {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-' || r == '_' {
			b.WriteRune(r)
			continue
		}
		if r == ' ' || r == '.' || r == '/' || r == '\\' {
			b.WriteByte('-')
		}
	}
	result := strings.Trim(b.String(), "-_")
	if result == "" {
		return "skill"
	}
	return result
}
