package hooks

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"

	"skill-manager/scanner/internal/aidr/agentlog"
)

var testKey = bytes.Repeat([]byte{31}, 32)

func normalize(t *testing.T, host, hook, body string, enabled bool) Event {
	t.Helper()
	e, err := Normalize(host, hook, []byte(body), agentlog.AuditPolicy{Version: "9", Enabled: enabled, Receipt: strings.Repeat("a", 32)}, testKey)
	if err != nil {
		t.Fatal(err)
	}
	return e
}

func TestLifecycleProjectionOmitsBodies(t *testing.T) {
	for host, events := range catalog {
		for hook, kind := range events {
			if strings.HasPrefix(kind, "tool.") || strings.HasPrefix(kind, "permission.") {
				continue
			}
			t.Run(host+"/"+hook, func(t *testing.T) {
				raw, _ := json.Marshal(map[string]any{"hook_event_name": hook, "session_id": "session-1", "conversation_id": "session-1", "prompt": "SYNTHETIC-PROMPT-SECRET", "message": "SYNTHETIC-MESSAGE-SECRET", "transcript_path": "/private/secret.jsonl", "reason": "UNRECOGNIZED-REASON"})
				e := normalize(t, host, hook, string(raw), false)
				got, _ := json.Marshal(e)
				if e.Kind != kind || e.ProcessRelation != "unknown" || e.Behavior != nil || e.CallKey("device", "user") != "" {
					t.Fatalf("bad lifecycle projection: %s", got)
				}
				for _, secret := range []string{"SECRET", "/private/secret", "UNRECOGNIZED"} {
					if bytes.Contains(got, []byte(secret)) {
						t.Fatal("raw body retained")
					}
				}
			})
		}
	}
}

func TestToolPolicyAndResultEvidence(t *testing.T) {
	raw := `{"hook_event_name":"PreToolUse","session_id":"s","turn_id":"t","tool_use_id":"c","tool_name":"Bash","tool_input":{"command":"echo --password='synthetic-secret' && pwd"}}`
	e := normalize(t, "codex", "PreToolUse", raw, true)
	b, _ := json.Marshal(e)
	if bytes.Contains(b, []byte("synthetic-secret")) || !bytes.Contains(b, []byte("[REDACTED]")) {
		t.Fatalf("bad redaction: %s", b)
	}
	off := normalize(t, "codex", "PreToolUse", raw, false)
	b, _ = json.Marshal(off)
	if !bytes.Contains(b, []byte("synthetic-secret")) {
		t.Fatal("disabled policy not applied")
	}
	if e.InputDigest != off.InputDigest || e.CallKey("d", "u") != off.CallKey("d", "u") {
		t.Fatal("policy changed invocation identity")
	}
	for _, tc := range []struct {
		result, status string
		exit           *int
	}{
		{`{"exit_code":0,"stdout":"BODY-SECRET"}`, "reported_success", newInt(0)},
		{`{"exit_code":7,"stdout":"BODY-SECRET"}`, "reported_error", newInt(7)},
		{`"BODY-SECRET"`, "unknown", nil},
	} {
		e := normalize(t, "codex", "PostToolUse", `{"hook_event_name":"PostToolUse","session_id":"s","tool_use_id":"c","tool_name":"Bash","tool_response":`+tc.result+`}`, true)
		if e.Behavior.Status != tc.status || (tc.exit == nil) != (e.Behavior.ExitCode == nil) || (tc.exit != nil && *tc.exit != *e.Behavior.ExitCode) {
			t.Fatalf("unexpected result %+v", e.Behavior)
		}
		b, _ := json.Marshal(e)
		if bytes.Contains(b, []byte("BODY-SECRET")) {
			t.Fatal("result body retained")
		}
	}
	failure := normalize(t, "claude", "PostToolUseFailure", `{"hook_event_name":"PostToolUseFailure","session_id":"s","tool_use_id":"c","tool_name":"Bash","error":"Exit code 7\nBODY-SECRET"}`, true)
	if failure.Behavior.ExitCode == nil || *failure.Behavior.ExitCode != 7 {
		t.Fatal("explicit failure exit lost")
	}
}
func newInt(n int) *int { return &n }

func TestClaudeNativeReadHookContentKeepsEvidenceUnknown(t *testing.T) {
	raw := []byte(`{"hook_event_name":"PostToolUse","session_id":"s","tool_use_id":"read-1","tool_name":"Read","tool_response":{"type":"text","file":{"filePath":"/tmp/fixture/audit.txt","content":"TOKEN=SYNTHETIC-READ-ONLY\n","numLines":1,"startLine":1,"totalLines":1}}}`)
	policy := agentlog.AuditPolicy{Version: "9", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{FileBody: true}}
	e, err := Normalize("claude", "PostToolUse", raw, policy, testKey)
	if err != nil || e.Behavior == nil || e.Behavior.ContentStatus != "captured" || len(e.Behavior.Contents) != 1 {
		t.Fatal(e, err)
	}
	if e.Behavior.Contents[0].Field != "result.file.text" || e.Behavior.Contents[0].Text != "TOKEN=[REDACTED]\n" || e.Behavior.Status != "unknown" || e.Behavior.ExitCode != nil || e.ProcessRelation != "unknown" {
		t.Fatal(e.Behavior)
	}
	encoded, _ := json.Marshal(e)
	if bytes.Contains(encoded, []byte("SYNTHETIC-READ-ONLY")) || bytes.Contains(encoded, []byte("numLines")) {
		t.Fatal("unprojected native response retained")
	}
}

// Codex 0.158.0-alpha.2.1 native PostToolUse supplied only stdout for
// controlled printf (exit 0) and exit 7 calls. Neither string proves an outcome.
func TestNativeCodexStdoutOnlyResultRemainsUnknown(t *testing.T) {
	for _, stdout := range []string{"aidr-native-hook-check\n", "", "Process exited with code 0\n"} {
		raw, _ := json.Marshal(map[string]any{
			"hook_event_name": "PostToolUse", "session_id": "isolated-session",
			"turn_id": "isolated-turn", "tool_use_id": "exec-isolated",
			"tool_name": "Bash", "tool_response": stdout,
		})
		e := normalize(t, "codex", "PostToolUse", string(raw), true)
		if e.Behavior.Status != "unknown" || e.Behavior.ExitCode != nil || e.ProcessRelation != "unknown" {
			t.Fatalf("stdout was promoted to execution evidence: %+v", e.Behavior)
		}
		projected, _ := json.Marshal(e)
		if stdout != "" && bytes.Contains(projected, []byte(strings.TrimSpace(stdout))) {
			t.Fatal("stdout body retained")
		}
	}
}

func TestDigestBoundariesAndLargeNumbers(t *testing.T) {
	prefix := `{"hook_event_name":"PreToolUse","session_id":"s","tool_use_id":"c","tool_name":"mcp__x__tool","tool_input":`
	a := normalize(t, "codex", "PreToolUse", prefix+`{"n":9007199254740993,"a":1}}`, true)
	b := normalize(t, "codex", "PreToolUse", prefix+`{"a":1,"n":9007199254740993}}`, true)
	c := normalize(t, "codex", "PreToolUse", prefix+`{"a":1,"n":9007199254740992}}`, true)
	if a.InputDigest != b.InputDigest || a.InputDigest == c.InputDigest {
		t.Fatal("digest lost ordering independence or integer precision")
	}
	other, err := Normalize("codex", "PreToolUse", []byte(prefix+`{"n":9007199254740993,"a":1}}`), agentlog.DefaultAuditPolicy(), bytes.Repeat([]byte{9}, 32))
	if err != nil || a.InputDigest == other.InputDigest {
		t.Fatal("digest is not receiver-keyed")
	}
	if len(a.Behavior.Actions) != 0 || a.Behavior.Method != "unsupported" {
		t.Fatal("unknown arguments projected")
	}
}

func TestConcurrentIdentityScopes(t *testing.T) {
	var wg sync.WaitGroup
	keys := make(chan string, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			raw := fmt.Sprintf(`{"hook_event_name":"PreToolUse","session_id":"s-%d","turn_id":"t","tool_use_id":"same","tool_name":"Bash","tool_input":{"command":"true"}}`, i)
			e := normalize(t, "codex", "PreToolUse", raw, true)
			keys <- e.CallKey("d", "u")
		}(i)
	}
	wg.Wait()
	close(keys)
	seen := map[string]bool{}
	for k := range keys {
		if k == "" || seen[k] {
			t.Fatal("concurrent sessions merged")
		}
		seen[k] = true
	}
	e := Event{Agent: "codex", Session: "s", Turn: "t", Call: "c"}
	k := e.CallKey("d", "u")
	if k == e.CallKey("other", "u") || k == e.CallKey("d", "other") {
		t.Fatal("authenticated boundary omitted")
	}
	e.Subagent = "sub"
	if k == e.CallKey("d", "u") {
		t.Fatal("subagent boundary omitted")
	}
	e.Subagent = ""
	e.Turn = ""
	if k == e.CallKey("d", "u") {
		t.Fatal("missing turn guessed")
	}
}

func TestInvalidInputDoesNotBecomeEvidence(t *testing.T) {
	for _, raw := range []string{`null`, `{}`, `[]`, `{"hook_event_name":"Stop","session_id":"s"} {}`, `{"hook_event_name":"Stop","session_id":"s\nforged"}`, strings.Repeat("x", MaxRecordBytes+1)} {
		if _, err := Normalize("codex", "Stop", []byte(raw), agentlog.DefaultAuditPolicy(), testKey); err == nil {
			t.Fatalf("accepted malformed input %q", raw[:min(len(raw), 80)])
		}
	}
	if _, err := Normalize("codex", "InventedEvent", []byte(`{}`), agentlog.DefaultAuditPolicy(), testKey); err == nil {
		t.Fatal("unsupported event accepted")
	}
}
