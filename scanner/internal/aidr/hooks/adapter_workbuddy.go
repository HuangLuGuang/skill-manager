package hooks

import (
	"io"
	"runtime"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func workbuddyHookAdapter() hookAdapter {
	return hookAdapter{Decode: standardCommandHook, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		// The Windows host can close stdout before the bridge writes its decision.
		if runtime.GOOS == "windows" {
			if hook == "PreToolUse" && decision == "deny" {
				return &HostDenied{Reason: reason}
			}
			return nil
		}
		return writeCommandDecision(out, hook, decision, reason)
	}, ProjectResult: agentlog.ProjectWorkBuddyToolEvidence,
		Settings: &settingsFormat{Path: ".workbuddy/settings.json", Nested: true, Timeout: 60}}
}
