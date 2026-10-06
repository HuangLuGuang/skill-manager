package agentlog

import (
	"encoding/json"
	"errors"
)

// ProjectToolEvidence applies the same field boundaries and audit policy as log
// ingestion before a hook receiver persists anything. The caller retains source
// provenance; this projection does not establish a system outcome.
func ProjectToolEvidence(tool, kind, cwd string, content, resultMeta json.RawMessage, outcome string, policy AuditPolicy) (*Behavior, error) {
	if !policy.Valid() || (kind != "tool_call" && kind != "tool_result") || (outcome != "unknown" && outcome != "success" && outcome != "error") {
		return nil, errors.New("aidr_hook_projection_invalid")
	}
	if len(content) > 256<<10 || len(resultMeta) > 256<<10 {
		return nil, errors.New("aidr_hook_record_oversized")
	}
	b := projectBehaviorPolicy(draft{Tool: tool, Kind: kind, Cwd: cwd, Content: content, ResultMeta: resultMeta, Outcome: outcome, HookResult: kind == "tool_result"}, 3, &policy)
	if err := validateBehavior(b); err != nil {
		return nil, err
	}
	return b, nil
}
