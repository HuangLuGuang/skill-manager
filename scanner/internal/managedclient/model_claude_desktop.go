package managedclient

import (
	"encoding/hex"
	"errors"
	"strings"
)

const desktopProfileID = "19bff109-59d3-4d28-bb3c-233e18174c13"

func applyClaudeDesktopConfig(home, server, model, credential string) error {
	files := modelConfigFiles("claude-desktop")
	if len(files) != 4 {
		return errors.New("model_config.platform_unsupported")
	}
	for _, path := range files[:2] {
		root, err := readJSONConfig(resolvedModelPath(home, "claude-desktop", path))
		if err != nil {
			return err
		}
		root["deploymentMode"] = "3p"
		if err := writeNativeJSON(resolvedModelPath(home, "claude-desktop", path), root); err != nil {
			return err
		}
	}
	profile, err := readJSONConfig(resolvedModelPath(home, "claude-desktop", files[2]))
	if err != nil {
		return err
	}
	profile["inferenceProvider"] = "gateway"
	profile["inferenceGatewayBaseUrl"] = strings.TrimSuffix(strings.TrimRight(server, "/"), "/v1") + "/client-models/" + hex.EncodeToString([]byte(model))
	profile["inferenceGatewayAuthScheme"] = "bearer"
	if credential != "" {
		profile["inferenceGatewayApiKey"] = credential
	}
	profile["inferenceModels"] = []any{map[string]any{"name": "claude-sonnet-5", "labelOverride": model}}
	if err := writeNativeJSON(resolvedModelPath(home, "claude-desktop", files[2]), profile); err != nil {
		return err
	}
	meta, err := readJSONConfig(resolvedModelPath(home, "claude-desktop", files[3]))
	if err != nil {
		return err
	}
	entries, _ := meta["entries"].([]any)
	kept := make([]any, 0, len(entries)+1)
	for _, value := range entries {
		if entry, ok := value.(map[string]any); !ok || entry["id"] != desktopProfileID {
			kept = append(kept, value)
		}
	}
	meta["entries"] = append(kept, map[string]any{"id": desktopProfileID, "name": "Agent Manager"})
	meta["appliedId"] = desktopProfileID
	return writeNativeJSON(resolvedModelPath(home, "claude-desktop", files[3]), meta)
}

func inspectClaudeDesktopConfig(home string) ModelConfigState {
	files := modelConfigFiles("claude-desktop")
	if len(files) != 4 {
		return ModelConfigState{Error: "model_config.platform_unsupported"}
	}
	state := ModelConfigState{Supported: true, ConfigPath: resolvedModelPath(home, "claude-desktop", files[2])}
	profile, err := readJSONConfig(state.ConfigPath)
	if err != nil {
		state.Error = err.Error()
		return state
	}
	state.GatewayURL, _ = profile["inferenceGatewayBaseUrl"].(string)
	if index := strings.LastIndex(state.GatewayURL, "/client-models/"); index >= 0 {
		if model, err := hex.DecodeString(state.GatewayURL[index+len("/client-models/"):]); err == nil {
			state.Model = string(model)
		}
	}
	state.Revision, _ = ModelConfigRevision(home, "claude-desktop")
	return state
}
