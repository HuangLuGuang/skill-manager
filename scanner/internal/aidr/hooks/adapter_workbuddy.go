package hooks

import (
	"io"
	"runtime"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func workbuddyHookAdapter() hookAdapter {
	return hookAdapter{Decode: standardCommandHook, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		// WorkBuddy accepts exit status alone on success; its output handle may already be closed.
		if runtime.GOOS == "windows" && decision == "allow" {
			return nil
		}
		return writeCommandDecision(out, hook, decision, reason)
	}, ProjectResult: agentlog.ProjectWorkBuddyToolEvidence,
		Settings: &settingsFormat{Path: ".workbuddy/settings.json", Nested: true, Timeout: 60}}
}
