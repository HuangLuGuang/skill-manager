package hooks

import (
	"context"
	"encoding/json"
	"io"
	"skill-manager/scanner/internal/aidr/agentlog"
	"time"
)

// Each entry owns host protocol semantics. The receiver, policy evaluator and
// persistent event chain consume only the decoded input and unified decision.
type hookAdapter struct {
	Decode        func(string, []byte) (input, error)
	WriteDecision func(io.Writer, string, string, string) error
	WriteInactive func(io.Writer, string) error
	ProjectResult func(string, string, string, json.RawMessage, string, agentlog.AuditPolicy) (*agentlog.Behavior, error)
	Settings      *settingsFormat
	Plugin        *nativePluginAdapter
	Desktop       *desktopIntegration
}

type desktopIntegration struct {
	Inspect   func(string) (PluginStatus, error)
	Configure func(string, bool) (PluginStatus, error)
}

func DesktopAdapter(agent string) bool { return hookAdapters[agent].Desktop != nil }
func InspectDesktopIntegration(agent, home string) (PluginStatus, error) {
	return hookAdapters[agent].Desktop.Inspect(home)
}
func ConfigureDesktopIntegration(agent, home string, remove bool) (PluginStatus, error) {
	return hookAdapters[agent].Desktop.Configure(home, remove)
}

// Native plugin lifecycle is a separate capability from review transport.
// Its protocol helpers preserve the host's existing installation semantics.
type nativePluginAdapter struct {
	Inspect   func(context.Context, string, string, string) (PluginStatus, error)
	Install   func(context.Context, string, string, string) (PluginStatus, error)
	Update    func(context.Context, string, string, string) (PluginStatus, error)
	Uninstall func(context.Context, string, string, string) (PluginStatus, error)
}

type settingsFormat struct {
	EventsEnvelope bool
	Path           string
	Nested         bool
	Version        int
	Timeout        int
}

var hookAdapters map[string]hookAdapter

func init() {
	hookAdapters = map[string]hookAdapter{
		"zcode":       zcodeHookAdapter(),
		"trae":        traeHookAdapter(".trae"),
		"trae-cn":     traeHookAdapter(".trae-cn"),
		"claude":      claudeHookAdapter(),
		"teleagent":   teleAgentHookAdapter(),
		"codex":       codexHookAdapter(),
		"cursor":      cursorHookAdapter(),
		"workbuddy":   workbuddyHookAdapter(),
		"codebuddy":   codeBuddyHookAdapter(),
		"qwenwork":    qwenWorkHookAdapter(),
		"qoder-hooks": qoderHookAdapter(),
		"qoder-work":  qoderWorkHookAdapter(),
	}
}

func pluginStatus(agent string) PluginStatus {
	return PluginStatus{Agent: agent, HookTrust: "unknown", VersionStatus: "unverified", SourceCode: "aidr_plugin_source_unreadable", SourceKind: "unknown", FilesCode: "aidr_plugin_files_unknown", ReceiverCode: "aidr_hook_receiver_not_checked", ReportedAt: time.Now().UTC().Format(time.RFC3339Nano)}
}

func InspectPlugin(ctx context.Context, agent, binary, home, socket string) (PluginStatus, error) {
	if p := hookAdapters[agent].Plugin; p != nil {
		return p.Inspect(ctx, binary, home, socket)
	}
	return pluginStatus(agent), code("aidr_plugin_config_invalid")
}
func InstallPlugin(ctx context.Context, agent, binary, home, market string) (PluginStatus, error) {
	if p := hookAdapters[agent].Plugin; p != nil {
		return p.Install(ctx, binary, home, market)
	}
	return pluginStatus(agent), code("aidr_plugin_config_invalid")
}
func UpdatePlugin(ctx context.Context, agent, binary, home, market string) (PluginStatus, error) {
	if p := hookAdapters[agent].Plugin; p != nil {
		return p.Update(ctx, binary, home, market)
	}
	return pluginStatus(agent), code("aidr_plugin_config_invalid")
}
func UninstallPlugin(ctx context.Context, agent, binary, home, connection string) (PluginStatus, error) {
	if p := hookAdapters[agent].Plugin; p != nil {
		return p.Uninstall(ctx, binary, home, connection)
	}
	return pluginStatus(agent), code("aidr_plugin_config_invalid")
}

func WriteInactiveHost(out io.Writer, agent, hook string) error {
	a, ok := hookAdapters[agent]
	if !ok {
		return code("aidr_hook_event_unsupported")
	}
	if a.WriteInactive != nil {
		return a.WriteInactive(out, hook)
	}
	return nil
}

func WriteHostDecision(out io.Writer, agent, hook, decision, reason string) error {
	a, ok := hookAdapters[agent]
	if !ok {
		return code("aidr_hook_event_unsupported")
	}
	return a.WriteDecision(out, hook, decision, reason)
}
