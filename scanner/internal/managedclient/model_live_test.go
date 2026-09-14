package managedclient

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Opt-in integration test. The supplied client must be a dedicated test client;
// every Agent receives a fresh HOME and its own task-issued runtime credential.
// A successful process is only Agent evidence; correlate it with gateway logs.
func TestLiveModelSwitch(t *testing.T) {
	server, token, clientID := os.Getenv("AM_TEST_SERVER"), os.Getenv("AM_TEST_CLIENT_TOKEN"), os.Getenv("AM_TEST_CLIENT_ID")
	if server == "" || token == "" || clientID == "" {
		t.Skip("live test environment not configured")
	}
	kind := os.Getenv("AM_TEST_AGENT")
	spec, ok := modelAdapters[kind]
	if !ok {
		t.Fatal("AM_TEST_AGENT must select an adapter")
	}
	binary, err := exec.LookPath(spec.Binary)
	if err != nil {
		t.Skip("Agent binary unavailable")
	}
	home := t.TempDir()
	if runtime.GOOS == "darwin" {
		home, err = os.MkdirTemp("/tmp", "am-live-")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.RemoveAll(home) })
	}
	env := []string{"PATH=" + os.Getenv("PATH"), "HOME=" + home, "XDG_CONFIG_HOME=" + filepath.Join(home, ".config"), "XDG_DATA_HOME=" + filepath.Join(home, ".local", "share"), "XDG_CACHE_HOME=" + filepath.Join(home, ".cache"), "CODEX_HOME=" + filepath.Join(home, ".codex"), "CLAUDE_CONFIG_DIR=" + filepath.Join(home, ".claude"), "HERMES_HOME=" + filepath.Join(home, ".hermes"), "GEMINI_CLI_HOME=" + home, "PI_CODING_AGENT_DIR=" + filepath.Join(home, ".pi", "agent"), "PI_OFFLINE=1", "GEMINI_TELEMETRY_ENABLED=false", "GEMINI_CLI_TRUST_WORKSPACE=true", "NO_COLOR=1"}
	for _, path := range []string{".codex", ".claude", ".hermes", ".gemini", ".pi/agent"} {
		if err := os.MkdirAll(filepath.Join(home, path), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	model := os.Getenv("AM_TEST_MODEL")
	if model == "" {
		t.Fatal("AM_TEST_MODEL is required")
	}
	parameters := map[string]any{}
	if raw := os.Getenv("AM_TEST_PARAMETERS"); raw != "" {
		if err := json.Unmarshal([]byte(raw), &parameters); err != nil {
			t.Fatal(err)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Second)
	defer cancel()
	revision, err := ModelConfigRevision(home, kind)
	if err != nil {
		t.Fatal(err)
	}
	target, err := url.Parse(server)
	if err != nil {
		t.Fatal(err)
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	var toolResults atomic.Int32
	proxy.ModifyResponse = func(response *http.Response) error {
		if response.StatusCode >= 400 {
			body, err := io.ReadAll(response.Body)
			if err != nil {
				return err
			}
			response.Body.Close()
			response.Body = io.NopCloser(bytes.NewReader(body))
			var failure map[string]any
			_ = json.Unmarshal(body, &failure)
			if details, ok := failure["detail"].([]any); ok {
				for _, value := range details {
					if detail, ok := value.(map[string]any); ok {
						t.Logf("gateway validation status=%d location=%v type=%v", response.StatusCode, detail["loc"], detail["type"])
					}
				}
			}
		}
		return nil
	}
	relay := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if !strings.HasPrefix(request.URL.Path, "/api/") && request.Method == "POST" {
			body, err := io.ReadAll(request.Body)
			if err != nil {
				http.Error(w, "read error", 400)
				return
			}
			request.Body.Close()
			request.Body = io.NopCloser(bytes.NewReader(body))
			var payload map[string]any
			_ = json.Unmarshal(body, &payload)
			toolResults.Add(int32(countLiveToolResults(payload)))
			observed := map[string]any{"path": request.URL.Path}
			for _, key := range []string{"model", "stream", "temperature", "top_p", "max_tokens", "max_completion_tokens", "max_output_tokens", "reasoning", "reasoning_effort", "text", "store", "generationConfig"} {
				if value, ok := payload[key]; ok {
					observed[key] = value
				}
			}
			encoded, _ := json.Marshal(observed)
			t.Logf("Agent request %s", encoded)
		}
		proxy.ServeHTTP(w, request)
	}))
	defer relay.Close()
	err = ConfigureAgentModel(ctx, home, Inventory{ClientID: clientID}, NewAPI(relay.URL, token, 30*time.Second), store, kind, kind, "", model, map[string]any{"parameters": parameters, "expected_revision": revision})
	if err != nil {
		t.Fatal(err)
	}
	if os.Getenv("AM_TEST_TOOL_CALL") == "1" {
		workspace := home
		if kind == "gemini" {
			workspace = filepath.Join(home, "work")
			if err := os.Mkdir(workspace, 0o700); err != nil {
				t.Fatal(err)
			}
		}
		nonce := make([]byte, 16)
		if _, err := rand.Read(nonce); err != nil {
			t.Fatal(err)
		}
		marker := fmt.Sprintf("violet %d river %d amber", nonce[0], nonce[1])
		if err := os.WriteFile(filepath.Join(workspace, "connection-fixture.txt"), []byte(marker), 0o600); err != nil {
			t.Fatal(err)
		}
		prompt := "Read connection-fixture.txt with the file reading tool and return its contents exactly."
		instructions := "You verify a file reading tool. Read the requested local file and return its contents."
		var args []string
		switch kind {
		case "gemini":
			path := resolvedModelPath(home, kind, ".gemini/settings.json")
			config, err := readJSONConfig(path)
			if err != nil {
				t.Fatal(err)
			}
			objectConfig(config, "tools")["core"] = []string{"read_file"}
			if err := writeNativeJSON(path, config); err != nil {
				t.Fatal(err)
			}
			args = []string{"-p", prompt, "--output-format", "json"}
		case "claude-code":
			args = []string{"-p", prompt, "--output-format", "json", "--max-turns", "3", "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config", "--mcp-config", `{"mcpServers":{}}`, "--system-prompt", instructions}
		case "pi":
			args = []string{"--print", "--mode", "json", "--offline", "--tools", "read", "--system-prompt", instructions, prompt}
		case "codex":
			instructionsPath := filepath.Join(home, "connection-check.md")
			if err := os.WriteFile(instructionsPath, []byte(instructions), 0o600); err != nil {
				t.Fatal(err)
			}
			args = []string{"-c", "model_instructions_file=" + fmt.Sprintf("%q", instructionsPath), "exec", "--skip-git-repo-check", "--json", "--sandbox", "read-only", prompt}
		case "hermes":
			args = []string{"chat", "-q", prompt, "-Q", "--max-turns", "3", "--ignore-rules", "--toolsets", "file"}
		default:
			t.Skip("File-tool verification command not established")
		}
		command := exec.CommandContext(ctx, binary, args...)
		command.Dir, command.Env = workspace, modelProbeEnvironment(home)
		if kind == "gemini" {
			path := filepath.Join(home, "connection-check.md")
			if err := os.WriteFile(path, []byte(instructions), 0o600); err != nil {
				t.Fatal(err)
			}
			command.Env = append(command.Env, "GEMINI_SYSTEM_MD="+path)
		}
		output, callErr := command.CombinedOutput()
		t.Logf("native file tool: agent=%s model=%s tool_result_requests=%d process_error=%v answer_contains_file=%t", kind, model, toolResults.Load(), callErr, liveToolHasAnswer(kind, output, marker))
		if callErr != nil || toolResults.Load() == 0 || !liveToolHasAnswer(kind, output, marker) {
			redacted := regexp.MustCompile(`amat_[A-Za-z0-9_-]+`).ReplaceAll(output, []byte("[REDACTED]"))
			if len(redacted) > 3000 {
				redacted = redacted[len(redacted)-3000:]
			}
			t.Logf("isolated tool diagnostic: %s", redacted)
			t.Fatal("Native file-tool round trip failed")
		}
		return
	}
	if os.Getenv("AM_TEST_NATIVE_PROBE") == "1" {
		operation := func(name string) error {
			inventory, err := Discover(home)
			if err != nil {
				return err
			}
			inventory.ClientID = clientID
			return ConfigureModelOperation(ctx, home, kind, name, NewAPI(server, token, 30*time.Second), inventory, store)
		}
		verify := func() ([]ModelRequestEvidence, error) {
			if os.Getenv("AM_TEST_MODEL_OPERATIONS") == "1" {
				err := operation("verify_model_config")
				return InspectModelConfig(home, kind).Verification, err
			}
			return VerifyModelConfig(ctx, home, kind, kind, NewAPI(server, token, 30*time.Second), Inventory{ClientID: clientID})
		}
		if os.Getenv("AM_TEST_PROBE_DIAGNOSTICS") == "1" && kind == "codex" {
			instructions := filepath.Join(home, "connection-check.md")
			if err := os.WriteFile(instructions, []byte(modelProbeInstructions), 0o600); err != nil {
				t.Fatal(err)
			}
			args, _ := modelProbeCommand(kind, "Reply with exactly MODEL_SWITCH_OK.")
			args = append([]string{"-c", "model_instructions_file=" + fmt.Sprintf("%q", instructions)}, args...)
			command := exec.CommandContext(ctx, binary, args...)
			command.Dir, command.Env = home, modelProbeEnvironment(home)
			output, callErr := command.CombinedOutput()
			redacted := regexp.MustCompile(`amat_[A-Za-z0-9_-]+`).ReplaceAll(output, []byte("[REDACTED]"))
			if len(redacted) > 4000 {
				redacted = redacted[:4000]
			}
			t.Logf("isolated diagnostic: %v %s", callErr, redacted)
		}
		evidence, err := verify()
		encoded, _ := json.Marshal(evidence)
		t.Logf("gateway evidence %s", encoded)
		if err != nil {
			t.Fatal(err)
		}
		if secondModel := os.Getenv("AM_TEST_SECOND_MODEL"); secondModel != "" {
			before := InspectModelConfig(home, kind)
			if err := ConfigureAgentModel(ctx, home, Inventory{ClientID: clientID}, NewAPI(server, token, 30*time.Second), store, kind, kind, "", secondModel, map[string]any{"parameters": parameters, "expected_revision": before.Revision}); err != nil {
				t.Fatal(err)
			}
			second := InspectModelConfig(home, kind)
			evidence, err := verify()
			encoded, _ := json.Marshal(evidence)
			t.Logf("model B gateway evidence %s", encoded)
			if err != nil {
				t.Fatal(err)
			}
			restore := func() error { return RestoreModelConfig(home, second.ChangeID) }
			if os.Getenv("AM_TEST_MODEL_OPERATIONS") == "1" {
				restore = func() error { return operation("restore_model_config") }
			}
			if err := restore(); err != nil {
				t.Fatal(err)
			}
			restored := InspectModelConfig(home, kind)
			if restored.Model != model || restored.Revision != before.Revision {
				t.Fatal("Restored configuration differs from model A")
			}
			evidence, err = verify()
			encoded, _ = json.Marshal(evidence)
			t.Logf("restored model A gateway evidence %s", encoded)
			if err != nil {
				t.Fatal(err)
			}
		}
		return
	}
	prompt := "Reply with exactly MODEL_SWITCH_OK. Do not call tools."
	var args []string
	switch kind {
	case "claude-code":
		args = []string{"-p", prompt, "--output-format", "json", "--max-turns", "1", "--tools", "", "--strict-mcp-config", "--mcp-config", `{"mcpServers":{}}`}
	case "codex":
		args = []string{"exec", "--skip-git-repo-check", "--json", "--sandbox", "read-only", prompt}
	case "hermes":
		args = []string{"chat", "-q", prompt, "-Q", "--max-turns", "1", "--ignore-rules"}
	case "opencode":
		args = []string{"run", "--format", "json", prompt}
	case "pi":
		args = []string{"--print", "--mode", "json", "--offline", prompt}
	case "gemini":
		args = []string{"-p", prompt, "--output-format", "json"}
	default:
		t.Skip("No unattended verification command established for this Agent")
	}
	command := exec.CommandContext(ctx, binary, args...)
	command.Dir, command.Env = home, env
	output, err := command.CombinedOutput()
	sanitized := regexp.MustCompile(`amat_[A-Za-z0-9_-]+`).ReplaceAllString(string(output), "[REDACTED]")
	if len(sanitized) > 12000 {
		sanitized = sanitized[len(sanitized)-12000:]
	}
	t.Logf("agent=%s model=%s output=%s", kind, model, sanitized)
	if err != nil {
		t.Fatalf("Agent process failed: %v", err)
	}
	if !liveAgentHasAnswer(kind, output) {
		t.Fatal("Agent response marker missing; inspect gateway evidence")
	}
	t.Log("Agent process completed; gateway model/parameter evidence must be checked separately")
}

func countLiveToolResults(payload map[string]any) int {
	count := 0
	if contents, ok := payload["contents"].([]any); ok {
		for _, value := range contents {
			content, _ := value.(map[string]any)
			parts, _ := content["parts"].([]any)
			for _, value := range parts {
				part, _ := value.(map[string]any)
				if _, ok := part["functionResponse"]; ok {
					count++
				}
			}
		}
	}
	for _, field := range []string{"messages", "input"} {
		items, _ := payload[field].([]any)
		for _, value := range items {
			item, _ := value.(map[string]any)
			if item["role"] == "tool" || item["type"] == "function_call_output" {
				count++
			}
			parts, _ := item["content"].([]any)
			for _, value := range parts {
				part, _ := value.(map[string]any)
				if part["type"] == "tool_result" {
					count++
				}
			}
		}
	}
	return count
}

// Tool verification permits explanatory text around the file contents. The
// random file contents are absent from the prompt; only assistant output counts.
func liveToolHasAnswer(kind string, output []byte, marker string) bool {
	if kind == "gemini" {
		start := bytes.IndexByte(output, '{')
		var result struct {
			Response string `json:"response"`
			Error    any    `json:"error"`
		}
		return start >= 0 && json.Unmarshal(output[start:], &result) == nil && result.Error == nil && strings.Contains(result.Response, marker)
	}
	if kind == "hermes" {
		// Hermes -Q emits the final answer and session metadata, suppressing
		// tool previews. The marker is never included in the input prompt.
		return strings.Contains(string(output), marker)
	}
	for _, line := range bytes.Split(output, []byte{'\n'}) {
		var event map[string]any
		if json.Unmarshal(line, &event) != nil {
			continue
		}
		if kind == "claude-code" && event["type"] == "result" && event["is_error"] == false {
			answer, _ := event["result"].(string)
			if strings.Contains(answer, marker) {
				return true
			}
		}
		if kind == "pi" && event["type"] == "message_end" {
			message, _ := event["message"].(map[string]any)
			if message["role"] != "assistant" || message["stopReason"] == "error" {
				continue
			}
			parts, _ := message["content"].([]any)
			for _, value := range parts {
				part, _ := value.(map[string]any)
				answer, _ := part["text"].(string)
				if part["type"] == "text" && strings.Contains(answer, marker) {
					return true
				}
			}
		}
		if kind == "codex" && event["type"] == "item.completed" {
			item, _ := event["item"].(map[string]any)
			answer, _ := item["text"].(string)
			if item["type"] == "agent_message" && strings.Contains(answer, marker) {
				return true
			}
		}
	}
	return false
}

func liveAgentHasAnswer(kind string, output []byte) bool {
	if kind == "hermes" {
		return strings.Contains(string(output), "\nMODEL_SWITCH_OK")
	}
	if kind == "gemini" {
		var result map[string]any
		return json.Unmarshal(output, &result) == nil && result["response"] == "MODEL_SWITCH_OK" && result["error"] == nil
	}
	for _, line := range bytes.Split(output, []byte{'\n'}) {
		var event map[string]any
		if json.Unmarshal(line, &event) != nil {
			continue
		}
		if kind == "claude-code" && event["type"] == "result" && event["result"] == "MODEL_SWITCH_OK" && event["is_error"] == false {
			return true
		}
		if kind == "codex" {
			if item, ok := event["item"].(map[string]any); ok && item["type"] == "agent_message" && item["text"] == "MODEL_SWITCH_OK" {
				return true
			}
		}
		if kind == "pi" && event["type"] == "message_end" {
			if message, ok := event["message"].(map[string]any); ok && message["role"] == "assistant" && message["stopReason"] != "error" {
				if parts, ok := message["content"].([]any); ok {
					for _, value := range parts {
						if part, ok := value.(map[string]any); ok && part["type"] == "text" && part["text"] == "MODEL_SWITCH_OK" {
							return true
						}
					}
				}
			}
		}
		if kind == "opencode" && event["type"] == "text" {
			if part, ok := event["part"].(map[string]any); ok && part["text"] == "MODEL_SWITCH_OK" {
				return true
			}
		}
	}
	return false
}
