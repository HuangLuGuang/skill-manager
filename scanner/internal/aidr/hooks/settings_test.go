package hooks

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	products "skill-manager/scanner/internal/aidr/catalog"
)

func TestSettingsMergeRepeatRemove(t *testing.T) {
	for _, agent := range []string{"cursor", "qoder-hooks", "qoder-work", "workbuddy"} {
		t.Run(agent, func(t *testing.T) {
			product, _ := products.Get(agent)
			if !products.SupportedHookOS(product) {
				t.Skip("settings installation is not available on this OS")
			}
			home, _ := filepath.EvalSymlinks(t.TempDir())
			path, _ := settingsPath(agent, home)
			os.MkdirAll(filepath.Dir(path), 0700)
			original := `{"custom":{"preserve":9007199254740993},"hooks":{"stop":[{"command":"echo user","customNumber":9007199254740993}]}}`
			if agent != "cursor" {
				original = `{"custom":{"preserve":9007199254740993},"hooks":{"Stop":[{"matcher":"empty-user-group","hooks":[]},{"matcher":"custom","hooks":[{"type":"command","command":"echo user","customNumber":9007199254740993}]}]}}`
			}
			os.WriteFile(path, []byte(original), 0600)
			for i := 0; i < 2; i++ {
				status, err := MergeSettingsHooks(agent, home, "/safe/client", "/safe/bridge.json", false)
				if err != nil || status.Installed == nil || !*status.Installed || status.Enabled != nil {
					t.Fatal(status, err)
				}
			}
			status, err := MergeSettingsHooks(agent, home, "/safe/client", "/safe/bridge.json", true)
			if err != nil || *status.Installed {
				t.Fatal(status, err)
			}
			after, _ := os.ReadFile(path)
			if !bytes.Contains(after, []byte("9007199254740993")) || !bytes.Contains(after, []byte("echo user")) || bytes.Contains(after, []byte("aidr-hook")) {
				t.Fatal("user configuration changed")
			}
			if agent != "cursor" && !bytes.Contains(after, []byte("empty-user-group")) {
				t.Fatal("unrelated empty user group removed")
			}
		})
	}
}

func TestQoderWorkDenialUsesExitStatus(t *testing.T) {
	var out bytes.Buffer
	err := WriteHostDecision(&out, "qoder-work", "PreToolUse", "deny", "blocked by rule")
	denied, ok := err.(*HostDenied)
	if !ok || denied.ExitCode() != 2 || out.Len() != 0 {
		t.Fatalf("expected native exit-2 denial without JSON: %v, %q", err, out.String())
	}
	if err := WriteHostDecision(&out, "qoder-work", "PreToolUse", "allow", ""); err != nil {
		t.Fatal(err)
	}
}
func TestCursorProtocolAndDecisions(t *testing.T) {
	raw := `{"hook_event_name":"postToolUse","conversation_id":"session-1","generation_id":"turn-1","tool_use_id":"call-1","tool_name":"Shell","tool_input":{"command":"echo safe"},"tool_output":"{\"exit_code\":0}"}`
	e := normalize(t, "cursor", "postToolUse", raw, true)
	if e.Session != "session-1" || e.Turn != "turn-1" || e.Call != "call-1" || e.Kind != "tool.post" {
		t.Fatal("identity mapping")
	}
	for _, decision := range []string{"allow", "deny"} {
		var out bytes.Buffer
		if err := WriteHostDecision(&out, "cursor", "preToolUse", decision, "test"); err != nil {
			t.Fatal(err)
		}
		var parsed map[string]string
		json.Unmarshal(out.Bytes(), &parsed)
		if parsed["permission"] != decision {
			t.Fatal("invalid host reply")
		}
	}
	if _, err := Normalize("cursor", "postToolUse", []byte(strings.ReplaceAll(raw, `"conversation_id":"session-1",`, "")), e.Policy, testKey); err == nil {
		t.Fatal("missing native identity accepted")
	}
}
