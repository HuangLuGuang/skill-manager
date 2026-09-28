package managedclient

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

type ModelRequestEvidence struct {
	RequestID        string         `json:"request_id,omitempty"`
	Model            string         `json:"model"`
	Status           string         `json:"status"`
	Parameters       map[string]any `json:"parameters"`
	VerificationMode string         `json:"verification_mode,omitempty"`
}

const modelProbeInstructions = "You are checking a model connection. Return the marker requested by the user exactly. Do not use tools."

type modelProbeOutput struct{ bytes.Buffer }

func (output *modelProbeOutput) Write(value []byte) (int, error) {
	length := len(value)
	remaining := 4*1024*1024 - output.Len()
	if remaining > 0 {
		if len(value) > remaining {
			value = value[:remaining]
		}
		_, _ = output.Buffer.Write(value)
	}
	return length, nil
}

func modelProbeCommand(kind, prompt string) ([]string, error) {
	switch kind {
	case "claude-code":
		return []string{"-p", prompt, "--output-format", "json", "--max-turns", "1", "--tools", "", "--strict-mcp-config", "--mcp-config", `{"mcpServers":{}}`, "--system-prompt", modelProbeInstructions}, nil
	case "codex":
		return []string{"exec", "--skip-git-repo-check", "--json", "--sandbox", "read-only", prompt}, nil
	case "hermes":
		return []string{"chat", "-q", prompt, "-Q", "--max-turns", "1", "--ignore-rules"}, nil
	case "pi":
		return []string{"--print", "--mode", "json", "--offline", "--system-prompt", modelProbeInstructions, prompt}, nil
	case "gemini":
		return []string{"-p", prompt, "--output-format", "json"}, nil
	case "opencode":
		return []string{"run", "--format", "json", "--agent", "agent_manager_probe", prompt}, nil
	default:
		return nil, errors.New("model_config.verification_unavailable")
	}
}

func modelProbeEnvironment(home string) []string {
	return []string{"PATH=" + os.Getenv("PATH"), "HOME=" + home, "XDG_CONFIG_HOME=" + filepath.Join(home, ".config"), "XDG_DATA_HOME=" + filepath.Join(home, ".local", "share"), "XDG_CACHE_HOME=" + filepath.Join(home, ".cache"), "CODEX_HOME=" + filepath.Join(home, ".codex"), "CLAUDE_CONFIG_DIR=" + filepath.Join(home, ".claude"), "HERMES_HOME=" + filepath.Join(home, ".hermes"), "GEMINI_CLI_HOME=" + home, "GEMINI_CLI_TRUST_WORKSPACE=true", "GEMINI_TELEMETRY_ENABLED=false", "PI_CODING_AGENT_DIR=" + filepath.Join(home, ".pi", "agent"), "PI_OFFLINE=1", "NO_COLOR=1"}
}

func nativeModelCredential(home, kind string) (string, error) {
	root, err := readNativeModelConfig(home, kind)
	if err != nil {
		return "", err
	}
	var path []string
	switch kind {
	case "claude-code":
		path = []string{"env", "ANTHROPIC_AUTH_TOKEN"}
	case "codex":
		path = []string{"model_providers", "agent_manager", "experimental_bearer_token"}
	case "hermes":
		path = []string{"model", "api_key"}
	case "opencode":
		path = []string{"provider", "agent_manager", "options", "apiKey"}
	case "openclaw":
		path = []string{"models", "providers", "agent_manager", "apiKey"}
	case "grokbuild":
		path = []string{"model", "agent_manager", "api_key"}
	case "claude-desktop":
		files := modelConfigFiles(kind)
		if len(files) != 4 {
			return "", errors.New("model_config.platform_unsupported")
		}
		root, err = readJSONConfig(resolvedModelPath(home, kind, files[2]))
		path = []string{"inferenceGatewayApiKey"}
	case "pi":
		root, err = readJSONConfig(resolvedModelPath(home, kind, ".pi/agent/models.json"))
		path = []string{"providers", "agent_manager", "apiKey"}
	case "gemini":
		body, readErr := os.ReadFile(resolvedModelPath(home, kind, ".gemini/.env"))
		if readErr != nil {
			return "", readErr
		}
		for _, line := range strings.Split(string(body), "\n") {
			key, value, ok := strings.Cut(line, "=")
			if ok && key == "GEMINI_API_KEY" {
				return strings.Trim(value, "\"' "), nil
			}
		}
	default:
		return "", errors.New("model_config.verification_unavailable")
	}
	if err != nil {
		return "", err
	}
	var value any = root
	for _, key := range path {
		object, ok := value.(map[string]any)
		if !ok {
			return "", errors.New("model_config.credential_missing")
		}
		value = object[key]
	}
	token, _ := value.(string)
	if token == "" {
		return "", errors.New("model_config.credential_missing")
	}
	return token, nil
}

// Verify the managed model and parameters with an installed native Agent in a
// fresh home. Native hooks, skills and user extensions are not copied to it.
// The local response and a challenge-correlated gateway audit must both pass.
func VerifyModelConfig(ctx context.Context, home, kind, localID string, api API, inventory Inventory) (evidence []ModelRequestEvidence, resultErr error) {
	state := InspectModelConfig(home, kind)
	if state.Revision == "" {
		return nil, errors.New("model_config.readback_failed")
	}
	if state.Revision != state.AppliedRevision {
		return nil, errors.New("model_config.conflict")
	}
	if state.ChangeID == "" || state.Model == "" {
		return nil, errors.New("model_config.change_invalid")
	}
	journalUpdated := false
	defer func() {
		if resultErr == nil || journalUpdated {
			return
		}
		unlock, err := lockModelConfig(home, kind)
		if err != nil {
			return
		}
		defer unlock()
		revision, err := ModelConfigRevision(home, kind)
		if err != nil || revision != state.Revision {
			return
		}
		path := filepath.Join(home, ".agent-manager", "model-changes", state.ChangeID+".json")
		body, err := os.ReadFile(path)
		var change ModelChange
		if err != nil || json.Unmarshal(body, &change) != nil {
			return
		}
		change.Status, change.Error, change.Evidence = "failed", resultErr.Error(), evidence
		_ = saveModelChange(path, change)
	}()
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}
	encoded := hex.EncodeToString(nonce)
	challenge := "AM_VERIFY_" + encoded[:8] + "-" + encoded[8:12] + "-" + encoded[12:16] + "-" + encoded[16:20] + "-" + encoded[20:]
	args, err := modelProbeCommand(kind, "Reply with exactly "+challenge+". Do not call tools.")
	if err != nil {
		return nil, err
	}
	binary, err := exec.LookPath(modelAdapters[kind].Binary)
	if err != nil {
		return nil, errors.New("model_config.agent_missing")
	}
	if err := validateModelParameterVersion(kind, discoverModelVersion(home, kind, binary), state.Parameters); err != nil {
		return nil, err
	}
	credential, err := nativeModelCredential(home, kind)
	if err != nil {
		return nil, err
	}
	probeRoot := ""
	if runtime.GOOS == "darwin" {
		// Agent context may include the absolute workspace path. Avoid the
		// per-user /var/folders identifier in macOS's default temporary root.
		probeRoot = "/tmp"
	}
	temporary, err := os.MkdirTemp(probeRoot, "am-probe-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(temporary)
	workspace := filepath.Join(temporary, "work")
	if err := os.Mkdir(workspace, 0o700); err != nil {
		return nil, err
	}
	probeGateway := strings.TrimSpace(state.GatewayURL)
	if probeGateway == "" {
		probeGateway = api.server
	}
	if err = renderModelConfig(temporary, probeGateway, localID, kind, state.Model, credential); err != nil {
		return nil, err
	}
	if err = writeModelParameters(temporary, kind, state.Parameters); err != nil {
		return nil, err
	}
	if kind == "opencode" {
		if err := prepareOpenCodeProbe(ctx, temporary, binary); err != nil {
			return nil, err
		}
	}
	if kind == "gemini" {
		path := resolvedModelPath(temporary, kind, ".gemini/settings.json")
		config, err := readJSONConfig(path)
		if err != nil {
			return nil, err
		}
		// Gemini's native core allowlist keeps a connection-only probe from
		// registering file, shell or network tools in its isolated session.
		objectConfig(config, "tools")["core"] = []string{}
		if err := writeNativeJSON(path, config); err != nil {
			return nil, err
		}
	}
	probeCtx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	instructions := filepath.Join(temporary, "connection-check.md")
	if err := os.WriteFile(instructions, []byte(modelProbeInstructions), 0o600); err != nil {
		return nil, err
	}
	if kind == "codex" {
		args = append([]string{"-c", "model_instructions_file=" + strconv.Quote(instructions)}, args...)
	}
	command := configureWindowsCommand(exec.CommandContext(probeCtx, binary, args...))
	// Native context builders inspect the working directory. Keep it empty
	// and separate from the home containing runtime credentials.
	command.Dir = workspace
	command.Env = modelProbeEnvironment(temporary)
	if kind == "gemini" {
		command.Env = append(command.Env, "GEMINI_SYSTEM_MD="+instructions)
	}
	if kind == "opencode" {
		command.Env = append(command.Env, "OPENCODE_DISABLE_AUTOUPDATE=true", "OPENCODE_DISABLE_DEFAULT_PLUGINS=true", "OPENCODE_DISABLE_LSP_DOWNLOAD=true", "OPENCODE_DISABLE_MODELS_FETCH=true", "OPENCODE_DISABLE_PROJECT_CONFIG=true", "OPENCODE_DISABLE_EXTERNAL_SKILLS=true", "OPENCODE_TEST_MANAGED_CONFIG_DIR="+filepath.Join(temporary, "managed"))
	}
	var captured modelProbeOutput
	command.Stdout, command.Stderr = &captured, &captured
	processErr := command.Run()
	output := captured.Bytes()
	var response struct {
		Requests []ModelRequestEvidence `json:"requests"`
	}
	if state.VerificationMode != "client_call" {
		resultErr = api.postJSON(ctx, "/api/v1/clients/"+inventory.ClientID+"/model-verification-evidence", map[string]any{"agent_type": kind, "local_agent_id": localID, "challenge": challenge}, &response)
	}
	if resultErr == nil && state.VerificationMode != "client_call" {
		for _, request := range response.Requests {
			if request.Status == "blocked" {
				resultErr = errors.New("model_config.gateway_blocked")
				break
			}
		}
	}
	if resultErr == nil {
		switch {
		case probeCtx.Err() != nil:
			resultErr = errors.New("model_config.verification_timeout")
		case processErr != nil:
			resultErr = errors.New("model_config.agent_call_failed")
		case !modelProbeHasAnswer(kind, output, challenge):
			resultErr = errors.New("model_config.agent_response_missing")
		default:
			if state.VerificationMode == "client_call" {
				response.Requests = []ModelRequestEvidence{{
					Model:            state.Model,
					Status:           "success",
					Parameters:       state.Parameters,
					VerificationMode: "client_call",
				}}
				break
			}
			matched := false
			for _, request := range response.Requests {
				if request.Model == state.Model && request.Status == "success" {
					matched = true
					for key, value := range state.Parameters {
						field := modelAdapters[kind].Parameters[key]
						if field.Condition == "local" {
							continue
						}
						actual, ok := request.Parameters[field.Wire]
						expectedJSON, _ := json.Marshal(value)
						actualJSON, _ := json.Marshal(actual)
						if !ok || !bytes.Equal(expectedJSON, actualJSON) {
							matched = false
							break
						}
					}
					if matched {
						break
					}
				}
			}
			if !matched {
				resultErr = errors.New("model_config.gateway_evidence_missing")
			}
		}
	}
	unlock, err := lockModelConfig(home, kind)
	if err != nil {
		return response.Requests, err
	}
	defer unlock()
	revision, err := ModelConfigRevision(home, kind)
	if err != nil {
		return response.Requests, err
	}
	if revision != state.Revision {
		return response.Requests, errors.New("model_config.conflict")
	}
	path := filepath.Join(home, ".agent-manager", "model-changes", state.ChangeID+".json")
	body, err := os.ReadFile(path)
	if err != nil {
		return response.Requests, err
	}
	var change ModelChange
	if err = json.Unmarshal(body, &change); err != nil {
		return response.Requests, err
	}
	change.Evidence = response.Requests
	change.Status = "verified"
	change.Error = ""
	if resultErr != nil {
		change.Status = "failed"
		change.Error = resultErr.Error()
	}
	if err = saveModelChange(path, change); err != nil {
		return response.Requests, err
	}
	journalUpdated = true
	return response.Requests, resultErr
}

func modelProbeHasAnswer(kind string, output []byte, marker string) bool {
	if kind == "hermes" {
		for _, line := range strings.Split(string(output), "\n") {
			if strings.TrimSpace(line) == marker {
				return true
			}
		}
		return false
	}
	if kind == "gemini" {
		for i, b := range output {
			if b != '{' {
				continue
			}
			var result map[string]any
			if json.Unmarshal(output[i:], &result) == nil && strings.TrimSpace(fmt.Sprint(result["response"])) == marker && result["error"] == nil {
				return true
			}
		}
		return false
	}
	for _, line := range bytes.Split(output, []byte{'\n'}) {
		var event map[string]any
		if json.Unmarshal(line, &event) != nil {
			continue
		}
		if kind == "opencode" && event["type"] == "text" {
			if part, ok := event["part"].(map[string]any); ok && strings.TrimSpace(fmt.Sprint(part["text"])) == marker {
				return true
			}
		}
		if kind == "claude-code" && event["type"] == "result" && event["result"] == marker && event["is_error"] == false {
			return true
		}
		if kind == "codex" {
			if item, ok := event["item"].(map[string]any); ok && item["type"] == "agent_message" && item["text"] == marker {
				return true
			}
		}
		if kind == "pi" && event["type"] == "message_end" {
			if message, ok := event["message"].(map[string]any); ok && message["role"] == "assistant" && message["stopReason"] != "error" {
				if parts, ok := message["content"].([]any); ok {
					for _, value := range parts {
						if part, ok := value.(map[string]any); ok && part["type"] == "text" && part["text"] == marker {
							return true
						}
					}
				}
			}
		}
	}
	return false
}
