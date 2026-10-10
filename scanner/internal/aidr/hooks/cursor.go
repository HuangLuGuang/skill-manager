package hooks

import (
	"encoding/json"
	"io"
	products "skill-manager/scanner/internal/aidr/catalog"
)

func IsPreTool(agent, event string) bool { return products.Kind(agent, event) == "tool.pre" }

func WriteInactiveHost(out io.Writer, agent, hook string) error {
	if agent == "cursor" {
		return WriteHostDecision(out, agent, hook, "allow", "")
	}
	return nil
}

// Cursor's permission hooks require a schema-valid allow response even in
// audit mode. An empty object can deny an otherwise ordinary tool operation.
func WriteHostDecision(out io.Writer, agent, hook, decision, reason string) error {
	if agent == "cursor" {
		if IsPreTool(agent, hook) {
			return json.NewEncoder(out).Encode(map[string]string{"permission": decision, "user_message": reason})
		}
		if hook == "beforeSubmitPrompt" {
			return json.NewEncoder(out).Encode(map[string]bool{"continue": true})
		}
	}
	if decision == "deny" && agent == "qoder-work" && IsPreTool(agent, hook) {
		return &HostDenied{Reason: reason}
	}
	if decision == "deny" {
		return json.NewEncoder(out).Encode(map[string]any{"hookSpecificOutput": map[string]string{"hookEventName": hook, "permissionDecision": "deny", "permissionDecisionReason": reason}})
	}
	return json.NewEncoder(out).Encode(map[string]any{})
}

func cursorInput(raw []byte, in *input) error {
	var c struct {
		Conversation string          `json:"conversation_id"`
		Generation   string          `json:"generation_id"`
		Output       json.RawMessage `json:"tool_output"`
		Error        string          `json:"error_message"`
	}
	if json.Unmarshal(raw, &c) != nil {
		return code("aidr_hook_record_invalid")
	}
	in.Session, in.Turn = c.Conversation, c.Generation
	in.Error = c.Error
	in.Response = c.Output
	var output string
	if json.Unmarshal(c.Output, &output) == nil && json.Valid([]byte(output)) {
		in.Response = json.RawMessage(output)
	}
	return nil
}

// QoderWork documents exit 2 for PreToolUse denial, not a permission JSON.
type HostDenied struct{ Reason string }

func (e *HostDenied) Error() string { return e.Reason }
func (e *HostDenied) ExitCode() int { return 2 }
