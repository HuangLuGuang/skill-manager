package managedclient

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"strings"

	"github.com/BurntSushi/toml"
)

func writeNativeJSON(path string, value map[string]any) error {
	body, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return atomicWriteFile(path, append(body, '\n'), 0o600)
}

func readJSONConfig(path string) (map[string]any, error) {
	body, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]any{}, nil
	}
	if err != nil {
		return nil, err
	}
	var root map[string]any
	if decodeModelJSON(body, &root) != nil || root == nil {
		return nil, errors.New("model_config.invalid_json")
	}
	return root, nil
}

func applyNativeModelConfig(home, server, kind, model, credential string) error {
	root, err := readNativeModelConfig(home, kind)
	if err != nil {
		return err
	}
	path := resolvedModelPath(home, kind, modelConfigFiles(kind)[0])
	switch kind {
	case "gemini":
		objectConfig(root, "model")["name"] = model
		configs := objectConfig(root, "modelConfigs")
		overrides, _ := configs["customOverrides"].([]any)
		managed := map[string]any{"match": map[string]any{"overrideScope": "core"}, "modelConfig": map[string]any{"model": model, "generateContentConfig": map[string]any{"topK": nil, "thinkingConfig": nil}}}
		replaced := false
		for i, value := range overrides {
			entry, _ := value.(map[string]any)
			match, _ := entry["match"].(map[string]any)
			if len(match) == 1 && match["overrideScope"] == "core" {
				objectConfig(entry, "modelConfig")["model"] = model
				generation := objectConfig(objectConfig(entry, "modelConfig"), "generateContentConfig")
				if generation["topK"] != nil || generation["thinkingConfig"] != nil {
					return errors.New("model_config.parameter_unsupported")
				}
				generation["topK"], generation["thinkingConfig"] = nil, nil
				overrides[i], replaced = entry, true
			}
		}
		if !replaced {
			overrides = append(overrides, managed)
		}
		configs["customOverrides"] = overrides

		objectConfig(objectConfig(root, "security"), "auth")["selectedType"] = "gemini-api-key"
		envPath := resolvedModelPath(home, kind, ".gemini/.env")
		body, err := os.ReadFile(envPath)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		body = updateEnvValue(body, "GOOGLE_GEMINI_BASE_URL", strings.TrimSuffix(strings.TrimRight(server, "/"), "/v1")+"/client-models/"+hex.EncodeToString([]byte(model)))
		body = updateEnvValue(body, "GEMINI_MODEL", model)
		if credential != "" {
			body = updateEnvValue(body, "GEMINI_API_KEY", credential)
		}
		if err := atomicWriteFile(envPath, body, 0o600); err != nil {
			return err
		}
	case "opencode":
		provider := objectConfig(objectConfig(root, "provider"), "agent_manager")
		provider["npm"], provider["name"] = "@ai-sdk/openai-compatible", "Agent Manager"
		options := objectConfig(provider, "options")
		options["baseURL"] = modelGatewayV1(server)
		if credential != "" {
			options["apiKey"] = credential
		}
		entry := objectConfig(objectConfig(provider, "models"), model)
		entry["name"] = model
		root["model"] = "agent_manager/" + model
	case "openclaw":
		provider := objectConfig(objectConfig(objectConfig(root, "models"), "providers"), "agent_manager")
		provider["baseUrl"], provider["api"] = modelGatewayV1(server), "openai-completions"
		if credential != "" {
			provider["apiKey"] = credential
		}
		entries, _ := provider["models"].([]any)
		found := false
		for _, entry := range entries {
			if obj, ok := entry.(map[string]any); ok && obj["id"] == model {
				found = true
			}
		}
		if !found {
			entries = append(entries, map[string]any{"id": model, "name": model})
		}
		provider["models"] = entries
		defaults := objectConfig(objectConfig(root, "agents"), "defaults")
		// Preserve the fallback list when the native model setting is an object.
		selected := objectConfig(defaults, "model")
		selected["primary"] = "agent_manager/" + model
		objectConfig(objectConfig(defaults, "models"), "agent_manager/"+model)
	case "pi":
		modelsPath := resolvedModelPath(home, kind, ".pi/agent/models.json")
		models, err := readJSONConfig(modelsPath)
		if err != nil {
			return err
		}
		provider := objectConfig(objectConfig(models, "providers"), "agent_manager")
		provider["baseUrl"], provider["api"] = modelGatewayV1(server), "openai-completions"
		objectConfig(provider, "compat")["supportsStore"] = false
		if credential != "" {
			provider["apiKey"] = credential
		}
		entries, _ := provider["models"].([]any)
		found := false
		for _, entry := range entries {
			if obj, ok := entry.(map[string]any); ok && obj["id"] == model {
				found = true
			}
		}
		if !found {
			entries = append(entries, map[string]any{"id": model, "name": model})
		}
		provider["models"] = entries
		if err := writeNativeJSON(modelsPath, models); err != nil {
			return err
		}
		root["defaultProvider"], root["defaultModel"] = "agent_manager", model
	case "grokbuild":
		objectConfig(root, "models")["default"] = "agent_manager"
		entry := objectConfig(objectConfig(root, "model"), "agent_manager")
		entry["model"], entry["name"], entry["base_url"], entry["api_backend"] = model, "Agent Manager", modelGatewayV1(server), "responses"
		if credential != "" {
			entry["api_key"] = credential
			delete(entry, "env_key")
		}
		var output bytes.Buffer
		if err := toml.NewEncoder(&output).Encode(root); err != nil {
			return err
		}
		return atomicWriteFile(path, output.Bytes(), 0o600)
	default:
		return errors.New("model_config.agent_unsupported")
	}
	return writeNativeJSON(path, root)
}

func inspectNativeModelConfig(home, kind string) ModelConfigState {
	state := ModelConfigState{Supported: true, ConfigPath: resolvedModelPath(home, kind, modelConfigFiles(kind)[0])}
	root, err := readNativeModelConfig(home, kind)
	if err != nil {
		state.Error = err.Error()
		return state
	}
	get := func(root map[string]any, parts ...string) string {
		var value any = root
		for _, part := range parts {
			object, ok := value.(map[string]any)
			if !ok {
				return ""
			}
			value = object[part]
		}
		text, _ := value.(string)
		return text
	}
	switch kind {
	case "gemini":
		state.Model = get(root, "model", "name")
		body, err := os.ReadFile(resolvedModelPath(home, kind, ".gemini/.env"))
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			state.Error = err.Error()
			return state
		}
		for _, line := range strings.Split(string(body), "\n") {
			key, value, found := strings.Cut(strings.TrimSpace(line), "=")
			if found && key == "GOOGLE_GEMINI_BASE_URL" {
				state.GatewayURL = value
			}
		}
	case "opencode":
		selected := get(root, "model")
		state.Model = strings.TrimPrefix(selected, "agent_manager/")
		provider := strings.SplitN(selected, "/", 2)[0]
		state.GatewayURL = get(root, "provider", provider, "options", "baseURL")
	case "openclaw":
		selected := get(root, "agents", "defaults", "model", "primary")
		if selected == "" {
			selected = get(root, "agents", "defaults", "model")
		}
		state.Model = strings.TrimPrefix(selected, "agent_manager/")
		provider := strings.SplitN(selected, "/", 2)[0]
		state.GatewayURL = get(root, "models", "providers", provider, "baseUrl")
	case "pi":
		state.Model = get(root, "defaultModel")
		models, err := readJSONConfig(resolvedModelPath(home, kind, ".pi/agent/models.json"))
		if err != nil {
			state.Error = err.Error()
			return state
		}
		state.GatewayURL = get(models, "providers", get(root, "defaultProvider"), "baseUrl")
	case "grokbuild":
		profile := get(root, "models", "default")
		state.Model = get(root, "model", profile, "model")
		state.GatewayURL = get(root, "model", profile, "base_url")
	}
	state.Revision, _ = ModelConfigRevision(home, kind)
	state.Parameters, _ = readModelParameters(home, kind)
	return state
}
