package managedclient

import (
	"context"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// OpenCode 1.1.51 installs its plugin package when the config directory has no
// matching dependency metadata. Copy installed packages into the probe home;
// never launch that installation path on behalf of a connection check.
func prepareOpenCodeProbe(ctx context.Context, home, binary string) error {
	versionCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	command := configureWindowsCommand(exec.CommandContext(versionCtx, binary, "--version"))
	command.Env = modelProbeEnvironment(home)
	output, err := command.Output()
	if err != nil || strings.TrimSpace(string(output)) != "1.1.51" {
		return errors.New("model_config.verification_version_unsupported")
	}
	current, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	source := filepath.Join(filepath.Dir(resolvedModelPath(current, "opencode", ".config/opencode/opencode.json")), "node_modules")
	destination := filepath.Join(home, ".config", "opencode")
	for name, version := range map[string]string{"@opencode-ai/plugin": "1.1.51", "@opencode-ai/sdk": "1.1.51", "zod": "4.1.8"} {
		root := filepath.Join(source, filepath.FromSlash(name))
		body, err := os.ReadFile(filepath.Join(root, "package.json"))
		var pkg struct {
			Name    string `json:"name"`
			Version string `json:"version"`
		}
		if err != nil || json.Unmarshal(body, &pkg) != nil || pkg.Name != name || pkg.Version != version {
			return errors.New("model_config.verification_dependencies_missing")
		}
		if err := copyProbePackage(root, filepath.Join(destination, "node_modules", filepath.FromSlash(name))); err != nil {
			return err
		}
	}
	if err := atomicWriteFile(filepath.Join(destination, "package.json"), []byte(`{"dependencies":{"@opencode-ai/plugin":"1.1.51"}}`), 0o600); err != nil {
		return err
	}
	path := filepath.Join(destination, "opencode.json")
	config, err := readJSONConfig(path)
	if err != nil {
		return err
	}
	objectConfig(config, "agent")["agent_manager_probe"] = map[string]any{"mode": "primary", "prompt": modelProbeInstructions, "steps": 1, "permission": map[string]any{"*": "deny"}}
	return writeNativeJSON(path, config)
}

func copyProbePackage(source, destination string) error {
	var total int64
	return filepath.WalkDir(source, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return errors.New("model_config.verification_dependencies_missing")
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return errors.New("model_config.verification_dependencies_missing")
		}
		relative, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		target := filepath.Join(destination, relative)
		if entry.IsDir() {
			return os.MkdirAll(target, 0o700)
		}
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			return errors.New("model_config.verification_dependencies_missing")
		}
		total += info.Size()
		if total > 32*1024*1024 {
			return errors.New("model_config.verification_dependencies_missing")
		}
		body, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(target, body, 0o600)
	})
}
