package hooks

import (
	"encoding/json"
	"io"
	"skill-manager/scanner/internal/aidr/agentlog"
)

func codeBuddyHookAdapter() hookAdapter {
	return hookAdapter{Decode: func(hook string, raw []byte) (input, error) {
		in, err := decodeCommandHook(hook, raw)
		if err != nil {
			return in, err
		}
		var native struct {
			Generation string `json:"generation_id"`
		}
		if json.Unmarshal(raw, &native) != nil {
			return in, code("aidr_hook_record_invalid")
		}
		in.Turn = native.Generation
		in.Tool = agentlog.CodeBuddyToolName(in.Tool, in.Input)
		// IDE 4.12.2 sends its process root for tool hooks, not the workspace.
		if in.Cwd == "/" {
			in.Cwd = ""
		}
		in.ProjectionInput = agentlog.NormalizeCodeBuddyInput(in.Input)
		return validateCommandHook(in)
	}, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		if decision == "deny" {
			return json.NewEncoder(out).Encode(map[string]any{"continue": false, "hookSpecificOutput": map[string]string{"hookEventName": hook, "permissionDecision": "deny", "permissionDecisionReason": reason}})
		}
		return json.NewEncoder(out).Encode(map[string]any{})
	}, ProjectResult: agentlog.ProjectCodeBuddyToolEvidence,
		Settings: &settingsFormat{Path: ".codebuddy/settings.json", Nested: true, Timeout: 60}}
}
