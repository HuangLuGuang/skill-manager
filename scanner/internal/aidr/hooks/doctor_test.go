package hooks

import "testing"

func TestNativePluginStatusDoesNotInventTrustOrRemoval(t *testing.T) {
	for _, tc := range []struct {
		host, raw, code    string
		installed, enabled *bool
	}{
		{"codex", `{"installed":[]}`, "aidr_plugin_not_installed", boolp(false), boolp(false)},
		{"claude", `[]`, "aidr_plugin_not_installed", boolp(false), boolp(false)},
		{"codex", `{"installed":[{"pluginId":"aidr-codex@local","installed":true,"enabled":true,"version":"0.1.0"}]}`, "aidr_plugin_enabled_trust_unknown", boolp(true), boolp(true)},
		{"claude", `[{"id":"aidr-claude@local","enabled":false,"version":"0.1.0"}]`, "aidr_plugin_disabled", boolp(true), boolp(false)},
		{"codex", `{"installed":[{"pluginId":"aidr-codex@a","installed":true,"enabled":true},{"pluginId":"aidr-codex@b","installed":true,"enabled":false}]}`, "aidr_plugin_multiple_sources", nil, nil},
	} {
		s, err := ParsePluginStatus(tc.host, []byte(tc.raw))
		if err != nil {
			t.Fatal(err)
		}
		if s.SourceCode != tc.code || s.HookTrust != "unknown" || (s.Installed == nil) != (tc.installed == nil) || (s.Enabled == nil) != (tc.enabled == nil) {
			t.Fatalf("incorrect state %+v", s)
		}
		if tc.installed != nil && (*s.Installed != *tc.installed || *s.Enabled != *tc.enabled) {
			t.Fatal("native flags lost")
		}
	}
	for _, raw := range []string{`null`, `{}`, `{"installed":null}`, `{"installed":[{}]}`, `{"installed":[{"pluginId":"aidr-codex@a","installed":true}]}`, `not json`} {
		s, err := ParsePluginStatus("codex", []byte(raw))
		if err == nil || s.Installed != nil || s.Enabled != nil {
			t.Fatalf("unreadable source became absence: %+v", s)
		}
	}
}
func boolp(v bool) *bool { return &v }
