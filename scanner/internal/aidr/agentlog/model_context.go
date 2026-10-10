package agentlog

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"os"
)

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
					attachModelContext("codex", line, c, nil)
				}
			}
		}
	}
}

// ModelContext contains only log-recorded identifiers and inference settings.
// Provider is an identifier, not an endpoint or a credential configuration.
type ModelContext struct {
	Model            string `json:"model,omitempty"`
	Provider         string `json:"provider,omitempty"`
	ReasoningEffort  string `json:"reasoning_effort,omitempty"`
	ReasoningSummary string `json:"reasoning_summary,omitempty"`
	Source           string `json:"source"`
}

func modelValue(v string) string {
	if redactValues(v) != v {
		return ""
	}
	return token(v)
}

func (m *ModelContext) empty() bool {
	return m == nil || (m.Model == "" && m.Provider == "" && m.ReasoningEffort == "" && m.ReasoningSummary == "")
}

func (m *ModelContext) valid(agent string) bool {
	if m == nil {
		return true
	}
	if m.empty() {
		return false
	}
	expected := map[string]string{"codex": "codex.turn_context", "claude": "claude.message.model", "qoder-cli": "qoder-cli.message.model", "workbuddy": "workbuddy.providerData.model", "opencode": "opencode.message"}
	if expected[agent] != m.Source {
		return false
	}
	for _, v := range []string{m.Model, m.Provider, m.ReasoningEffort, m.ReasoningSummary} {
		if v != "" && modelValue(v) != v {
			return false
		}
	}
	return true
}

func collectedModel(d draft, policy *AuditPolicy) *ModelContext {
	if policy == nil || policy.ModelContextSchema != 1 || d.ModelContext.empty() {
		return nil
	}
	return d.ModelContext
}

func attachModelContext(agent string, raw []byte, c *Cursor, drafts []draft) {
	var r struct {
		Type    string `json:"type"`
		Message struct {
			Model string `json:"model"`
		} `json:"message"`
		ProviderData struct {
			Model string `json:"model"`
		} `json:"providerData"`
		Payload struct {
			Type     string `json:"type"`
			TurnID   string `json:"turn_id"`
			Model    string `json:"model"`
			Provider string `json:"model_provider"`
			Effort   string `json:"effort"`
			Summary  string `json:"summary"`
		} `json:"payload"`
	}
	if json.Unmarshal(raw, &r) != nil {
		if agent == "codex" && (r.Type == "turn_context" || r.Type == "session_meta") {
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
	var m *ModelContext
	switch agent {
	case "codex":
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
		return
	case "claude", "qoder-cli":
		if r.Type == "assistant" {
			m = &ModelContext{Model: modelValue(r.Message.Model), Source: agent + ".message.model"}
		}
	case "workbuddy":
		m = &ModelContext{Model: modelValue(r.ProviderData.Model), Source: "workbuddy.providerData.model"}
	}
	if !m.empty() {
		for i := range drafts {
			drafts[i].ModelContext = m
		}
	}
}
