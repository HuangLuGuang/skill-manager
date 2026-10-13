package agentlog

import (
	"bytes"
	"encoding/json"
	"errors"
	"time"
)

func parseTranscriptBlocks(raw []byte, c *Cursor, nativeTurn string) ([]draft, error) {
	var r logRecord
	if json.Unmarshal(raw, &r) != nil || r.Type == "" {
		return nil, errors.New("aidr_log_invalid_json")
	}
	var drafts []draft
	at, _ := time.Parse(time.RFC3339Nano, r.Timestamp)
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
				rememberTool(c, v.ID, nativeTurn, v.Name, v.Input)
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
				resultTurn, resultTool := completeTool(c, v.ToolUseID, nativeTurn)
				drafts = append(drafts, draft{Turn: resultTurn, ResultMeta: meta, Call: v.ToolUseID, ResultTool: resultTool, Kind: "tool_result", Outcome: outcome, Content: v.Content, Time: at, Block: i})
			case "text", "thinking", "redacted_thinking", "image":
			default:
				return nil, errors.New("aidr_log_schema_unsupported")
			}
		}
	case "system", "attachment", "file-history-snapshot", "file-history-delta", "mode", "permission-mode", "last-prompt", "ai-title", "queue-operation", "progress", "summary":
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	return validateDrafts(drafts)
}

func messageModel(source string) func([]byte, *Cursor, []draft) {
	return func(raw []byte, c *Cursor, drafts []draft) {
		var r modelRecord
		if json.Unmarshal(raw, &r) != nil || c.Session == "" || r.Type != "assistant" {
			return
		}
		assignModel(drafts, &ModelContext{Model: modelValue(r.Message.Model), Source: source})
	}
}
func assignModel(drafts []draft, m *ModelContext) {
	if !m.empty() {
		for i := range drafts {
			drafts[i].ModelContext = m
		}
	}
}
func transcriptSkillField(tool string) string {
	if tool == "Skill" {
		return "skill"
	}
	return ""
}
