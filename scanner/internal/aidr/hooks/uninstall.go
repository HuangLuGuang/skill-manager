package hooks

import "context"

// UninstallPlugin uses the host's user-scope removal command and verifies the
// resulting inventory. The bridge binds ownership to this device connection.
func UninstallPlugin(ctx context.Context, agent, binary, home, connection string) (PluginStatus, error) {
	before, err := InspectPlugin(ctx, agent, binary, home, "")
	if err != nil {
		return before, err
	}
	if before.Installed == nil {
		return before, code("aidr_plugin_source_unreadable")
	}
	if !*before.Installed {
		return before, nil
	}
	if before.PluginID != "aidr-"+agent+"@aidr-local" || !PluginBridgeMatches(before, connection) {
		return before, code("aidr_desktop_manual_migration_required")
	}
	args := []string{"plugin", "remove", before.PluginID}
	if agent == "claude" {
		args = []string{"plugin", "uninstall", before.PluginID, "--scope", "user"}
	}
	if _, err = hostCommand(ctx, binary, agent, home, args...); err != nil {
		return before, code("aidr_plugin_remove_failed")
	}
	after, err := InspectPlugin(ctx, agent, binary, home, "")
	if err != nil || after.Installed == nil || *after.Installed {
		return after, code("aidr_plugin_remove_not_applied")
	}
	return after, nil
}
