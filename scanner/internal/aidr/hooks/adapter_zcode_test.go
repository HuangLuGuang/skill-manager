package hooks

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestZcodeGrantScopeReplayAndRestart(t *testing.T)  { testGrantExactScope(t, "zcode") }
func TestZcodeIndependentApprovalAttempts(t *testing.T) { testApprovalAttemptLifecycle(t, "zcode") }

func TestZcodeCapturedDesktopHooks(t *testing.T) {
	raw, err := os.ReadFile("../agentlog/testdata/zcode-3.16.3/desktop-hooks.json")
	if err != nil {
		t.Fatal(err)
	}
	var events []json.RawMessage
	if json.Unmarshal(raw, &events) != nil {
		t.Fatal("invalid fixture")
	}
	found := false
	for _, raw := range events {
		var header struct {
			Event string `json:"hook_event_name"`
		}
		json.Unmarshal(raw, &header)
		in, err := zcodeHookAdapter().Decode(header.Event, raw)
		if err != nil || in.Session == "" || in.Turn == "" {
			t.Fatal(header.Event, err)
		}
		if header.Event == "PostToolUse" {
			found = true
			if in.Tool != "Bash" || in.Call == "" {
				t.Fatal(in)
			}
		}
	}
	if !found {
		t.Fatal("desktop tool result fixture missing")
	}
}

func TestZcodeNativeIdentityAndSettings(t *testing.T) {
	in, err := zcodeHookAdapter().Decode("PreToolUse", []byte(`{"hook_event_name":"PreToolUse","session_id":"native-session","turnId":"native-turn","tool_use_id":"native-call","tool_name":"Bash","tool_input":{"command":"printf harmless"}}`))
	if err != nil || in.Turn != "native-turn" || in.Call != "native-call" {
		t.Fatal(in, err)
	}
	for _, enabled := range []string{"false", "true"} {
		home, _ := filepath.EvalSymlinks(t.TempDir())
		dir := filepath.Join(home, ".zcode/cli")
		os.MkdirAll(dir, 0700)
		path := filepath.Join(dir, "config.json")
		before := []byte(`{"custom":7,"hooks":{"enabled":` + enabled + `,"timeoutMs":1234,"events":{"PreToolUse":[{"matcher":"Read","hooks":[{"type":"process","command":"user-hook","args":["--test"]}]}]}}}`)
		os.WriteFile(path, before, 0600)
		for _, remove := range []bool{false, false, true, true} {
			if _, err := MergeSettingsHooks("zcode", home, "/tmp/client", "/tmp/bridge", remove); err != nil {
				t.Fatal(err)
			}
		}
		var want, got any
		json.Unmarshal(before, &want)
		after, _ := os.ReadFile(path)
		json.Unmarshal(after, &got)
		a, _ := json.Marshal(want)
		b, _ := json.Marshal(got)
		if !bytes.Equal(a, b) {
			t.Fatalf("settings changed: %s", after)
		}
	}
}
