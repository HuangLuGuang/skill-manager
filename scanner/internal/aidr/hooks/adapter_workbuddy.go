package hooks

import "skill-manager/scanner/internal/aidr/agentlog"

func workbuddyHookAdapter() hookAdapter {
	return hookAdapter{Decode: standardCommandHook, WriteDecision: writeCommandDecision, ProjectResult: agentlog.ProjectWorkBuddyToolEvidence,
		Settings: &settingsFormat{Path: ".workbuddy/settings.json", Nested: true, Timeout: 60}}
}
