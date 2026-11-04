package agentlog

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"
)

const codexContextRepairVersion = 6

func parseCodex(raw []byte, c *Cursor) ([]draft, error) {
	var r logRecord
	if json.Unmarshal(raw, &r) != nil || r.Type == "" {
		return nil, errors.New("aidr_log_invalid_json")
	}
	var drafts []draft
	at, _ := time.Parse(time.RFC3339Nano, r.Timestamp)
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
		case "item_completed":
			var completed struct {
				Thread string `json:"thread_id"`
				Turn   string `json:"turn_id"`
				Item   struct {
					Type     string `json:"type"`
					ID       string `json:"id"`
					Server   string `json:"server"`
					Tool     string `json:"tool"`
					Status   string `json:"status"`
					ExitCode *int32 `json:"exit_code"`
				} `json:"item"`
			}
			if json.Unmarshal(r.Payload, &completed) != nil || completed.Thread != c.Session || token(completed.Turn) == "" || token(completed.Item.ID) == "" {
				return nil, nil
			}
			tool, status := "", ""
			switch completed.Item.Type {
			case "McpToolCall":
				if token(completed.Item.Server) != "" && token(completed.Item.Tool) != "" && (completed.Item.Status == "failed" || completed.Item.Status == "completed") {
					tool, status = "mcp__"+completed.Item.Server+"__"+completed.Item.Tool, completed.Item.Status
				}
			case "ImageView":
				tool, status = "view_image", "completed"
			case "CommandExecution":
				if completed.Item.Status == "failed" || completed.Item.Status == "completed" {
					tool, status = "Bash", completed.Item.Status
				}
			}
			if tool != "" {
				evidence := &ToolCompletion{Source: "codex.item_completed", Status: status}
				if completed.Item.Type == "CommandExecution" {
					evidence.ExitCode = completed.Item.ExitCode
				}
				content, _ := json.Marshal(evidence)
				drafts = append(drafts, draft{Turn: completed.Turn, Call: completed.Item.ID, Kind: "tool_result", Tool: tool, Outcome: "unknown", Content: content, Time: at, Completion: evidence})
			}
		case "token_count", "thread_settings_applied", "user_message", "agent_message", "agent_reasoning", "thread_goal_updated":
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
		case "reasoning", "agent_message", "configuration_update":
		case "additional_tools":
			if !codexToolMetadata(r.Payload) {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
		default:
			return nil, errors.New("aidr_log_schema_unsupported")
		}
	}
	return validateDrafts(drafts)
}

func contextNeutralEnvelope(d *json.Decoder, envelope string) bool {
	tok, err := d.Token()
	if err != nil || tok != json.Delim('{') {
		return false
	}
	var kind string
	for d.More() {
		key, err := d.Token()
		if err != nil {
			return false
		}
		if key == "type" {
			if d.Decode(&kind) != nil {
				return false
			}
			if envelope == "event_msg" {
				return kind == "item_completed"
			}
			if envelope == "response_item" {
				switch kind {
				case "function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output", "message", "agent_message", "reasoning", "additional_tools", "configuration_update":
					return true
				default:
					return false
				}
			}
			if kind != "response_item" && kind != "event_msg" {
				return kind == "compacted" || kind == "world_state" || kind == "token_usage_record" || kind == "inter_agent_communication_metadata"
			}
			continue
		}
		if key == "payload" && (kind == "response_item" || kind == "event_msg") {
			return contextNeutralEnvelope(d, kind)
		}
		var value json.RawMessage
		if d.Decode(&value) != nil {
			return false
		}
	}
	return false
}

func quarantineCodex(raw []byte) (bool, bool) {
	var record map[string]json.RawMessage
	if json.Unmarshal(raw, &record) != nil || record == nil {
		return false, false
	}
	var kind string
	if json.Unmarshal(record["type"], &kind) != nil || kind == "" {
		return false, false
	}
	switch kind {
	case "session_meta", "turn_context", "token_usage_record", "inter_agent_communication_metadata", "world_state", "compacted":
		return false, false
	case "event_msg", "response_item":
		var payload map[string]json.RawMessage
		if json.Unmarshal(record["payload"], &payload) != nil || payload == nil {
			return false, false
		}
		var subtype string
		if json.Unmarshal(payload["type"], &subtype) != nil || subtype == "" {
			return false, false
		}
		if kind == "response_item" {
			switch subtype {
			case "function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output", "reasoning", "message", "agent_message", "additional_tools", "configuration_update":
				return false, false
			}
			return true, true
		}
		switch subtype {
		case "task_started", "item_completed", "token_count", "thread_settings_applied", "task_complete", "turn_aborted", "user_message", "agent_message", "agent_reasoning", "thread_goal_updated":
			return false, false
		}
		// Unknown optional metadata cannot carry identity, tool arguments or outputs.
		// Inspect nested objects as well as the envelope to detect future shapes.
		var value any
		if json.Unmarshal(raw, &value) != nil {
			return false, false
		}
		return true, identityFields(value)
	default:
		return true, true
	}
}

// Tool declarations are metadata, not a session boundary or executed calls.
func codexToolMetadata(raw []byte) bool {
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return false
	}
	for key := range fields {
		switch key {
		case "type", "id", "role", "tools":
		default:
			return false
		}
	}
	var tools []json.RawMessage
	return json.Unmarshal(fields["tools"], &tools) == nil && tools != nil
}

func codexMetadataReplay(f *os.File, s Source, c Cursor) bool {
	if s.Agent != "codex" || c.ContextRepairVersion >= contextRepairVersion {
		return false
	}
	if c.Session == "" {
		for _, gap := range c.Gaps {
			if gap == "aidr_log_record_too_large" {
				return true
			}
		}
	}
	for _, gap := range c.RecoveryGaps {
		if gap.Reason != "aidr_log_context_invalidated" || gap.End <= gap.Start || gap.End-gap.Start > 4<<20 {
			continue
		}
		raw := make([]byte, gap.End-gap.Start)
		if _, err := f.ReadAt(raw, gap.Start); err != nil || digest(string(raw)) != gap.EvidenceDigest {
			continue
		}
		var record logRecord
		var payload item
		if json.Unmarshal(raw, &record) == nil && record.Type == "response_item" && json.Unmarshal(record.Payload, &payload) == nil && payload.Type == "additional_tools" && codexToolMetadata(record.Payload) {
			return true
		}
	}
	return false
}

// Recover metadata on upgrade without replaying events or moving the durable
// cursor. The header and recent native turn must match persisted identities.
func restoreModelProvider(f *os.File, c *Cursor) {
	if c.ModelHeaderRead || c.Offset == 0 || c.Session == "" {
		return
	}
	c.ModelHeaderRead = true
	line, err := bufio.NewReaderSize(io.NewSectionReader(f, 0, 256<<10), 256<<10).ReadBytes('\n')
	if err != nil {
		return
	}
	var header struct {
		Type    string `json:"type"`
		Payload struct {
			ID        string `json:"id"`
			SessionID string `json:"session_id"`
			Provider  string `json:"model_provider"`
		} `json:"payload"`
	}
	if json.Unmarshal(line, &header) != nil || header.Type != "session_meta" {
		return
	}
	id := header.Payload.SessionID
	if id == "" {
		id = header.Payload.ID
	}
	if id == c.Session {
		c.ModelProvider = modelValue(header.Payload.Provider)
		if c.Turn != "" && c.ModelContext == nil {
			start := max(int64(0), c.Offset-(1<<20))
			raw, err := io.ReadAll(io.NewSectionReader(f, start, c.Offset-start))
			if err != nil {
				return
			}
			lines := bytes.Split(raw, []byte{'\n'})
			if start > 0 {
				lines = lines[1:]
			}
			for _, line := range lines {
				var record struct {
					Type    string `json:"type"`
					Payload struct {
						Turn string `json:"turn_id"`
					} `json:"payload"`
				}
				if json.Unmarshal(line, &record) == nil && record.Type == "turn_context" && record.Payload.Turn == c.Turn {
					codexModel(line, c, nil)
				}
			}
		}
	}
}

func codexModel(raw []byte, c *Cursor, drafts []draft) {
	var r modelRecord
	if json.Unmarshal(raw, &r) != nil {
		if r.Type == "turn_context" || r.Type == "session_meta" {
			c.ModelContext, c.ModelTurn = nil, ""
			if r.Type == "session_meta" {
				c.ModelProvider = ""
			}
		}
		return
	}
	if c.Session == "" {
		return
	}
	switch r.Type {
	case "session_meta":
		c.ModelHeaderRead = true
		c.ModelProvider = modelValue(r.Payload.Provider)
		c.ModelContext, c.ModelTurn = nil, ""
	case "turn_context":
		c.ModelTurn = token(r.Payload.TurnID)
		c.ModelContext = &ModelContext{Model: modelValue(r.Payload.Model), Provider: c.ModelProvider, ReasoningEffort: modelValue(r.Payload.Effort), ReasoningSummary: modelValue(r.Payload.Summary), Source: "codex.turn_context"}
	case "event_msg":
		if r.Payload.Type == "task_complete" || r.Payload.Type == "turn_aborted" || (r.Payload.Type == "task_started" && c.ModelTurn != token(r.Payload.TurnID)) {
			c.ModelContext, c.ModelTurn = nil, ""
		}
	}
	for i := range drafts {
		if drafts[i].Turn != "" && drafts[i].Turn == c.ModelTurn {
			drafts[i].ModelContext = c.ModelContext
		}
	}
}

func codexLogAdapter() logAdapter {
	a := lineAdapter(parseCodex)
	a.Model, a.ModelSource, a.DraftTurn = codexModel, "codex.turn_context", true
	a.Restore = restoreModelProvider
	a.PreservesContext = func(raw []byte) bool { return contextNeutralEnvelope(json.NewDecoder(bytes.NewReader(raw)), "") }
	a.Quarantine = quarantineCodex
	a.Repair = func(c Cursor) bool {
		if c.ContextRepairVersion >= codexContextRepairVersion || c.Offset == 0 || c.Session != "" {
			return false
		}
		for _, gap := range c.Gaps {
			if gap == "aidr_log_context_invalidated" || (c.ContextRepairVersion < contextRepairVersion && gap == "aidr_log_record_too_large") {
				return true
			}
		}
		return false
	}
	a.Roots = func(home string) []string {
		base := os.Getenv("CODEX_HOME")
		if base == "" {
			base = filepath.Join(home, ".codex")
		}
		return []string{filepath.Join(base, "sessions")}
	}

	return a
}
