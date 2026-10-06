package hooks

import (
	"context"
	"path/filepath"
)

// UpdatePlugin changes only the product marketplace and plugin, through native
// commands. Packages are immutable; replacing the marketplace does not rewrite
// the package used by an already running Agent session.
func UpdatePlugin(ctx context.Context, agent, binary, home, market string) (PluginStatus, error) {
	before, err := InspectPlugin(ctx, agent, binary, home, "")
	if err != nil {
		return before, err
	}
	if before.VersionStatus != "adapter_target" {
		return before, code("aidr_plugin_version_unverified")
	}
	if before.Installed == nil || before.Enabled == nil {
		return before, code("aidr_plugin_source_unreadable")
	}
	if !*before.Installed {
		return InstallPlugin(ctx, agent, binary, home, market)
	}
	if before.PluginID != "aidr-"+agent+"@aidr-local" || before.sourcePath == "" {
		return before, code("aidr_plugin_multiple_sources")
	}
	if err := VerifyMarketplace(market); err != nil {
		return before, err
	}
	expected, expectedCode := pluginFilesDigest(agent, filepath.Join(market, "plugins", "aidr-"+agent))
	if expectedCode != "aidr_plugin_files_observed" {
		return before, code("aidr_plugin_package_invalid")
	}
	if before.FilesDigest == expected && before.PluginVersion == BundledPluginVersion {
		return before, nil
	}
	if agent == "codex" {
		oldMarket := filepath.Dir(filepath.Dir(before.sourcePath))
		if _, err = hostCommand(ctx, binary, agent, home, "plugin", "marketplace", "remove", "aidr-local"); err != nil {
			return before, code("aidr_plugin_update_failed")
		}
		if _, err = hostCommand(ctx, binary, agent, home, "plugin", "marketplace", "add", market); err != nil {
			_, _ = hostCommand(ctx, binary, agent, home, "plugin", "marketplace", "add", oldMarket)
			return before, code("aidr_plugin_update_failed")
		}
		_, err = hostCommand(ctx, binary, agent, home, "plugin", "add", before.PluginID, "--json")
		if !*before.Enabled && !preserveCodexDisabled(ctx, binary, home, before.PluginID) {
			return before, code("aidr_plugin_update_failed")
		}
	} else {
		if _, err = hostCommand(ctx, binary, agent, home, "plugin", "marketplace", "add", market); err == nil {
			_, err = hostCommand(ctx, binary, agent, home, "plugin", "update", before.PluginID, "--scope", "user")
		}
		if err == nil && !*before.Enabled {
			current, e := InspectPlugin(ctx, agent, binary, home, "")
			if e != nil || current.Enabled == nil {
				return current, code("aidr_plugin_update_not_applied")
			}
			if *current.Enabled {
				_, err = hostCommand(ctx, binary, agent, home, "plugin", "disable", before.PluginID, "--scope", "user")
			}
		}
	}
	if err != nil {
		return before, code("aidr_plugin_update_failed")
	}
	after, err := InspectPlugin(ctx, agent, binary, home, "")
	if err != nil || after.Installed == nil || !*after.Installed || after.Enabled == nil || *after.Enabled != *before.Enabled || after.FilesDigest != expected || after.PluginVersion != BundledPluginVersion {
		return after, code("aidr_plugin_update_not_applied")
	}
	return after, nil
}
