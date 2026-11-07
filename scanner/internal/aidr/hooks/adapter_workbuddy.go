package hooks

import (
	"io"
	"runtime"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func workbuddyHookAdapter() hookAdapter {
	return hookAdapter{Decode: standardCommandHook, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		// Windows WorkBuddy can close Stop's output handle after the turn ends.
		if runtime.GOOS == "windows" && hook == "Stop" && decision == "allow" {
			return nil
		}
		return writeCommandDecision(out, hook, decision, reason)
	}, ProjectResult: agentlog.ProjectWorkBuddyToolEvidence,
		Settings: &settingsFormat{Path: ".workbuddy/settings.json", Nested: true, Timeout: 60}}
}
