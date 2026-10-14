package hooks

import (
	"bytes"
	"encoding/json"
	"io"
)

type input struct {
	ProjectionInput  json.RawMessage `json:"-"`
	WorkspaceRoots   []string        `json:"-"`
	Event            string          `json:"hook_event_name"`
	Session          string          `json:"session_id"`
	Turn             string          `json:"turn_id"`
	Prompt           string          `json:"prompt_id"`
	RequestSet       string          `json:"request_set_id"`
	ParentRequestSet string          `json:"parent_request_set_id"`
	PromptText       string          `json:"prompt"`
	Call             string          `json:"tool_use_id"`
	Subagent         string          `json:"agent_id"`
	Tool             string          `json:"tool_name"`
	Cwd              string          `json:"cwd"`
	Model            json.RawMessage `json:"model"`
	Input            json.RawMessage `json:"tool_input"`
	Response         json.RawMessage `json:"tool_response"`
	Error            string          `json:"error"`
	Interrupted      bool            `json:"is_interrupt"`
}

func decodeCommandHook(hook string, raw []byte) (input, error) {
	var in input
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(&in); err != nil {
		return input{}, code("aidr_hook_record_invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || in.Event != hook {
		return input{}, code("aidr_hook_record_invalid")
	}
	return in, nil
}
func validateCommandHook(in input) (input, error) {
	if !validID(in.Session, true) || !validID(in.Turn, false) || !validID(in.Prompt, false) || !validID(in.Call, false) || !validID(in.Subagent, false) || !validID(in.Tool, false) {
		return input{}, code("aidr_hook_identity_invalid")
	}
	return in, nil
}
func standardCommandHook(hook string, raw []byte) (input, error) {
	in, err := decodeCommandHook(hook, raw)
	if err != nil {
		return in, err
	}
	return validateCommandHook(in)
}
func writeCommandDecision(out io.Writer, hook, decision, reason string) error {
	if decision == "deny" {
		return json.NewEncoder(out).Encode(map[string]any{"hookSpecificOutput": map[string]string{"hookEventName": hook, "permissionDecision": "deny", "permissionDecisionReason": reason}})
	}
	return json.NewEncoder(out).Encode(map[string]any{})
}
