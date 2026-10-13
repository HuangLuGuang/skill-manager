package agentlog

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
	if logAdapters[agent].ModelSource != m.Source {
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
	if f := logAdapters[agent].Model; f != nil {
		f(raw, c, drafts)
	}
}
