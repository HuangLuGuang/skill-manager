package hooks

import (
	"encoding/json"
	"testing"
)

func TestNativeTrustSeparatesMissingWarningsAndUntrusted(t *testing.T) {
	hooks := []map[string]any{}
	for n := 0; n < 12; n++ {
		hooks = append(hooks, map[string]any{"pluginId": "aidr-codex@aidr-local", "enabled": true, "trustStatus": "trusted"})
	}
	group := map[string]any{"hooks": hooks, "errors": []string{}, "warnings": []string{}}
	read := func() string {
		raw, _ := json.Marshal(map[string]any{"data": []any{group}})
		return parseNativeCodexTrust(raw)
	}
	if read() != "trusted" {
		t.Fatal("trusted inventory not recognized")
	}
	hooks[0]["trustStatus"] = "untrusted"
	if read() != "needs_review" {
		t.Fatal("untrusted hook reported trusted")
	}
	hooks[0]["trustStatus"] = "trusted"
	hooks[0]["enabled"] = false
	if read() != "needs_review" {
		t.Fatal("disabled hook reported trusted")
	}
	group["warnings"] = []string{"unreadable definition"}
	if read() != "unknown" {
		t.Fatal("incomplete inventory treated as complete")
	}
	group["warnings"] = []string{}
	group["hooks"] = hooks[:11]
	if read() != "unknown" {
		t.Fatal("partial inventory treated as complete")
	}
	if parseNativeCodexTrust([]byte(`{"data":[]}`)) != "unknown" {
		t.Fatal("missing inventory treated as trusted")
	}
}

func TestManagedTrustRequiresNativeIdentityAndEveryExactHook(t *testing.T) {
	layout := ManagedLayout{Root: "/system/aidr", Binary: "/system/aidr/client", Config: "/system/codex/requirements.toml"}
	items := []map[string]any{}
	for event := range catalog["codex"] {
		items = append(items, map[string]any{"command": managedCommand(layout, "codex", event), "isManaged": true, "enabled": true, "sourcePath": layout.Root, "source": "system", "trustStatus": "managed", "eventName": managedNativeEvent(event)})
	}
	group := map[string]any{"hooks": items, "errors": []any{}, "warnings": []any{}}
	read := func() string {
		raw, _ := json.Marshal(map[string]any{"data": []any{group}})
		return parseNativeManagedTrust(raw, layout)
	}
	if read() != "managed" {
		t.Fatal("valid native managed inventory rejected")
	}
	for key, bad := range map[string]any{"isManaged": false, "enabled": false, "sourcePath": "/other/config", "source": "plugin", "trustStatus": "trusted", "eventName": "wrong"} {
		original := items[0][key]
		items[0][key] = bad
		if read() != "unknown" {
			t.Fatal("unverified managed trust", key)
		}
		items[0][key] = original
	}
	items[0]["sourcePath"] = layout.Config
	if read() != "unknown" {
		t.Fatal("configuration path is not the native managed source directory")
	}
	items[0]["sourcePath"] = layout.Root
	group["warnings"] = []string{"clamping SessionEnd hook timeout to 3s"}
	if read() != "unknown" {
		t.Fatal("native loading warning hidden")
	}
	group["warnings"] = []string{}
	group["hooks"] = items[:11]
	if read() != "unknown" {
		t.Fatal("partial trust accepted")
	}
}
