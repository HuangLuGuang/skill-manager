package agentlog

import "encoding/json"

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
