package agentlog

import (
	"encoding/json"
	"errors"
	"strings"
	"time"
)

// Message is text retained by an Agent, not a complete model API request.
type Message struct {
	Role          string      `json:"role"`
	Phase         string      `json:"phase"`
	Policy        AuditPolicy `json:"policy"`
	Contents      []Content   `json:"contents"`
	ContentStatus string      `json:"content_status"`
}

func messageDraft(role, phase, id, turn string, raw json.RawMessage, at time.Time) (draft, bool) {
	if role != "user" && role != "assistant" {
		return draft{}, false
	}
	block := 0
	var text string
	if json.Unmarshal(raw, &text) != nil {
		var blocks []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		}
		if json.Unmarshal(raw, &blocks) != nil {
			return draft{}, false
		}
		var parts []string
		for i, b := range blocks {
			if contentAllowed(b.Type, "text|input_text|output_text") && b.Text != "" {
				if len(parts) == 0 {
					block = i
				}
				parts = append(parts, b.Text)
			}
		}
		text = strings.Join(parts, "\n")
	}
	if text == "" {
		return draft{}, false
	}
	if token(id) == "" || len(id) > 240 {
		id = digest(role, at.UTC().Format(time.RFC3339Nano), text)
	}
	if role == "user" {
		phase = "unspecified"
	}
	content, _ := json.Marshal(text)
	return draft{Block: block, Call: "message:" + id, Turn: turn, Kind: role + "_message", Outcome: "unknown", Content: content, Time: at, MessageRole: role, MessagePhase: phase}, true
}

func projectMessage(d draft, p AuditPolicy) *Message {
	m := &Message{Role: d.MessageRole, Phase: d.MessagePhase, Policy: p, Contents: []Content{}, ContentStatus: "not_requested"}
	if !p.CollectionEnabled() || p.Capture == nil {
		return m
	}
	kind, field, enabled := "prompt", "message.input", p.Capture.Prompt
	if m.Role == "assistant" {
		kind, field, enabled = "model_response", "message.output", p.Capture.ModelResponse
	}
	if enabled {
		c := contentBuilder{policy: p}
		c.add(kind, field, 0, rawString(d.Content))
		m.Contents, m.ContentStatus = c.result(true)
	}
	return m
}

func validateMessage(m *Message, kind string) error {
	if m.Policy.MessageSchema != 1 || kind != m.Role+"_message" || !contentAllowed(m.Role, "user|assistant") || !contentAllowed(m.Phase, "unspecified|commentary|final") || (m.Role == "user" && m.Phase != "unspecified") || !m.Policy.CollectionEnabled() {
		return errors.New("aidr_log_message_invalid")
	}
	for _, c := range m.Contents {
		if (m.Role == "user" && (c.Kind != "prompt" || c.Field != "message.input")) || (m.Role == "assistant" && (c.Kind != "model_response" || c.Field != "message.output")) {
			return errors.New("aidr_log_message_invalid")
		}
	}
	return validateContents(m.Contents, m.ContentStatus, m.Policy)
}
