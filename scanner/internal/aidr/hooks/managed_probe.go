package hooks

import (
	"context"
	"encoding/json"
	"path/filepath"
)

// ManagedHostReady checks native inspection before authorization and effective
// managed hooks after installation. Inventory alone is not a trust grant.
func ManagedHostReady(ctx context.Context, agent, binary, home string, installed bool) error {
	if !filepath.IsAbs(binary) || !filepath.IsAbs(home) {
		return code("aidr_managed_interface_unavailable")
	}
	if agent == "claude" {
		status, err := InspectPlugin(ctx, agent, binary, home, "")
		if err != nil || status.VersionStatus != "interface_compatible" {
			return code("aidr_managed_interface_unavailable")
		}
		return nil
	}
	if agent != "codex" {
		return code("aidr_plugin_host_unsupported")
	}
	raw, ok := nativeCodexCall(ctx, binary, home, "hooks/list", map[string]any{"cwds": []string{home}})
	if !ok || !managedInventoryReadable(raw) {
		return code("aidr_managed_interface_unavailable")
	}
	if installed {
		layout, err := SystemManagedLayout(agent)
		if err != nil {
			return err
		}
		if parseNativeManagedTrust(raw, layout) != "managed" {
			return code("aidr_managed_hooks_not_applied")
		}
	}
	return nil
}

func managedInventoryReadable(raw []byte) bool {
	var result struct {
		Data []struct {
			Hooks    []json.RawMessage `json:"hooks"`
			Errors   []json.RawMessage `json:"errors"`
			Warnings []json.RawMessage `json:"warnings"`
		} `json:"data"`
	}
	if json.Unmarshal(raw, &result) != nil || len(result.Data) != 1 {
		return false
	}
	g := result.Data[0]
	return g.Hooks != nil && len(g.Errors) == 0 && len(g.Warnings) == 0
}
