package managedclient

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ApplyModelConfig updates model routing fields and, when supplied through the
// task-bound issuance endpoint, stores the Agent-specific runtime credential.
// The credential is never carried inside the task payload.
func ApplyModelConfig(home, server, localAgentID, agentType, model, credential string) error {
	server = strings.TrimRight(strings.TrimSpace(server), "/")
	localAgentID = strings.TrimSpace(localAgentID)
	model = strings.TrimSpace(model)
	if server == "" || localAgentID == "" || model == "" {
		return errors.New("model configuration requires server, local Agent ID, and model")
	}
	if filepath.Base(localAgentID) != localAgentID || localAgentID == "." {
		return errors.New("invalid local Agent ID")
	}
	switch agentType {
	case "claude-code":
		return applyClaudeCodeModelConfig(home, server, localAgentID, model, credential)
	default:
		return fmt.Errorf("automatic model configuration is not supported for %s", agentType)
	}
}

func applyClaudeCodeModelConfig(home, server, localAgentID, model, credential string) error {
	path := filepath.Join(home, ".claude", "settings.json")
	settings := map[string]any{}
	mode := os.FileMode(0o600)
	body, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(body, &settings); err != nil {
			return fmt.Errorf("Claude Code settings.json is invalid: %w", err)
		}
		if info, statErr := os.Stat(path); statErr == nil {
			mode = info.Mode().Perm()
		}
		if err := backupAgentConfig(home, localAgentID, "settings.json", body); err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	env, ok := settings["env"].(map[string]any)
	if !ok {
		env = map[string]any{}
	}
	env["ANTHROPIC_BASE_URL"] = server
	env["ANTHROPIC_MODEL"] = model
	if strings.TrimSpace(credential) != "" {
		env["ANTHROPIC_AUTH_TOKEN"] = strings.TrimSpace(credential)
		// A task-issued credential turns this file into a secret-bearing config.
		// Do not preserve a pre-existing group/world-readable mode.
		mode = 0o600
	}
	settings["env"] = env
	encoded, err := json.MarshalIndent(settings, "", "  ")
	if err != nil {
		return err
	}
	encoded = append(encoded, '\n')
	return atomicWriteFile(path, encoded, mode)
}

func backupAgentConfig(home, localAgentID, name string, body []byte) error {
	stamp := time.Now().UTC().Format("20060102T150405.000000000Z")
	path := filepath.Join(home, ".agent-manager", "config-backups", stamp, localAgentID, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, body, 0o600)
}

func atomicWriteFile(path string, body []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".agent-manager-config-*")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(body); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpPath, path)
}
