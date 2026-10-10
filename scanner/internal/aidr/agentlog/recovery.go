package agentlog

import (
	"bytes"
	"encoding/json"
	"strings"
)

const contextRepairVersion = 3

func needsContextRepair(s Source, c Cursor) bool {
	if s.Agent == "qoder-cli" {
		return c.Offset > 0 && c.ContextRepairVersion < contextRepairVersion
	}
	if s.Agent != "codex" || c.ContextRepairVersion >= contextRepairVersion || c.Offset == 0 || c.Session != "" {
		return false
	}
	for _, gap := range c.Gaps {
		if gap == "aidr_log_record_too_large" {
			return true
		}
	}
	return false
}

// The envelope of these Codex records never updates session/turn identity.
// Inspect JSON tokens, not text in their (possibly truncated) payload bodies.
func oversizedPreservesContext(agent string, prefix []byte) bool {
	if agent != "codex" {
		return false
	}
	d := json.NewDecoder(bytes.NewReader(prefix))
	return contextNeutralEnvelope(d, false)
}

func contextNeutralEnvelope(d *json.Decoder, response bool) bool {
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
			if response {
				switch kind {
				case "function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output", "message", "agent_message", "reasoning":
					return true
				default:
					return false
				}
			}
			if kind != "response_item" {
				return kind == "compacted" || kind == "world_state" || kind == "token_usage_record" || kind == "inter_agent_communication_metadata"
			}
			continue
		}
		if key == "payload" && kind == "response_item" {
			return contextNeutralEnvelope(d, true)
		}
		var value json.RawMessage
		if d.Decode(&value) != nil {
			return false
		}
	}
	return false
}

// Only syntactically valid unknown variants are quarantined. A recognized
// identity/tool record with invalid fields remains at its checkpoint for repair.
func quarantineUnknown(agent string, raw []byte) (skip, invalidate bool) {
	var record map[string]json.RawMessage
	if json.Unmarshal(raw, &record) != nil || record == nil {
		return false, false
	}
	var kind string
	if json.Unmarshal(record["type"], &kind) != nil || kind == "" {
		return false, false
	}
	if agent == "claude" {
		switch kind {
		case "assistant", "user", "system", "attachment", "file-history-snapshot", "file-history-delta", "mode", "permission-mode", "last-prompt", "ai-title", "queue-operation", "progress", "summary":
			return false, false
		default:
			return true, true
		}
	}
	if agent == "workbuddy" || agent == "qoder-cli" {
		// Unknown identity-bearing variants require explicit adapter support.
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
			case "function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output", "reasoning", "message", "agent_message":
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

func identityFields(value any) bool {
	switch v := value.(type) {
	case map[string]any:
		for key, child := range v {
			switch strings.ToLower(strings.NewReplacer("_", "", "-", "").Replace(key)) {
			case "id", "session", "sessionid", "turn", "turnid", "thread", "threadid", "call", "callid", "tooluseid", "tool", "name", "arguments", "input", "output", "message", "content", "cliversion", "version":
				return true
			}
			if identityFields(child) {
				return true
			}
		}
	case []any:
		for _, child := range v {
			if identityFields(child) {
				return true
			}
		}
	}
	return false
}

func invalidateContext(c *Cursor) {
	c.ModelContext, c.ModelProvider, c.ModelTurn = nil, "", ""
	c.Session = ""
	c.Turn = ""
	c.CallTurns = nil
	c.QoderLinks = nil
	addGap(c, "aidr_log_context_invalidated")
}

func rememberRecovery(c *Cursor, start, end int64, reason string, raw []byte) {
	addGap(c, reason)
	c.RecoveryGaps = append([]Gap(nil), c.RecoveryGaps...)
	if len(c.RecoveryGaps) < 32 {
		c.RecoveryGaps = append(c.RecoveryGaps, Gap{Start: start, End: end, Reason: reason, EvidenceDigest: digest(string(raw))})
	} else {
		c.RecoveryDetailsTruncated = true
	}
}
