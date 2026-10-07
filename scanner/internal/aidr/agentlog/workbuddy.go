package agentlog

import (
	"encoding/json"
	"errors"
	"time"
)

// WorkBuddy desktop 5.6.2 persists response items, not Claude message envelopes.
// Completion of a persisted item does not establish a tool's execution outcome
// or whether an assistant reply is the final reply of a turn.
func normalizeWorkBuddy(raw []byte, c *Cursor) ([]draft, error) {
	var r struct {
		Type, ID, SessionID, Role, CallID, Name, Arguments, Cwd string
		Timestamp                                               int64
		Content, Output                                         json.RawMessage
		ProviderData                                            struct {
			ToolResult struct {
				RawResponse json.RawMessage `json:"rawResponse"`
			} `json:"toolResult"`
		} `json:"providerData"`
	}
	if json.Unmarshal(raw, &r) != nil || r.Type == "" {
		return nil, errors.New("aidr_log_invalid_json")
	}
	switch r.Type {
	case "session-meta", "message", "function_call", "function_call_result":
		if token(r.SessionID) == "" {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		if c.Session != r.SessionID {
			c.CallTurns = nil
			c.Turn = ""
		}
		c.Session = r.SessionID
	case "reasoning", "file-history-snapshot", "resend-fork-notice", "ai-title":
		return nil, nil
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	at := time.UnixMilli(r.Timestamp).UTC()
	if r.Type == "session-meta" {
		return nil, nil
	}
	if r.Timestamp <= 0 {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	switch r.Type {
	case "message":
		if token(r.ID) == "" {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		if d, ok := messageDraft(r.Role, "unspecified", r.ID, "", r.Content, at); ok {
			return []draft{d}, nil
		}
	case "function_call", "function_call_result":
		if token(r.CallID) == "" || token(r.Name) == "" {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		if r.Type == "function_call" {
			input := json.RawMessage(r.Arguments)
			if !json.Valid(input) {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			rememberTool(c, r.CallID, "", r.Name, input)
			return []draft{{Call: r.CallID, Kind: "tool_call", Tool: r.Name, Cwd: r.Cwd, Content: input, Outcome: "unknown", Time: at}}, nil
		}
		// The native result may be one text block or an array of blocks.
		content := r.Output
		var block struct{ Type, Text string }
		if json.Unmarshal(content, &block) == nil && block.Type == "text" {
			content, _ = json.Marshal(block.Text)
		}
		completeTool(c, r.CallID, "")
		return []draft{{Call: r.CallID, Kind: "tool_result", ResultTool: r.Name, Content: content, ResultMeta: r.ProviderData.ToolResult.RawResponse, WorkBuddyResult: true, Outcome: "unknown", Time: at}}, nil
	}
	return nil, nil
}
