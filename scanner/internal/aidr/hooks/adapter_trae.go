package hooks

import (
	"encoding/json"
	"io"
	"runtime"
)

func traeHookAdapter(root string) hookAdapter {
	return hookAdapter{Decode: func(hook string, raw []byte) (input, error) {
		in, err := standardCommandHook(hook, raw)
		if err != nil {
			return in, err
		}
		var native struct {
			Roots []string `json:"workspace_roots"`
		}
		if err := json.Unmarshal(raw, &native); err != nil {
			return in, code("aidr_hook_record_invalid")
		}
		in.WorkspaceRoots = native.Roots
		return in, nil
	}, WriteDecision: writeTraeDecision,
		Settings: &settingsFormat{Path: root + "/hooks.json", Nested: true, Version: 1, Timeout: 60}}
}

func writeTraeDecision(out io.Writer, hook, decision, reason string) error {
	if runtime.GOOS == "windows" && hook == "PreToolUse" && decision == "deny" {
		return &HostDenied{Reason: reason}
	}
	if decision == "ask" {
		return json.NewEncoder(out).Encode(map[string]any{"hookSpecificOutput": map[string]string{"hookEventName": hook, "permissionDecision": decision, "permissionDecisionReason": reason}})
	}
	return writeCommandDecision(out, hook, decision, reason)
}
