package agentlog

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestReadableBehaviorIndependentExpectations(t *testing.T) {
	tests := []struct {
		name, tool, kind, input, outcome, category, status, command, target string
		exit                                                                *int
	}{
		{name: "shell intent", tool: "Bash", kind: "tool_call", input: `{"command":"/bin/ls -l /tmp/audit","cwd":"/tmp/audit"}`, category: "command", status: "unknown", command: "/bin/ls -l /tmp/audit"},
		{name: "windows powershell intent", tool: "PowerShell", kind: "tool_call", input: `{"command":"Remove-Item C:\\Protected -Recurse","cwd":"C:\\Work"}`, category: "command", status: "unknown", command: `Remove-Item C:\Protected -Recurse`},
		{name: "file read", tool: "Read", kind: "tool_call", input: `{"file_path":"/tmp/audit/input.txt","content":"DO_NOT_COPY"}`, category: "file_read", status: "unknown", target: "/tmp/audit/input.txt"},
		{name: "file edit", tool: "Edit", kind: "tool_call", input: `{"file_path":"/tmp/audit/input.txt","old_string":"DO_NOT_COPY","new_string":"DO_NOT_COPY"}`, category: "file_edit", status: "unknown", target: "/tmp/audit/input.txt"},
		{name: "file rename", tool: "rename_file", kind: "tool_call", input: `{"old_path":"/tmp/audit/input.txt","new_path":"/tmp/audit/renamed.txt"}`, category: "file_rename", status: "unknown", target: "/tmp/audit/input.txt"},
		{name: "wrapper", tool: "exec", kind: "tool_call", input: string(mustJSON(`await tools.exec_command({"cmd":"/bin/false; /bin/true","workdir":"/tmp/audit"})`)), category: "wrapper", status: "unknown", command: "/bin/false; /bin/true"},
		{name: "code unknown", tool: "js", kind: "tool_call", input: `{"code":"await arbitraryFunction(secret)","secret":"DO_NOT_COPY"}`, category: "wrapper", status: "unknown"},
		{name: "reported success", kind: "tool_result", input: `{"exit_code":0,"output":"DO_NOT_COPY"}`, category: "unknown", status: "reported_success", exit: ptr(0)},
		{name: "nonzero", kind: "tool_result", input: `{"exit_code":7,"output":"DO_NOT_COPY"}`, category: "unknown", status: "reported_error", exit: ptr(7)},
		{name: "uninterpreted result", kind: "tool_result", input: `"success, exit_code=0"`, category: "unknown", status: "unknown"},
		{name: "no error flag", kind: "tool_result", input: `"DO_NOT_COPY"`, outcome: "success", category: "unknown", status: "reported_complete"},
		{name: "cancel", kind: "tool_result", input: `{"interrupted":true}`, category: "unknown", status: "reported_cancelled"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := projectBehavior(draft{Tool: tt.tool, Kind: tt.kind, Content: json.RawMessage(tt.input), Outcome: tt.outcome})
			if b.Category != tt.category || b.Status != tt.status {
				t.Fatal(b)
			}
			if tt.command != "" && (len(b.Actions) != 1 || b.Actions[0].Command != tt.command) {
				t.Fatal(b)
			}
			if tt.target != "" && (len(b.Actions) != 1 || b.Actions[0].Targets[0].Value != tt.target) {
				t.Fatal(b)
			}
			if (b.ExitCode == nil) != (tt.exit == nil) || b.ExitCode != nil && *b.ExitCode != *tt.exit {
				t.Fatal(b)
			}
			if err := validateBehavior(b); err != nil {
				t.Fatal(err)
			}
			raw, _ := json.Marshal(b)
			if strings.Contains(string(raw), "DO_NOT_COPY") {
				t.Fatal("non-allowlisted body copied")
			}
		})
	}
}
func ptr(v int) *int { return &v }

func TestSecretsMaskedBeforePersistence(t *testing.T) {
	secret := strings.Repeat("SyntheticSensitive", 3)
	inputs := []string{"TOKEN=" + secret + " /bin/true", "curl --password " + secret + " https://example.invalid", "curl -H 'Authorization: Bearer " + secret + "' https://example.invalid", "curl -H 'Cookie: sid=" + secret + "' https://example.invalid", "printf '" + secret + "'", "cat <<EOF\n" + secret + "\nEOF", "-----BEGIN PRIVATE KEY-----\n" + secret + "\n-----END PRIVATE KEY-----"}
	for _, cmd := range inputs {
		raw, _ := json.Marshal(map[string]string{"command": cmd, "password": secret})
		b := projectBehavior(draft{Tool: "Bash", Kind: "tool_call", Content: raw})
		encoded, _ := json.Marshal(b)
		if strings.Contains(string(encoded), secret) || !b.Redacted {
			t.Fatal("secret not masked")
		}
		if err := validateBehavior(b); err != nil {
			t.Fatal(err)
		}
	}
}
func TestWrapperBoundariesAndLimits(t *testing.T) {
	code := `// tools.exec_command({"cmd":"fake"})
 const x='tools.exec_command({"cmd":"fake"})';
 await tools.exec_command({"cmd":"/bin/true"}); await tools.exec_command(dynamic);`
	b := projectBehavior(draft{Tool: "exec", Kind: "tool_call", Content: mustJSON(code)})
	if len(b.Actions) != 1 || b.Actions[0].Command != "/bin/true" {
		t.Fatal(b)
	}
	b = projectBehavior(draft{Tool: "exec", Kind: "tool_call", Content: mustJSON(strings.Repeat(`await tools.exec_command({"cmd":"/bin/true"});`, 10))})
	if len(b.Actions) != 4 || !b.Truncated {
		t.Fatal(b)
	}
	raw, _ := json.Marshal(map[string]string{"command": strings.Repeat("/long-path/", 300)})
	b = projectBehavior(draft{Tool: "Bash", Kind: "tool_call", Content: raw})
	if !b.Truncated || len(b.Actions[0].Command) > 1536 {
		t.Fatal(b)
	}
}

func TestRestrictedJavaScriptLiterals(t *testing.T) {
	for _, code := range []string{"await tools.exec_command({cmd: `/bin/true`, workdir: '/tmp/audit'});", `await tools.exec_command({"cmd":"/bin/true","workdir":"/tmp/audit"});`} {
		b := projectBehavior(draft{Tool: "exec", Kind: "tool_call", Content: mustJSON(code)})
		if len(b.Actions) != 1 || b.Actions[0].Command != "/bin/true" || b.Actions[0].Cwd != "/tmp/audit" {
			t.Fatal(b)
		}
	}
	for _, code := range []string{`tools.exec("dynamic wrapper")`, "tools.exec_command({cmd: `${secret}`})", `tools.exec_command({cmd: "a", cmd: "b"})`, `tools.exec_command({cmd: "a" + secret})`, `tools.exec_command({...secret})`, `const r=/tools.exec_command({cmd:"fake"})/;`} {
		b := projectBehavior(draft{Tool: "exec", Kind: "tool_call", Content: mustJSON(code)})
		if len(b.Actions) != 0 {
			t.Fatal("nonliteral accepted", b)
		}
	}
}

func TestRepeatedResultMetadata(t *testing.T) {
	for _, tc := range []struct {
		name   string
		codes  []int
		status string
		exit   *int
	}{
		{"matching success", []int{0, 0}, "reported_success", ptr(0)},
		{"matching error", []int{7, 7}, "reported_error", ptr(7)},
		{"mixed results", []int{0, 7}, "unknown", nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			blocks := []map[string]string{{"type": "input_text", "text": "{}"}}
			for _, code := range tc.codes {
				meta, _ := json.Marshal(map[string]int{"exit_code": code})
				blocks = append(blocks, map[string]string{"type": "input_text", "text": string(meta)})
			}
			content, _ := json.Marshal(blocks)
			result := projectBehavior(draft{Kind: "tool_result", Outcome: "unknown", Content: content})
			if result.Status != tc.status || (result.ExitCode == nil) != (tc.exit == nil) || (tc.exit != nil && *result.ExitCode != *tc.exit) {
				t.Fatalf("unexpected result: %+v", result)
			}
		})
	}
}

func TestResultHeadersAndPatchConstant(t *testing.T) {
	for _, code := range []int{0, 7} {
		meta, _ := json.Marshal(map[string]any{"exit_code": code, "output": "BODY_MUST_NOT_LEAVE"})
		blocks, _ := json.Marshal([]map[string]string{{"type": "input_text", "text": string(meta)}})
		result := projectBehavior(draft{Kind: "tool_result", Outcome: "unknown", Content: blocks})
		if result.ExitCode == nil || *result.ExitCode != code {
			t.Fatal("Codex input_text metadata missing", result)
		}
	}
	b := projectBehavior(draft{Kind: "tool_result", Outcome: "error", Content: mustJSON("Exit code 7\nintentional failure")})
	if b.ExitCode == nil || *b.ExitCode != 7 || b.Status != "reported_error" {
		t.Fatal(b)
	}
	b = projectBehavior(draft{Kind: "tool_result", Outcome: "unknown", Content: mustJSON("Exit code 0")})
	if b.ExitCode != nil || b.Status != "unknown" {
		t.Fatal("arbitrary output interpreted as exit metadata")
	}
	code := `const patch = "*** Begin Patch\n*** Update File: /tmp/audit/input.txt\n@@\n-alpha\n+DO_NOT_COPY\n*** End Patch";
text(await tools.apply_patch(patch));`
	b = projectBehavior(draft{Kind: "tool_call", Tool: "exec", Content: mustJSON(code)})
	if len(b.Actions) != 1 || b.Actions[0].Category != "patch" || b.Actions[0].Targets[0].Value != "/tmp/audit/input.txt" {
		t.Fatal(b)
	}
	raw, _ := json.Marshal(b)
	if strings.Contains(string(raw), "DO_NOT_COPY") {
		t.Fatal("patch body copied")
	}
}

func TestLateResultUsesPersistedCallTurn(t *testing.T) {
	c := Cursor{Session: "test-session", Turn: "first-turn"}
	parse := func(payload map[string]any) []draft {
		raw, _ := json.Marshal(map[string]any{"type": "response_item", "timestamp": "2026-09-24T00:00:00Z", "payload": payload})
		d, err := normalize("codex", raw, &c)
		if err != nil {
			t.Fatal(err)
		}
		return d
	}
	parse(map[string]any{"type": "function_call", "name": "exec_command", "call_id": "call-a", "arguments": "{\"cmd\":\"/usr/bin/true\"}"})
	raw, _ := json.Marshal(c)
	c = Cursor{}
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	c.Turn = "second-turn"
	d := parse(map[string]any{"type": "function_call_output", "call_id": "call-a", "output": "done"})
	if d[0].Turn != "first-turn" {
		t.Fatal("late result moved to active turn")
	}
	d = parse(map[string]any{"type": "function_call_output", "call_id": "unseen", "output": "done"})
	if d[0].Turn != "" {
		t.Fatal("unknown call inherited active turn")
	}
	parse(map[string]any{"type": "function_call", "name": "exec_command", "call_id": "call-a", "arguments": "{}"})
	d = parse(map[string]any{"type": "function_call_output", "call_id": "call-a", "output": "done"})
	if d[0].Turn != "" {
		t.Fatal("ambiguous turn merged")
	}
}

func TestAllowedTargetsNeverCopyBodies(t *testing.T) {
	for _, tool := range []string{"Write", "write_file", "MultiEdit", "edit_file", "WebFetch", "fetch"} {
		raw, _ := json.Marshal(map[string]any{"file_path": "/tmp/audit.txt", "url": "https://example.invalid/path?token=SYNTHETIC_VALUE", "content": "BODY_NOT_ALLOWED", "prompt": "BODY_NOT_ALLOWED", "edits": []any{"BODY_NOT_ALLOWED"}})
		b := projectBehavior(draft{Kind: "tool_call", Tool: tool, Content: raw})
		encoded, _ := json.Marshal(b)
		if len(b.Actions) != 1 || len(b.Actions[0].Targets) != 1 || strings.Contains(string(encoded), "BODY_NOT_ALLOWED") || strings.Contains(string(encoded), "SYNTHETIC_VALUE") {
			t.Fatal("projection copied unapproved data")
		}
		if err := validateBehavior(b); err != nil {
			t.Fatal(err)
		}
	}
}

func TestSafeControlSyntaxRetainsBodyBoundary(t *testing.T) {
	for _, tc := range []struct{ input, want string }{
		{"/bin/sh -c 'exit 7'", "/bin/sh -c 'exit 7'"},
		{"printf '%s\\n' 'BODY_MUST_NOT_LEAVE' > ./file", "printf '%s\\n' '[REDACTED]' > ./file"},
		{"sh -c 'exit 7; cat secret'", "sh -c '[REDACTED]'"},
	} {
		b := &Behavior{Version: 2}
		if got := safeCommand(tc.input, b); got != tc.want {
			t.Fatalf("control syntax mismatch: %q", got)
		}
	}
}

func TestProjectionPolicyPinnedToExistingCursor(t *testing.T) {
	line := strings.ReplaceAll(claudeCall("control"), "TOKEN=SYNTHETIC_SECRET /bin/true", "/bin/sh -c 'exit 7'")
	src := source(t, "claude", line)
	fresh := read(t, src, Cursor{})
	if fresh.Cursor.ProjectionVersion != 2 || fresh.Events[0].Behavior.Actions[0].Command != "/bin/sh -c 'exit 7'" {
		t.Fatal("new projection not used")
	}
	legacy := fresh.Cursor
	legacy.ProjectionVersion = 0
	legacy.Offset = 0
	// Empty-file anchor represents an existing checkpoint before this record.
	legacy.Anchor = digest("")
	first := read(t, src, legacy)
	if first.Events[0].Behavior.Version != 1 || first.Events[0].Behavior.Actions[0].Command != "/bin/sh -c '[REDACTED]'" {
		t.Fatal("legacy projection changed")
	}
	os.Rename(src.Path, src.Path+".old")
	os.WriteFile(src.Path, []byte(line), 0600)
	replay := read(t, src, first.Cursor)
	if replay.Events[0].LogicalEventID != first.Events[0].LogicalEventID {
		t.Fatal("rotation changed immutable logical content")
	}
}

func TestCommandRedactionRemainsValidAfterQuoteBoundaryChanges(t *testing.T) {
	input := "[REDACTED] -r '[REDACTED]'{print $1}')\nsqlite3 -json ./test.db '[REDACTED]'"
	b := projectBehavior(draft{Tool: "Bash", Kind: "tool_call", Content: mustJSON("{\"command\":" + string(mustJSON(input)) + "}")})
	if e := validateBehavior(b); e != nil {
		t.Fatal("redacted projection invalid", e)
	}
	if safeCommand(b.Actions[0].Command, &Behavior{Version: 2}) != b.Actions[0].Command {
		t.Fatal("redaction not idempotent")
	}
}
