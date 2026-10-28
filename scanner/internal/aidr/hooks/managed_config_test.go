package hooks

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/BurntSushi/toml"
)

func TestManagedCodexPreservesValuesAndRejectsConflictingDirectory(t *testing.T) {
	layout := ManagedLayout{Root: "/Library/Application Support/AgentManagerRuntime/managed", Binary: "/Library/Application Support/AgentManagerRuntime/managed/agent-manager-client"}
	raw := []byte("allowed_approval_policies = ['on-request']\n[features]\nplugins = false\n[hooks]\n[[hooks.PreToolUse]]\nmatcher = '^Bash$'\n[[hooks.PreToolUse.hooks]]\ntype = 'command'\ncommand = '/company/owned-hook'\n")
	next, added, err := mergeManagedConfig(raw, "codex", layout, true, false)
	if err != nil || !added || !managedContains(next, "codex", layout) {
		t.Fatal(err, string(next))
	}
	var decoded map[string]any
	if _, err = toml.Decode(string(next), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["features"].(map[string]any)["plugins"] != false || !strings.Contains(string(next), "/company/owned-hook") || strings.Contains(string(next), "allow_managed_hooks_only") {
		t.Fatal("other policy changed", string(next))
	}
	again, _, err := mergeManagedConfig(next, "codex", layout, true, true)
	if err != nil || string(again) != string(next) {
		t.Fatal("repeat installation changed policy", err)
	}
	removed, _, err := mergeManagedConfig(next, "codex", layout, false, true)
	if err != nil || !strings.Contains(string(removed), "/company/owned-hook") || strings.Contains(string(removed), "aidr-hook") {
		t.Fatal("removed foreign hook", err, string(removed))
	}
	_, _, err = mergeManagedConfig([]byte("[hooks]\nmanaged_dir='/company/hooks'\n"), "codex", layout, true, false)
	if err == nil || err.Error() != "aidr_managed_config_conflict" {
		t.Fatal(err)
	}
	_, _, err = mergeManagedConfig([]byte("[features]\nhooks=false\n"), "codex", layout, true, false)
	if err == nil {
		t.Fatal("silently replaced another administrator's setting")
	}
	_, _, err = mergeManagedConfig(next, "codex", layout, true, false)
	if err == nil || err.Error() != "aidr_managed_ownership_unknown" {
		t.Fatal("adopted unowned hook", err)
	}
}

func TestManagedClaudeIsIndependentJSONAndRetainsOtherHooks(t *testing.T) {
	layout := ManagedLayout{Root: "/system/our hooks", Binary: "/system/our hooks/client"}
	raw := []byte(`{"permissions":{"deny":["Read(./.env)"]},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"/company/stop"}]}]}}`)
	next, _, err := mergeManagedConfig(raw, "claude", layout, true, false)
	if err != nil || !json.Valid(next) || !managedContains(next, "claude", layout) {
		t.Fatal(err, string(next))
	}
	if !strings.Contains(string(next), "PermissionDenied") || !strings.Contains(string(next), "/company/stop") || strings.Contains(string(next), "allowManagedHooksOnly") {
		t.Fatal("unrelated settings changed")
	}
	removed, _, err := mergeManagedConfig(next, "claude", layout, false, true)
	if err != nil || strings.Contains(string(removed), "aidr-hook") || !strings.Contains(string(removed), "Read(./.env)") || !strings.Contains(string(removed), "/company/stop") {
		t.Fatal(err, string(removed))
	}
	for _, invalid := range []string{`null`, `[]`, `{"hooks":false}`, `{"hooks":{"Stop":"bad"}}`} {
		if _, _, err = mergeManagedConfig([]byte(invalid), "claude", layout, true, false); err == nil {
			t.Fatal("invalid settings accepted", invalid)
		}
	}
}

func TestManagedCodexMigratesOwnedNativeTimeouts(t *testing.T) {
	layout := ManagedLayout{Root: "/system/aidr", Binary: "/system/aidr/client"}
	legacy := []byte("[hooks]\nmanaged_dir = '/system/aidr'\n[[hooks.SessionEnd]]\n[[hooks.SessionEnd.hooks]]\ntype = 'command'\ncommand = \"'/system/aidr/client' aidr-hook --managed-connection --agent codex --event SessionEnd\"\ntimeout = 60\n[[hooks.Interrupt]]\n[[hooks.Interrupt.hooks]]\ntype = 'command'\ncommand = \"'/system/aidr/client' aidr-hook --managed-connection --agent codex --event Interrupt\"\ntimeout = 60\n")
	next, _, err := mergeManagedConfig(legacy, "codex", layout, true, true)
	if err != nil {
		t.Fatal(err)
	}
	type group struct{ Hooks []struct{ Timeout int } }
	var values struct {
		Hooks struct{ SessionEnd, Interrupt, PreToolUse []group }
	}
	if _, err = toml.Decode(string(next), &values); err != nil {
		t.Fatal(err)
	}
	if values.Hooks.SessionEnd[0].Hooks[0].Timeout != 3 || values.Hooks.Interrupt[0].Hooks[0].Timeout != 3 {
		t.Fatal("native event timeout not migrated")
	}
	if values.Hooks.PreToolUse[0].Hooks[0].Timeout != 315 {
		t.Fatal("blocking hook budget changed")
	}
	if _, _, err = mergeManagedConfig(legacy, "codex", layout, true, false); err == nil || err.Error() != "aidr_managed_ownership_unknown" {
		t.Fatal("unowned legacy entry adopted", err)
	}
	changed := []byte(strings.Replace(string(legacy), "timeout = 60", "timeout = 4", 1))
	if _, _, err = mergeManagedConfig(changed, "codex", layout, true, true); err == nil || err.Error() != "aidr_managed_config_conflict" {
		t.Fatal("administrator-changed entry overwritten", err)
	}
	removed, _, err := mergeManagedConfig(legacy, "codex", layout, false, true)
	if err != nil || strings.Contains(string(removed), "aidr-hook") {
		t.Fatal("owned legacy removal failed", err)
	}
}
