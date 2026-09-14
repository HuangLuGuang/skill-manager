package managedclient

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"gopkg.in/yaml.v3"
)

type ModelConfigState struct {
	AppliedRevision string                 `json:"applied_revision,omitempty"`
	Verification    []ModelRequestEvidence `json:"verification,omitempty"`
	Supported       bool                   `json:"supported"`
	Model           string                 `json:"model,omitempty"`
	GatewayURL      string                 `json:"gateway_url,omitempty"`
	ConfigPath      string                 `json:"config_path,omitempty"`
	Error           string                 `json:"error,omitempty"`
	Revision        string                 `json:"revision,omitempty"`
	Parameters      map[string]any         `json:"parameters,omitempty"`
	ChangeID        string                 `json:"change_id,omitempty"`
	Status          string                 `json:"status,omitempty"`
	CanRestore      bool                   `json:"can_restore"`
}

// InspectModelConfig reads the live Agent configuration without returning any
// credential value. The desktop uses this as the source of truth after a switch.
func InspectModelConfig(home, agentType string) (state ModelConfigState) {
	state = ModelConfigState{Supported: true}
	defer func() {
		if !state.Supported {
			return
		}
		var readErr error
		state.Revision, readErr = ModelConfigRevision(home, agentType)
		if readErr == nil {
			state.Parameters, readErr = readModelParameters(home, agentType)
		}
		if readErr != nil {
			state.Error = readErr.Error()
		}
		attachModelChangeState(home, agentType, &state)
	}()
	var err error
	switch agentType {
	case "claude-desktop":
		return inspectClaudeDesktopConfig(home)
	case "opencode", "openclaw", "pi", "grokbuild", "gemini":
		return inspectNativeModelConfig(home, agentType)
	case "claude-code":
		state.ConfigPath = resolvedModelPath(home, "claude-code", ".claude/settings.json")
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
		state.ConfigPath = resolvedModelPath(home, "codex", ".codex/config.toml")
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
		state.ConfigPath = resolvedModelPath(home, "hermes", ".hermes/config.yaml")
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
func renderModelConfig(home, server, localAgentID, agentType, model, credential string) error {
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
	case "claude-desktop":
		return applyClaudeDesktopConfig(home, server, model, credential)
	case "opencode", "openclaw", "pi", "grokbuild", "gemini":
		return applyNativeModelConfig(home, server, agentType, model, credential)
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
	path := resolvedModelPath(home, "codex", ".codex/config.toml")
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
	parsed := map[string]any{}
	if _, err := toml.Decode(string(body), &parsed); err != nil {
		return nil, errors.New("model_config.invalid_toml")
	}
	parsed["model"] = model
	parsed["model_provider"] = "agent_manager"
	// The gateway handles client tools, but does not execute OpenAI-hosted tools.
	parsed["web_search"] = "disabled"
	features := objectConfig(parsed, "features")
	features["image_generation"] = false
	providers := objectConfig(parsed, "model_providers")
	provider := objectConfig(providers, "agent_manager")
	provider["name"], provider["base_url"], provider["wire_api"] = "Agent Manager", server, "responses"
	if strings.TrimSpace(credential) != "" {
		provider["experimental_bearer_token"] = strings.TrimSpace(credential)
	}
	var output bytes.Buffer
	if err := toml.NewEncoder(&output).Encode(parsed); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func objectConfig(root map[string]any, key string) map[string]any {
	value, ok := root[key].(map[string]any)
	if !ok {
		value = map[string]any{}
		root[key] = value
	}
	return value
}

func applyHermesModelConfig(home, server, localAgentID, model, credential string) error {
	configPath := resolvedModelPath(home, "hermes", ".hermes/config.yaml")
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
	if strings.TrimSpace(credential) != "" {
		yamlSetScalar(modelNode, "api_key", strings.TrimSpace(credential))
		configMode = 0o600
	}
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
	envPath := resolvedModelPath(home, "hermes", ".hermes/.env")
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
	path := resolvedModelPath(home, "claude-code", ".claude/settings.json")
	settings := map[string]any{}
	mode := os.FileMode(0o600)
	body, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(body, &settings); err != nil {
			return fmt.Errorf("Claude Code settings.json is invalid: %w", err)
		}
		if settings == nil {
			return errors.New("model_config.invalid_document")
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
