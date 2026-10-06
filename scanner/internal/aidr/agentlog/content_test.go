package agentlog

import (
	"encoding/json"
	"strings"
	"testing"
)

func contentPolicy(enabled bool, scope CaptureScope) AuditPolicy {
	return AuditPolicy{Version: "2", Enabled: enabled, Receipt: strings.Repeat("a", 32), Capture: &scope}
}

func TestCodexNativePatchCommandField(t *testing.T) {
	patch := "*** Begin Patch\n*** Add File: audit.txt\n+AIDR-FILE-ONE\n+TOKEN=SYNTHETIC-FILEBODY-ONLY\n*** End Patch\n"
	raw, _ := json.Marshal(map[string]string{"command": patch, "unrecognized": "NEVER-COPY"})
	for _, enabled := range []bool{true, false} {
		p := contentPolicy(enabled, CaptureScope{FileBody: true})
		b := projectBehaviorPolicy(draft{Kind: "tool_call", Tool: "apply_patch", Content: raw}, 3, &p)
		if b.ContentStatus != "captured" || len(b.Contents) != 1 || b.Contents[0].Field != "input.command" || len(b.Actions[0].Targets) != 1 || b.Actions[0].Targets[0].Value != "audit.txt" {
			t.Fatal(b)
		}
		expected := patch
		if enabled {
			expected = strings.ReplaceAll(patch, "SYNTHETIC-FILEBODY-ONLY", "[REDACTED]")
		}
		if b.Contents[0].Text != expected || b.Contents[0].Redacted != enabled || b.Status != "unknown" || b.ExitCode != nil || validateBehavior(b) != nil {
			t.Fatal(b)
		}
		b.Category = "file_write"
		if validateBehavior(b) == nil {
			t.Fatal("native patch command accepted without patch binding")
		}
	}
	p := contentPolicy(true, CaptureScope{FileBody: true})
	if v, s := projectContents("Bash", "tool_call", raw, p); len(v) != 0 || s != "not_requested" {
		t.Fatal("shell command classified as file body", v, s)
	}
	if v, s := projectContents("apply_patch", "tool_call", raw, contentPolicy(true, CaptureScope{})); len(v) != 0 || s != "not_requested" {
		t.Fatal("file-body scope bypass", v, s)
	}
}

func TestClaudeNativeReadTextFileResult(t *testing.T) {
	// Independent native Read response shape observed on Claude Code 2.1.220.
	raw := json.RawMessage(`{"type":"text","file":{"filePath":"/tmp/fixture/audit.txt","content":"AIDR-BODY-ONE\nTOKEN=SYNTHETIC-READ-ONLY\n","numLines":2,"startLine":1,"totalLines":2},"unknown":"NEVER-COPY"}`)
	for _, enabled := range []bool{false, true} {
		p := contentPolicy(enabled, CaptureScope{FileBody: true})
		values, status := projectContents("Read", "tool_result", raw, p)
		if status != "captured" || len(values) != 1 || values[0].Field != "result.file.text" || values[0].Kind != "file_body" || values[0].Redacted != enabled {
			t.Fatal(values, status)
		}
		want := "AIDR-BODY-ONE\nTOKEN=SYNTHETIC-READ-ONLY\n"
		if enabled {
			want = "AIDR-BODY-ONE\nTOKEN=[REDACTED]\n"
		}
		if values[0].Text != want || validateContents(values, status, p) != nil {
			t.Fatal(values, status)
		}
	}
	for _, tool := range []string{"Read", "read_file"} {
		if values, status := projectContents(tool, "tool_result", raw, contentPolicy(true, CaptureScope{ToolOutput: true})); len(values) != 0 || status != "not_requested" {
			t.Fatal("file-body scope required", tool, values, status)
		}
	}
	for _, raw := range []json.RawMessage{
		json.RawMessage(`{"type":"image","file":{"content":"NOT-TEXT"}}`),
		json.RawMessage(`{"file":{"content":"UNCLASSIFIED"}}`),
		json.RawMessage(`{"type":"text","file":"UNSTRUCTURED"}`),
	} {
		if values, status := projectContents("Read", "tool_result", raw, contentPolicy(true, CaptureScope{FileBody: true})); len(values) != 0 || status != "unsupported" {
			t.Fatal("unrecognized native content", values, status)
		}
	}
	if values, status := projectContents("Bash", "tool_result", raw, contentPolicy(true, CaptureScope{ToolOutput: true, FileBody: true})); len(values) != 0 || status != "unsupported" {
		t.Fatal("unrelated tool classified as file text", values, status)
	}
	long, _ := json.Marshal(map[string]any{"type": "text", "file": map[string]string{"content": strings.Repeat("你", 900)}})
	values, status := projectContents("Read", "tool_result", long, contentPolicy(false, CaptureScope{FileBody: true}))
	if status != "partial" || len(values) != 1 || !values[0].Truncated || len(values[0].Text) > 1024 || validateContents(values, status, contentPolicy(false, CaptureScope{FileBody: true})) != nil {
		t.Fatal("native read content budget", values, status)
	}
}

func TestExplicitContentScopeMatrixAndBudget(t *testing.T) {
	for mask := 0; mask < 8; mask++ {
		p := contentPolicy(true, CaptureScope{Prompt: mask&1 != 0, ToolOutput: mask&2 != 0, FileBody: mask&4 != 0})
		prompt, status := ProjectPrompt(`TOKEN=SYNTHETIC-PROMPT`, p)
		if p.Capture.Prompt {
			if status != "captured" || prompt[0].Text != "TOKEN=[REDACTED]" {
				t.Fatal(mask, prompt, status)
			}
		} else if len(prompt) != 0 || status != "not_requested" {
			t.Fatal(mask, prompt, status)
		}
		output, s := projectContents("Bash", "tool_result", json.RawMessage(`"Authorization: Bearer SYNTHETIC-OUTPUT"`), p)
		if p.Capture.ToolOutput {
			if s != "captured" || output[0].Text != "Authorization: Bearer [REDACTED]" {
				t.Fatal(mask, output, s)
			}
		} else if len(output) != 0 || s != "not_requested" {
			t.Fatal(mask, output, s)
		}
		file, f := projectContents("Write", "tool_call", json.RawMessage(`{"content":"password='SYNTHETIC-FILE'","unknown":"DO-NOT-COPY"}`), p)
		if p.Capture.FileBody {
			if f != "captured" || file[0].Text != "password='[REDACTED]'" {
				t.Fatal(mask, file, f)
			}
		} else if len(file) != 0 || f != "not_requested" {
			t.Fatal(mask, file, f)
		}
		for _, v := range []struct {
			values []Content
			status string
		}{{prompt, status}, {output, s}, {file, f}} {
			if err := validateContents(v.values, v.status, p); err != nil {
				t.Fatal(err)
			}
		}
	}
	p := contentPolicy(false, CaptureScope{FileBody: true, ToolOutput: true, Prompt: true})
	original := `git commit -m "credential rotation" && tool --password="SYNTHETIC-OFF"`
	data, _ := json.Marshal(original)
	values, status := projectContents("Bash", "tool_result", data, p)
	if status != "captured" || values[0].Text != original || values[0].Redacted {
		t.Fatal(values, status)
	}
	long := strings.Repeat("你", 800)
	encoded, _ := json.Marshal(map[string]any{"edits": []map[string]string{{"old_string": long, "new_string": long}, {"old_string": "extra", "new_string": "extra"}}})
	values, status = projectContents("MultiEdit", "tool_call", encoded, p)
	total := 0
	for _, c := range values {
		total += len(c.Text)
		if len(c.Text) > 1024 || c.SourceBytes < len(c.Text) {
			t.Fatal(c)
		}
	}
	if total > 2048 || status != "partial" || !values[0].Truncated {
		t.Fatal(values, status, total)
	}
	if err := validateContents(values, status, p); err != nil {
		t.Fatal(err)
	}
	for _, tool := range []string{"js", "exec", "unknown"} {
		v, s := projectContents(tool, "tool_call", json.RawMessage(`{"content":"NEVER-TRANSMIT"}`), p)
		want := "not_requested"
		if tool == "unknown" {
			want = "unsupported"
		}
		if len(v) != 0 || s != want {
			t.Fatal(tool, v, s)
		}
	}
	if v, s := projectContents("", "tool_result", json.RawMessage(`"AMBIGUOUS-RESULT"`), p); len(v) != 0 || s != "unsupported" {
		t.Fatal(v, s)
	}
	if v, s := projectContents("Read", "tool_result", json.RawMessage(`"File text"`), contentPolicy(false, CaptureScope{ToolOutput: true})); len(v) != 0 || s != "not_requested" {
		t.Fatal("file result crossed tool-output boundary", v, s)
	}
}

func TestResultToolBindingSurvivesCursorAndPreservesIdentityInputs(t *testing.T) {
	c := Cursor{}
	call := `{"type":"assistant","timestamp":"2026-09-23T10:00:00Z","sessionId":"a","version":"2.1.220","message":{"content":[{"type":"tool_use","id":"same","name":"Read","input":{"file_path":"/tmp/test"}}]}}`
	if _, err := normalize("claude", []byte(call), &c); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(c)
	var restored Cursor
	if err := json.Unmarshal(raw, &restored); err != nil {
		t.Fatal(err)
	}
	result := `{"type":"user","timestamp":"2026-09-23T10:00:01Z","sessionId":"a","message":{"content":[{"type":"tool_result","tool_use_id":"same","content":"Fictional file"}]}}`
	d, err := normalize("claude", []byte(result), &restored)
	if err != nil || len(d) != 1 || d[0].Tool != "" || d[0].ResultTool != "Read" {
		t.Fatal(d, err)
	}
	p := contentPolicy(false, CaptureScope{FileBody: true})
	b := projectBehaviorPolicy(d[0], 3, &p)
	if b.Version != 4 || b.Contents[0].Kind != "file_body" || b.Contents[0].Text != "Fictional file" {
		t.Fatal(b)
	}
	// Legacy event identity still uses the original empty result Tool.
	if legacy := projectBehaviorPolicy(d[0], 3, nil); len(legacy.Contents) != 0 || legacy.ContentStatus != "" {
		t.Fatal(legacy)
	}
	_, err = normalize("claude", []byte(strings.ReplaceAll(result, `"sessionId":"a"`, `"sessionId":"b"`)), &restored)
	if err != nil || boundTool(&restored, "same") != "" {
		t.Fatal("cross-session association", err)
	}
	rememberTool(&restored, "same", "turn-one", "Read", nil)
	rememberTool(&restored, "same", "turn-two", "Bash", nil)
	if boundTool(&restored, "same") != "" {
		t.Fatal("ambiguous call was classified")
	}
	for i := 0; i < 100; i++ {
		rememberTool(&restored, strings.Repeat("x", i+1), "t", "Bash", nil)
	}
	if len(restored.CallTurns) > maxToolBindings {
		t.Fatal("unbounded cursor bindings")
	}
}

func TestTruncationThroughSecretReplacementRemainsUploadable(t *testing.T) {
	p := contentPolicy(true, CaptureScope{ToolOutput: true})
	for _, suffix := range []string{"TOKEN=SYNTHETIC-SECRET", "Authorization: Bearer SYNTHETIC-SECRET", "password='SYNTHETIC-SECRET'"} {
		for cut := 0; cut < 24; cut++ {
			raw, _ := json.Marshal(strings.Repeat("x", 1000+cut) + " " + suffix)
			values, status := projectContents("Bash", "tool_result", raw, p)
			if err := validateContents(values, status, p); err != nil {
				t.Fatal("truncated fragment cannot upload", cut, err)
			}
			for _, v := range values {
				if strings.Contains(v.Text, "SYNTHETIC-SECRET") || len(v.Text) > 1024 {
					t.Fatal("secret or budget violation")
				}
			}
		}
	}
}
