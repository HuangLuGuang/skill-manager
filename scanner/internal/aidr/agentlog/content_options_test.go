package agentlog

import (
	"encoding/json"
	"strings"
	"testing"
	"unicode/utf8"
)

func TestCommandBodyCaptureAndConfiguredLimits(t *testing.T) {
	command := "cat <<'EOF'\n真实正文\nTOKEN=SYNTHETIC-SECRET\nEOF\n"
	for _, tool := range []string{"Bash", "PowerShell", "exec_command", "shell_command", "exec", "js"} {
		var source any = map[string]string{"command": command}
		field := "input.command"
		if tool == "exec_command" {
			source = map[string]string{"cmd": command}
			field = "input.cmd"
		}
		if tool == "exec" {
			source = "text(await tools.exec_command({cmd: " + string(mustJSON(command)) + "}));"
			field = "input.code"
		}
		if tool == "js" {
			source = map[string]string{"code": "const example = '真实正文';"}
			field = "input.code"
		}
		raw, _ := json.Marshal(source)
		p := contentPolicy(true, CaptureScope{CommandBody: true, MaxFragmentBytes: 8192, MaxEventBytes: 16384})
		b := projectBehaviorPolicy(draft{Kind: "tool_call", Tool: tool, Content: raw}, 3, &p)
		if validateBehavior(b) != nil || len(b.Contents) != 1 || b.Contents[0].Field != field || !strings.Contains(b.Contents[0].Text, "真实正文") || strings.Contains(b.Contents[0].Text, "SYNTHETIC-SECRET") || strings.Contains(b.Contents[0].Text, "OMITTED") {
			t.Fatalf("%s: %#v", tool, b)
		}
		p.Capture.CommandBody = false
		if contents, status := projectContents(tool, "tool_call", raw, p); len(contents) != 0 || status != "not_requested" {
			t.Fatal(tool, contents, status)
		}
	}
	for _, command := range []string{"python3 -c 'print(\"真实正文\")'", "printf '真实正文' > sample.txt"} {
		raw, _ := json.Marshal(map[string]string{"cmd": command})
		p := contentPolicy(true, CaptureScope{CommandBody: true})
		b := projectBehaviorPolicy(draft{Kind: "tool_call", Tool: "exec_command", Content: raw}, 3, &p)
		if !b.BodyOmitted || b.Contents[0].Text != command || validateBehavior(b) != nil {
			t.Fatal(b)
		}
	}
	text := strings.Repeat("你", 4000)
	raw, _ := json.Marshal(map[string]string{"stdout": text, "stderr": text})
	p := contentPolicy(true, CaptureScope{ToolOutput: true, MaxFragmentBytes: 8192, MaxEventBytes: 10000})
	contents, status := projectContents("Bash", "tool_result", raw, p)
	if status != "partial" || len(contents) != 2 || len(contents[0].Text) != 8190 || len(contents[1].Text) != 1809 || !utf8.ValidString(contents[1].Text) || validateContents(contents, status, p) != nil {
		t.Fatal(contents, status)
	}
	if validateContents(contents, status, contentPolicy(true, CaptureScope{ToolOutput: true})) == nil {
		t.Fatal("legacy limit was bypassed")
	}
	for _, scope := range []CaptureScope{{MaxFragmentBytes: 255}, {MaxFragmentBytes: 4096, MaxEventBytes: 2048}, {MaxEventBytes: 32769}, {MaxFragmentBytes: -1}} {
		if contentPolicy(true, scope).Valid() {
			t.Fatal("invalid limit accepted", scope)
		}
	}
}
