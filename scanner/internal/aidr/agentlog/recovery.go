package agentlog

import (
	"strings"
)

const contextRepairVersion = 5

func needsContextRepair(s Source, c Cursor) bool {
	f := logAdapters[s.Agent].Repair
	return f != nil && f(c)
}
func oversizedPreservesContext(agent string, prefix []byte) bool {
	f := logAdapters[agent].PreservesContext
	return f != nil && f(prefix)
}

// Only syntactically valid unknown variants are quarantined. A recognized
// identity/tool record with invalid fields remains at its checkpoint for repair.
func quarantineUnknown(agent string, raw []byte) (bool, bool) {
	if f := logAdapters[agent].Quarantine; f != nil {
		return f(raw)
	}
	return false, false
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
