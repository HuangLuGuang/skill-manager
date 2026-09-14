package managedclient

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
)

// Version discovery never starts an interactive session or reads the user's
// native Agent home. Cache by executable modification time to keep scans fast.
func discoverModelVersion(home, kind, binary string) string {
	if binary == "" {
		return ""
	}
	info, err := os.Stat(binary)
	if err != nil {
		return ""
	}
	if kind == "claude-desktop" && runtime.GOOS == "darwin" && info.IsDir() {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		output, err := exec.CommandContext(ctx, "/usr/bin/plutil", "-extract", "CFBundleShortVersionString", "raw", "-o", "-", filepath.Join(binary, "Contents", "Info.plist")).Output()
		if err != nil {
			return ""
		}
		return strings.TrimSpace(string(output))
	}
	if info.IsDir() {
		return ""
	}
	if kind == "hermes" {
		return installedHermesVersion(binary)
	}
	cache := filepath.Join(home, ".agent-manager", "model-versions", kind+".json")
	var previous struct {
		Executable string
		Modified   int64
		Version    string
	}
	if body, err := os.ReadFile(cache); err == nil && json.Unmarshal(body, &previous) == nil && previous.Executable == binary && previous.Modified == info.ModTime().UnixNano() {
		return previous.Version
	}
	isolated, err := os.MkdirTemp("", "agent-manager-version-")
	if err != nil {
		return ""
	}
	defer os.RemoveAll(isolated)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, "--version")
	cmd.Dir = isolated
	cmd.Env = modelProbeEnvironment(isolated)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return ""
	}
	version := regexp.MustCompile(`\b[vV]?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.]+)?`).FindString(string(output))
	previous.Executable, previous.Modified, previous.Version = binary, info.ModTime().UnixNano(), version
	body, _ := json.Marshal(previous)
	_ = atomicWriteFile(cache, body, 0o600)
	return version
}

// Hermes --version synchronously checks for updates. Resolve its installed
// entry point and read package metadata without launching that network path.
func installedHermesVersion(binary string) string {
	resolved, err := filepath.EvalSymlinks(binary)
	if err != nil {
		return ""
	}
	environment := filepath.Dir(filepath.Dir(resolved))
	candidates := []string{filepath.Join(filepath.Dir(environment), "hermes_cli", "__init__.py")}
	installed, _ := filepath.Glob(filepath.Join(environment, "lib", "python*", "site-packages", "hermes_cli", "__init__.py"))
	candidates = append(candidates, installed...)
	candidates = append(candidates, filepath.Join(environment, "Lib", "site-packages", "hermes_cli", "__init__.py"))
	pattern := regexp.MustCompile(`(?m)^__version__\s*=\s*["']([^"']+)["']`)
	version := ""
	for _, path := range candidates {
		info, err := os.Stat(path)
		if err != nil || !info.Mode().IsRegular() || info.Size() > 128*1024 {
			continue
		}
		body, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		match := pattern.FindStringSubmatch(string(body))
		if len(match) == 2 {
			if version != "" && version != match[1] {
				return ""
			}
			version = match[1]
		}
	}
	return version
}
