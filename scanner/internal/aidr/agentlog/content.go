package agentlog

import (
	"encoding/json"
	"errors"
	"strings"
)

func contentAllowed(value, values string) bool {
	for _, candidate := range strings.Split(values, "|") {
		if value == candidate {
			return true
		}
	}
	return false
}

// Content is a source-provided fragment, not a file read or an execution receipt.
// No business file is opened to fill a missing source field.
type Content struct {
	Kind        string `json:"kind"`
	Field       string `json:"source_field"`
	Block       int    `json:"block"`
	Text        string `json:"text"`
	SourceBytes int    `json:"source_bytes"`
	Redacted    bool   `json:"redacted"`
	Truncated   bool   `json:"truncated"`
}

type contentBuilder struct {
	policy  AuditPolicy
	values  []Content
	bytes   int
	partial bool
}

func (c *contentBuilder) add(kind, field string, block int, text string) {
	if text == "" {
		return
	}
	fragmentLimit, eventLimit := c.policy.ContentLimits()
	if len(c.values) >= 4 || c.bytes >= eventLimit {
		c.partial = true
		if len(c.values) > 0 {
			c.values[len(c.values)-1].Truncated = true
		}
		return
	}
	b := &Behavior{Version: 4, Policy: &c.policy}
	value := safeText(text, min(fragmentLimit, eventLimit-c.bytes), b)
	// A byte cut through a masked value must not leave a new credential-shaped
	// suffix that the server would redact again. Shorten the fragment only;
	// never restore source text or increase the byte budget.
	for c.policy.Enabled && redactValues(value) != value {
		at := strings.LastIndexAny(value, " \n\t")
		if at < 0 {
			value = ""
		} else {
			value = value[:at]
		}
		b.Truncated = true
	}
	c.bytes += len(value)
	c.partial = c.partial || b.Truncated
	c.values = append(c.values, Content{Kind: kind, Field: field, Block: block, Text: value, SourceBytes: len(text), Redacted: b.Redacted, Truncated: b.Truncated})
}

func (c *contentBuilder) result(supported bool) ([]Content, string) {
	if len(c.values) > 0 {
		if c.partial {
			return c.values, "partial"
		}
		return c.values, "captured"
	}
	if !supported {
		return nil, "unsupported"
	}
	return nil, "not_provided"
}

func ProjectPrompt(prompt string, policy AuditPolicy) ([]Content, string) {
	if !policy.CollectionEnabled() || policy.Capture == nil || !policy.Capture.Prompt {
		return nil, "not_requested"
	}
	c := contentBuilder{policy: policy}
	c.add("prompt", "hook.prompt", 0, prompt)
	return c.result(true)
}

func projectContents(tool, kind string, raw json.RawMessage, policy AuditPolicy) ([]Content, string) {
	p := policy.Capture
	if p == nil {
		return nil, ""
	}
	if !policy.CollectionEnabled() {
		return nil, "not_requested"
	}
	c := contentBuilder{policy: policy}
	if kind == "tool_call" {
		if category(tool) == "command" || category(tool) == "wrapper" {
			if !p.CommandBody {
				return nil, "not_requested"
			}
			obj := rawObject(raw)
			if category(tool) == "wrapper" {
				text := rawString(raw)
				if text == "" {
					text = rawString(obj["code"])
				}
				c.add("command_body", "input.code", 0, text)
			} else {
				for _, field := range []string{"command", "cmd"} {
					if text := rawString(obj[field]); text != "" {
						c.add("command_body", "input."+field, 0, text)
						break
					}
				}
			}
			return c.result(true)
		}
		if !p.FileBody {
			return nil, "not_requested"
		}
		obj := rawObject(raw)
		switch tool {
		case "Write", "write_file":
			c.add("file_body", "input.content", 0, rawString(obj["content"]))
		case "Edit", "edit_file":
			c.add("file_body", "input.old_string", 0, rawString(obj["old_string"]))
			c.add("file_body", "input.new_string", 0, rawString(obj["new_string"]))
		case "MultiEdit":
			var edits []map[string]json.RawMessage
			if json.Unmarshal(obj["edits"], &edits) == nil {
				for i, edit := range edits {
					if i >= 16 {
						c.partial = true
						break
					}
					c.add("file_body", "input.edits.old_string", i, rawString(edit["old_string"]))
					c.add("file_body", "input.edits.new_string", i, rawString(edit["new_string"]))
				}
			}
		case "apply_patch":
			patch := rawString(raw)
			field := "input.patch"
			if patch == "" {
				patch = rawString(obj["patch"])
			}
			if patch == "" {
				// Codex native apply_patch hooks provide the patch as command.
				patch, field = rawString(obj["command"]), "input.command"
			}
			c.add("file_body", field, 0, patch)
		case "Bash", "exec_command", "shell_command", "Read", "read_file", "rename_file", "move_file", "WebFetch", "fetch":
			return nil, "not_requested"
		default:
			return nil, "unsupported"
		}
		return c.result(true)
	}
	fileResult := tool == "Read" || tool == "read_file"
	if fileResult && !p.FileBody || !fileResult && !p.ToolOutput {
		return nil, "not_requested"
	}
	// A missing reliable call/tool binding cannot classify a file result safely.
	if tool == "" {
		return nil, "unsupported"
	}
	contentKind, source := "tool_output", "result.text"
	if fileResult {
		contentKind, source = "file_body", "result.file.text"
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		c.add(contentKind, source, 0, text)
		return c.result(true)
	}
	obj := rawObject(raw)
	// Claude Read's native text response carries its source in file.content.
	// Keep the existing normalized file-text contract and content budgets.
	if fileResult && rawString(obj["type"]) == "text" {
		file := rawObject(obj["file"])
		if file != nil {
			c.add(contentKind, source, 0, rawString(file["content"]))
			return c.result(true)
		}
	}
	if !fileResult {
		for _, field := range []string{"stdout", "stderr", "output"} {
			c.add(contentKind, "result."+field, 0, rawString(obj[field]))
		}
	}
	var blocks []map[string]json.RawMessage
	if json.Unmarshal(raw, &blocks) != nil {
		_ = json.Unmarshal(obj["content"], &blocks)
	}
	for i, block := range blocks {
		if i >= 16 {
			c.partial = true
			break
		}
		if contentAllowed(rawString(block["type"]), "text|input_text|output_text") {
			field := "result.content.text"
			if fileResult {
				field = "result.file.text"
			}
			c.add(contentKind, field, i, rawString(block["text"]))
		}
	}
	return c.result(len(obj) > 0 && (obj["stdout"] != nil || obj["stderr"] != nil || obj["output"] != nil || obj["content"] != nil) || blocks != nil)
}

func validateContents(values []Content, status string, policy AuditPolicy) error {
	invalid := errors.New("aidr_log_content_invalid")
	if !contentAllowed(status, "not_requested|not_provided|unsupported|captured|partial") || len(values) > 4 || (len(values) > 0) != contentAllowed(status, "captured|partial") {
		return invalid
	}
	fragmentLimit, eventLimit := policy.ContentLimits()
	total := 0
	for _, value := range values {
		if policy.Capture == nil || value.Block < 0 || value.Block > 65535 || value.SourceBytes < 0 || value.SourceBytes > 4<<20 {
			return invalid
		}
		fields := ""
		switch value.Kind {
		case "command_body":
			if policy.Capture.CommandBody {
				fields = "input.command|input.cmd|input.code"
			}
		case "prompt":
			if policy.Capture.Prompt {
				fields = "hook.prompt|message.input"
			}
		case "model_response":
			if policy.Capture.ModelResponse {
				fields = "message.output"
			}
		case "tool_output":
			if policy.Capture.ToolOutput {
				fields = "result.text|result.stdout|result.stderr|result.output|result.content.text"
			}
		case "file_body":
			if policy.Capture.FileBody {
				fields = "input.content|input.old_string|input.new_string|input.edits.old_string|input.edits.new_string|input.patch|input.command|result.file.text"
			}
		}
		check := &Behavior{Version: 4, Policy: &policy}
		if fields == "" || !contentAllowed(value.Field, fields) || safeText(value.Text, fragmentLimit, check) != value.Text || strings.ContainsRune(value.Text, '\x00') {
			return invalid
		}
		total += len(value.Text)
	}
	if total > eventLimit {
		return invalid
	}
	return nil
}
