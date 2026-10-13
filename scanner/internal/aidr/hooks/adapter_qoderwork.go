package hooks

import "io"

func qoderWorkHookAdapter() hookAdapter {
	return hookAdapter{Decode: standardCommandHook, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		if decision == "deny" && IsPreTool("qoder-work", hook) {
			return &HostDenied{Reason: reason}
		}
		return writeCommandDecision(out, hook, decision, reason)
	}, Settings: &settingsFormat{Path: ".qoderwork/settings.json", Nested: true, Timeout: 60}}
}

// QoderWork uses exit status 2 for execution denial.
type HostDenied struct{ Reason string }

func (e *HostDenied) Error() string { return e.Reason }
func (e *HostDenied) ExitCode() int { return 2 }
