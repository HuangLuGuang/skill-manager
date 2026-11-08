package hooks

import (
	"encoding/json"
	"io"
	"runtime"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func zcodeHookAdapter() hookAdapter {
	return hookAdapter{Decode: func(hook string, raw []byte) (input, error) {
		in, err := decodeCommandHook(hook, raw)
		if err != nil {
			return in, err
		}
		var native struct{ TurnID string }
		if json.Unmarshal(raw, &native) != nil {
			return in, code("aidr_hook_record_invalid")
		}
		in.Turn = native.TurnID
		return validateCommandHook(in)
	}, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		if runtime.GOOS == "windows" && hook == "PreToolUse" && decision == "deny" {
			return &HostDenied{Reason: reason}
		}
		return writeCommandDecision(out, hook, decision, reason)
	}, ProjectResult: agentlog.ProjectZcodeToolEvidence, Settings: &settingsFormat{Path: ".zcode/cli/config.json", Nested: true, EventsEnvelope: true, Timeout: 60}}
}
