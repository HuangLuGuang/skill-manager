package managedclient

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"gopkg.in/yaml.v3"
)

type ModelConfigState struct {
	Supported  bool   `json:"supported"`
	Model      string `json:"model,omitempty"`
	GatewayURL string `json:"gateway_url,omitempty"`
	ConfigPath string `json:"config_path,omitempty"`
	Error      string `json:"error,omitempty"`
}

// InspectModelConfig reads the live Agent configuration without returning any
// credential value. The desktop uses this as the source of truth after a switch.
func InspectModelConfig(home, agentType string) ModelConfigState {
	state := ModelConfigState{Supported: true}
	var err error
	switch agentType {
	case "claude-code":
		state.ConfigPath = filepath.Join(home, ".claude", "settings.json")
		var body []byte
		body, err = os.ReadFile(state.ConfigPath)
		if errors.Is(err, os.ErrNotExist) {
			return state
		}
		if err == nil {
			settings := map[string]any{}
			err = json.Unmarshal(body, &settings)
			if env, ok := settings["env"].(map[string]any); ok {
				state.Model, _ = env["ANTHROPIC_MODEL"].(string)
				state.GatewayURL, _ = env["ANTHROPIC_BASE_URL"].(string)
			}
		}
	case "codex":
		state.ConfigPath = filepath.Join(home, ".codex", "config.toml")
		var parsed map[string]any
		if _, err = toml.DecodeFile(state.ConfigPath, &parsed); errors.Is(err, os.ErrNotExist) {
			return state
		}
		if err == nil {
			state.Model, _ = parsed["model"].(string)
			providerName, _ := parsed["model_provider"].(string)
			if providers, ok := parsed["model_providers"].(map[string]any); ok {
				if provider, ok := providers[providerName].(map[string]any); ok {
					state.GatewayURL, _ = provider["base_url"].(string)
				}
			}
		}
	case "hermes":
		state.ConfigPath = filepath.Join(home, ".hermes", "config.yaml")
		var body []byte
		body, err = os.ReadFile(state.ConfigPath)
		if errors.Is(err, os.ErrNotExist) {
			return state
		}
		if err == nil {
			parsed := map[string]any{}
			err = yaml.Unmarshal(body, &parsed)
			if model, ok := parsed["model"].(map[string]any); ok {
				state.Model, _ = model["default"].(string)
				state.GatewayURL, _ = model["base_url"].(string)
			}
		}
	default:
		return ModelConfigState{Supported: false}
	}
	if err != nil {
		state.Error = err.Error()
	}
	return state
}

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
	case "codex":
		return applyCodexModelConfig(home, server, localAgentID, model, credential)
	case "hermes":
		return applyHermesModelConfig(home, server, localAgentID, model, credential)
	default:
		return fmt.Errorf("automatic model configuration is not supported for %s", agentType)
	}
}

func modelGatewayV1(server string) string {
	server = strings.TrimRight(strings.TrimSpace(server), "/")
	if strings.HasSuffix(server, "/v1") {
		return server
	}
	return server + "/v1"
}

func applyCodexModelConfig(home, server, localAgentID, model, credential string) error {
	path := filepath.Join(home, ".codex", "config.toml")
	body, err := os.ReadFile(path)
	mode := os.FileMode(0o600)
	if err == nil {
		parsed := map[string]any{}
		if _, decodeErr := toml.Decode(string(body), &parsed); decodeErr != nil {
			return fmt.Errorf("Codex config.toml is invalid: %w", decodeErr)
		}
		if info, statErr := os.Stat(path); statErr == nil {
			mode = info.Mode().Perm()
		}
		if err := backupAgentConfig(home, localAgentID, "config.toml", body); err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	updated, err := mergeCodexModelConfig(body, modelGatewayV1(server), model, credential)
	if err != nil {
		return err
	}
	if strings.TrimSpace(credential) != "" {
		mode = 0o600
	}
	return atomicWriteFile(path, updated, mode)
}

func mergeCodexModelConfig(body []byte, server, model, credential string) ([]byte, error) {
	existingCredential := ""
	if len(bytes.TrimSpace(body)) > 0 {
		parsed := map[string]any{}
		if _, err := toml.Decode(string(body), &parsed); err != nil {
			return nil, err
		}
		if providers, ok := parsed["model_providers"].(map[string]any); ok {
			if provider, ok := providers["agent_manager"].(map[string]any); ok {
				existingCredential, _ = provider["experimental_bearer_token"].(string)
			}
		}
	}
	if strings.TrimSpace(credential) == "" {
		credential = existingCredential
	}
	kept := make([]string, 0)
	section := ""
	skipManagedSection := false
	scanner := bufio.NewScanner(bytes.NewReader(body))
	for scanner.Scan() {
		line := scanner.Text()
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "[") && strings.HasSuffix(trimmed, "]") {
			section = trimmed
			skipManagedSection = section == "[model_providers.agent_manager]"
			if skipManagedSection {
				continue
			}
		}
		if skipManagedSection {
			continue
		}
		if section == "" && (strings.HasPrefix(trimmed, "model =") || strings.HasPrefix(trimmed, "model_provider =")) {
			continue
		}
		kept = append(kept, line)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	for len(kept) > 0 && strings.TrimSpace(kept[len(kept)-1]) == "" {
		kept = kept[:len(kept)-1]
	}
	lines := []string{"model = " + strconv.Quote(model), "model_provider = \"agent_manager\"", ""}
	lines = append(lines, kept...)
	if len(kept) > 0 {
		lines = append(lines, "")
	}
	lines = append(lines, "[model_providers.agent_manager]", "name = \"Agent Manager\"", "base_url = "+strconv.Quote(server), "wire_api = \"responses\"")
	if strings.TrimSpace(credential) != "" {
		lines = append(lines, "experimental_bearer_token = "+strconv.Quote(strings.TrimSpace(credential)))
	}
	updated := []byte(strings.Join(lines, "\n") + "\n")
	parsed := map[string]any{}
	if _, err := toml.Decode(string(updated), &parsed); err != nil {
		return nil, fmt.Errorf("generated Codex config.toml is invalid: %w", err)
	}
	return updated, nil
}

func applyHermesModelConfig(home, server, localAgentID, model, credential string) error {
	configPath := filepath.Join(home, ".hermes", "config.yaml")
	configBody, err := os.ReadFile(configPath)
	configMode := os.FileMode(0o600)
	if err == nil {
		if info, statErr := os.Stat(configPath); statErr == nil {
			configMode = info.Mode().Perm()
		}
		if err := backupAgentConfig(home, localAgentID, "config.yaml", configBody); err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	root := &yaml.Node{Kind: yaml.MappingNode}
	if len(bytes.TrimSpace(configBody)) > 0 {
		var document yaml.Node
		if err := yaml.Unmarshal(configBody, &document); err != nil {
			return fmt.Errorf("Hermes config.yaml is invalid: %w", err)
		}
		if len(document.Content) > 0 {
			root = document.Content[0]
		}
		if root.Kind != yaml.MappingNode {
			return errors.New("Hermes config.yaml root must be a mapping")
		}
	}
	modelNode := yamlMappingValue(root, "model")
	if modelNode == nil || modelNode.Kind != yaml.MappingNode {
		modelNode = &yaml.Node{Kind: yaml.MappingNode}
		yamlSetMappingValue(root, "model", modelNode)
	}
	yamlSetScalar(modelNode, "default", model)
	yamlSetScalar(modelNode, "provider", "custom")
	yamlSetScalar(modelNode, "base_url", modelGatewayV1(server))
	yamlSetScalar(modelNode, "api_mode", "chat_completions")
	var output bytes.Buffer
	encoder := yaml.NewEncoder(&output)
	encoder.SetIndent(2)
	if err := encoder.Encode(root); err != nil {
		return err
	}
	_ = encoder.Close()
	if err := atomicWriteFile(configPath, output.Bytes(), configMode); err != nil {
		return err
	}
	if strings.TrimSpace(credential) == "" {
		return nil
	}
	envPath := filepath.Join(home, ".hermes", ".env")
	envBody, envErr := os.ReadFile(envPath)
	if envErr == nil {
		if err := backupAgentConfig(home, localAgentID, "hermes.env", envBody); err != nil {
			return err
		}
	} else if !errors.Is(envErr, os.ErrNotExist) {
		return envErr
	}
	return atomicWriteFile(envPath, updateEnvValue(envBody, "OPENAI_API_KEY", strings.TrimSpace(credential)), 0o600)
}

func yamlMappingValue(mapping *yaml.Node, key string) *yaml.Node {
	for index := 0; index+1 < len(mapping.Content); index += 2 {
		if mapping.Content[index].Value == key {
			return mapping.Content[index+1]
		}
	}
	return nil
}

func yamlSetMappingValue(mapping *yaml.Node, key string, value *yaml.Node) {
	for index := 0; index+1 < len(mapping.Content); index += 2 {
		if mapping.Content[index].Value == key {
			mapping.Content[index+1] = value
			return
		}
	}
	mapping.Content = append(mapping.Content, &yaml.Node{Kind: yaml.ScalarNode, Value: key}, value)
}

func yamlSetScalar(mapping *yaml.Node, key, value string) {
	yamlSetMappingValue(mapping, key, &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: value})
}

func updateEnvValue(body []byte, key, value string) []byte {
	lines := strings.Split(strings.ReplaceAll(string(body), "\r\n", "\n"), "\n")
	result := make([]string, 0, len(lines)+1)
	replaced := false
	for _, line := range lines {
		candidate := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(line), "export "))
		if strings.HasPrefix(candidate, key+"=") {
			if !replaced {
				result = append(result, key+"="+value)
				replaced = true
			}
			continue
		}
		if line != "" || len(result) > 0 {
			result = append(result, line)
		}
	}
	if !replaced {
		result = append(result, key+"="+value)
	}
	for len(result) > 0 && result[len(result)-1] == "" {
		result = result[:len(result)-1]
	}
	return []byte(strings.Join(result, "\n") + "\n")
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
