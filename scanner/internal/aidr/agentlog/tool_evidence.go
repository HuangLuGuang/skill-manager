package agentlog

import (
	"encoding/json"
	"errors"
)

// ProjectToolEvidence applies the same field boundaries and audit policy as log
// ingestion before a hook receiver persists anything. The caller retains source
// provenance; this projection does not establish a system outcome.
func ProjectToolEvidence(tool, kind, cwd string, content, resultMeta json.RawMessage, outcome string, policy AuditPolicy) (*Behavior, error) {
	return projectToolEvidence(tool, kind, cwd, content, resultMeta, outcome, policy, false)
}

// WorkBuddy sends the native rawResponse as tool_response. Its text output is
// a separate log field and must not be interpreted as structured result data.
func ProjectWorkBuddyToolEvidence(tool, kind, cwd string, content json.RawMessage, outcome string, policy AuditPolicy) (*Behavior, error) {
	meta := content
	var obj map[string]json.RawMessage
	if json.Unmarshal(content, &obj) == nil {
		for _, field := range []string{"content", "error"} {
			var text string
			if json.Unmarshal(obj[field], &text) == nil && text != "" {
				content = obj[field]
				break
			}
		}
	}
	return projectToolEvidence(tool, kind, cwd, content, meta, outcome, policy, kind == "tool_result")
}

func projectToolEvidence(tool, kind, cwd string, content, resultMeta json.RawMessage, outcome string, policy AuditPolicy, workBuddy bool) (*Behavior, error) {
	if !policy.Valid() || (kind != "tool_call" && kind != "tool_result") || (outcome != "unknown" && outcome != "success" && outcome != "error") {
		return nil, errors.New("aidr_hook_projection_invalid")
	}
	if len(content) > 256<<10 || len(resultMeta) > 256<<10 {
		return nil, errors.New("aidr_hook_record_oversized")
	}
	b := projectBehaviorPolicy(draft{Tool: tool, Kind: kind, Cwd: cwd, Content: content, ResultMeta: resultMeta, Outcome: outcome, HookResult: kind == "tool_result", WorkBuddyResult: workBuddy}, 3, &policy)
	if err := validateBehavior(b); err != nil {
		return nil, err
	}
	return b, nil
}
