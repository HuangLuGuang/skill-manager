package agentlog

import (
	"bytes"
	"encoding/json"
	"errors"
	"regexp"
	"time"
)

var tokenPattern = regexp.MustCompile(`^[A-Za-z0-9_.:/@+-]{1,256}$`)

func token(s string) string {
	if tokenPattern.MatchString(s) {
		return s
	}
	return ""
}
func canonical(raw json.RawMessage) string {
	var value any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if d.Decode(&value) != nil {
		return string(raw)
	}
	b, _ := json.Marshal(value)
	return string(b)
}

type draft struct {
	MessageRole, MessagePhase string
	HookResult                bool
	WorkBuddyResult           bool
	ResultTool                string
	Turn                      string
	Cwd                       string
	ResultMeta                json.RawMessage
	Call, Kind, Tool, Outcome string
	Content                   json.RawMessage
	Time                      time.Time
	Block                     int
}
type logRecord struct {
	UUID       string          `json:"uuid"`
	APIError   bool            `json:"isApiErrorMessage"`
	Cwd        string          `json:"cwd"`
	ResultMeta json.RawMessage `json:"toolUseResult"`
	Type       string          `json:"type"`
	Timestamp  string          `json:"timestamp"`
	Session    string          `json:"sessionId"`
	Version    string          `json:"version"`
	Payload    json.RawMessage `json:"payload"`
	Message    struct {
		Content    json.RawMessage `json:"content"`
		ID         string          `json:"id"`
		Model      string          `json:"model"`
		StopReason string          `json:"stop_reason"`
	} `json:"message"`
}
type item struct {
	Role      string          `json:"role"`
	Phase     string          `json:"phase"`
	Type      string          `json:"type"`
	ID        string          `json:"id"`
	SessionID string          `json:"session_id"`
	TurnID    string          `json:"turn_id"`
	Version   string          `json:"cli_version"`
	CallID    string          `json:"call_id"`
	ToolUseID string          `json:"tool_use_id"`
	Name      string          `json:"name"`
	Input     json.RawMessage `json:"input"`
	Arguments json.RawMessage `json:"arguments"`
	Output    json.RawMessage `json:"output"`
	Content   json.RawMessage `json:"content"`
	IsError   *bool           `json:"is_error"`
}

func normalize(agent string, raw []byte, c *Cursor) ([]draft, error) {
	switch agent {
	case "workbuddy":
		return normalizeWorkBuddy(raw, c)
	case "qoder-cli":
		return normalizeQoder(raw, c)
	case "claude", "codex":
		return normalizeLegacy(agent, raw, c)
	default:
		return nil, errors.New("aidr_log_agent_unsupported")
	}
}

func normalizeLegacy(agent string, raw []byte, c *Cursor) ([]draft, error) {
	var r logRecord
	if json.Unmarshal(raw, &r) != nil || r.Type == "" {
		return nil, errors.New("aidr_log_invalid_json")
	}
	var drafts []draft
	at, _ := time.Parse(time.RFC3339Nano, r.Timestamp)
	if agent == "claude" {
		if r.Session != "" {
			if token(r.Session) == "" {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			if c.Session != r.Session {
				c.CallTurns = nil
			}
			c.Session = r.Session
		}
		if r.Version != "" {
			if len(r.Version) > 80 || token(r.Version) == "" {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			c.AgentVersion = r.Version
		}
		switch r.Type {
		case "assistant", "user":
			if !r.APIError && r.Message.Model != "<synthetic>" {
				phase := "unspecified"
				if r.Type == "assistant" {
					if r.Message.StopReason == "end_turn" {
						phase = "final"
					} else if r.Message.StopReason == "tool_use" {
						phase = "commentary"
					}
				}
				if d, ok := messageDraft(r.Type, phase, r.UUID, "", r.Message.Content, at); ok {
					drafts = append(drafts, d)
				}
			}
			var contents []item
			if len(r.Message.Content) == 0 {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			if bytes.HasPrefix(bytes.TrimSpace(r.Message.Content), []byte(`"`)) {
				return drafts, nil
			}
			if json.Unmarshal(r.Message.Content, &contents) != nil {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			for i, v := range contents {
				switch v.Type {
				case "tool_use":
					rememberTool(c, v.ID, "", v.Name, v.Input)
					drafts = append(drafts, draft{Call: v.ID, Kind: "tool_call", Tool: v.Name, Cwd: r.Cwd, Outcome: "unknown", Content: v.Input, Time: at, Block: i})
				case "tool_result":
					outcome := "unknown"
					if v.IsError != nil {
						if *v.IsError {
							outcome = "error"
						} else {
							outcome = "success"
						}
					}
					meta := json.RawMessage(nil)
					if len(contents) == 1 {
						meta = r.ResultMeta
					}
					_, resultTool := completeTool(c, v.ToolUseID, "")
					drafts = append(drafts, draft{ResultMeta: meta, Call: v.ToolUseID, ResultTool: resultTool, Kind: "tool_result", Outcome: outcome, Content: v.Content, Time: at, Block: i})
				case "text", "thinking", "redacted_thinking", "image":
				default:
					return nil, errors.New("aidr_log_schema_unsupported")
				}
			}
		case "system", "attachment", "file-history-snapshot", "file-history-delta", "mode", "permission-mode", "last-prompt", "ai-title", "queue-operation", "progress", "summary":
		default:
			return nil, errors.New("aidr_log_schema_unsupported")
		}
	} else {
		var v item
		switch r.Type {
		case "session_meta", "turn_context", "event_msg", "response_item":
			if json.Unmarshal(r.Payload, &v) != nil {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
		case "token_usage_record", "inter_agent_communication_metadata", "world_state", "compacted":
			return nil, nil
		default:
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		switch r.Type {
		case "session_meta":
			if v.SessionID == "" {
				v.SessionID = v.ID
			}
			if token(v.SessionID) == "" || len(v.Version) > 80 || token(v.Version) == "" {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			if c.Session != v.SessionID {
				c.Turn = ""
				c.CallTurns = nil
			}
			c.Session = v.SessionID
			c.AgentVersion = v.Version
		case "turn_context":
			if v.TurnID != "" && token(v.TurnID) == "" {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			c.Turn = v.TurnID
		case "event_msg":
			switch v.Type {
			case "task_started":
				c.Turn = token(v.TurnID)
			case "task_complete", "turn_aborted":
				c.Turn = ""
			case "item_completed", "token_count", "thread_settings_applied", "user_message", "agent_message", "agent_reasoning", "thread_goal_updated":
			default:
				return nil, errors.New("aidr_log_schema_unsupported")
			}
		case "response_item":
			switch v.Type {
			case "function_call", "custom_tool_call":
				content := v.Arguments
				if v.Type == "custom_tool_call" {
					content = v.Input
				}
				rememberTool(c, v.CallID, c.Turn, v.Name, content)
				drafts = append(drafts, draft{Turn: c.Turn, Call: v.CallID, Kind: "tool_call", Tool: v.Name, Outcome: "unknown", Content: content, Time: at})
			case "function_call_output", "custom_tool_call_output":
				turn, resultTool := completeTool(c, v.CallID, token(v.TurnID))
				drafts = append(drafts, draft{Turn: turn, Call: v.CallID, ResultTool: resultTool, Kind: "tool_result", Outcome: "unknown", Content: v.Output, Time: at})
			case "message":
				phase := "unspecified"
				if v.Phase == "final_answer" {
					phase = "final"
				} else if v.Phase == "commentary" {
					phase = "commentary"
				}
				if d, ok := messageDraft(v.Role, phase, v.ID, c.Turn, v.Content, at); ok {
					drafts = append(drafts, d)
				}
			case "reasoning", "agent_message":
			default:
				return nil, errors.New("aidr_log_schema_unsupported")
			}
		}
	}
	for _, d := range drafts {
		if token(d.Call) == "" || (d.Kind == "tool_call" && token(d.Tool) == "") || len(d.Content) == 0 || d.Time.IsZero() {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
	}
	return drafts, nil
}

// Pending calls survive read budgets and persisted cursors. Completed entries are
// a bounded replay/conflict cache; capacity never evicts an unfinished call.
const maxToolBindings = 512
const completedToolBindings = 64

func rememberTool(c *Cursor, call, turn, tool string, content json.RawMessage) {
	c.CallTurns = append([]CallTurn(nil), c.CallTurns...)
	signature := digest(canonical(content))
	for i := range c.CallTurns {
		binding := &c.CallTurns[i]
		if binding.Call == call {
			if binding.Turn != turn || (binding.Tool != "" && binding.Tool != tool) || (binding.ContentDigest != "" && binding.ContentDigest != signature) {
				binding.Ambiguous = true
				addGap(c, "aidr_log_call_conflict")
			}
			if !binding.Ambiguous {
				binding.Tool = tool
				binding.ContentDigest = signature
			}
			return
		}
	}
	pruneCompletedTools(c, completedToolBindings)
	if len(c.CallTurns) >= maxToolBindings {
		pruneCompletedTools(c, 0)
	}
	if len(c.CallTurns) >= maxToolBindings {
		addGap(c, "aidr_log_call_capacity")
		return
	}
	c.CallTurns = append(c.CallTurns, CallTurn{Call: call, Turn: turn, Tool: tool, ContentDigest: signature})
}

func pruneCompletedTools(c *Cursor, keep int) {
	completed := 0
	for _, binding := range c.CallTurns {
		if binding.Completed {
			completed++
		}
	}
	retained := make([]CallTurn, 0, len(c.CallTurns))
	for _, binding := range c.CallTurns {
		if binding.Completed && completed > keep {
			completed--
			continue
		}
		retained = append(retained, binding)
	}
	c.CallTurns = retained
}

func completeTool(c *Cursor, call, turn string) (string, string) {
	c.CallTurns = append([]CallTurn(nil), c.CallTurns...)
	for i := range c.CallTurns {
		binding := &c.CallTurns[i]
		if binding.Call != call {
			continue
		}
		if binding.Ambiguous || (turn != "" && turn != binding.Turn) {
			addGap(c, "aidr_log_call_conflict")
			return turn, ""
		}
		binding.Completed = true
		resolvedTurn, tool := binding.Turn, binding.Tool
		pruneCompletedTools(c, completedToolBindings)
		return resolvedTurn, tool
	}
	addGap(c, "aidr_log_call_unresolved")
	return turn, ""
}

func boundTool(c *Cursor, call string) string {
	for _, binding := range c.CallTurns {
		if binding.Call == call && !binding.Ambiguous {
			return binding.Tool
		}
	}
	return ""
}
