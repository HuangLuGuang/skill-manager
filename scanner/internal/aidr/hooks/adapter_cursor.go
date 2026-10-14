package hooks

import (
	"encoding/json"
	"io"
)

func cursorHookAdapter() hookAdapter {
	return hookAdapter{Decode: func(hook string, raw []byte) (input, error) {
		in, err := decodeCommandHook(hook, raw)
		if err != nil {
			return in, err
		}
		if err = cursorInput(raw, &in); err != nil {
			return in, err
		}
		return validateCommandHook(in)
	}, WriteDecision: writeCursorDecision, WriteInactive: func(out io.Writer, hook string) error { return writeCursorDecision(out, hook, "allow", "") },
		Settings: &settingsFormat{Path: ".cursor/hooks.json", Version: 1, Timeout: 10}}
}
func writeCursorDecision(out io.Writer, hook, decision, reason string) error {
	if IsPreTool("cursor", hook) {
		return json.NewEncoder(out).Encode(map[string]string{"permission": decision, "user_message": reason})
	}
	if hook == "beforeSubmitPrompt" {
		return json.NewEncoder(out).Encode(map[string]bool{"continue": true})
	}
	return writeCommandDecision(out, hook, decision, reason)
}
func cursorInput(raw []byte, in *input) error {
	var c struct {
		WorkspaceRoots []string        `json:"workspace_roots"`
		ModelID        string          `json:"model_id"`
		Conversation   string          `json:"conversation_id"`
		Generation     string          `json:"generation_id"`
		Output         json.RawMessage `json:"tool_output"`
		Error          string          `json:"error_message"`
	}
	if json.Unmarshal(raw, &c) != nil {
		return code("aidr_hook_record_invalid")
	}
	in.Session, in.Turn = c.Conversation, c.Generation
	in.Error = c.Error
	in.WorkspaceRoots = c.WorkspaceRoots
	if c.ModelID != "" {
		in.Model, _ = json.Marshal(c.ModelID)
	}
	in.Response = c.Output
	var output string
	if json.Unmarshal(c.Output, &output) == nil && json.Valid([]byte(output)) {
		in.Response = json.RawMessage(output)
	}
	return nil
}
