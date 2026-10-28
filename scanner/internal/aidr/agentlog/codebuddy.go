package agentlog

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"time"
)

type codeBuddyMessage struct {
	ID, Role, Message, Extra string
	CreatedAt                time.Time
}
type codeBuddyExtra struct {
	RequestID, ModelID  string
	SourceContentBlocks json.RawMessage
}
type codeBuddyRequest struct {
	ID, State string
	Messages  []string
}
type codeBuddyIndex struct {
	Messages []struct{ ID, Role string }
	Requests []codeBuddyRequest
}

func codeBuddyTool(name string) string {
	switch name {
	case "execute_command":
		return "Bash"
	case "read_file":
		return "Read"
	case "write_to_file":
		return "Write"
	case "replace_in_file":
		return "Edit"
	case "use_skill":
		return "Skill"
	case "list_files", "list_dir", "search_file":
		return "Glob"
	case "search_content":
		return "Grep"
	case "delete_file", "delete_files":
		return "Delete"
	case "notebook_edit":
		return "NotebookEdit"
	case "notebook_read":
		return "NotebookRead"
	case "todo_write":
		return "TodoWrite"
	case "web_fetch":
		return "WebFetch"
	case "web_search":
		return "WebSearch"
	case "task":
		return "Task"
	case "read_lints":
		return "ReadLints"
	case "preview_url":
		return "PreviewUrl"
	case "create_rule":
		return "CreateRule"
	default:
		return name
	}
}

// IDE MCP calls use one dispatcher; preserve its explicit server/tool identity.
func CodeBuddyToolName(name string, raw json.RawMessage) string {
	if name == "mcp_call_tool" {
		var input struct{ ServerName, ToolName string }
		if json.Unmarshal(raw, &input) == nil && token(input.ServerName) != "" && token(input.ToolName) != "" {
			if full := "mcp__" + input.ServerName + "__" + input.ToolName; token(full) != "" {
				return full
			}
		}
	}
	return codeBuddyTool(name)
}

func NormalizeCodeBuddyInput(raw json.RawMessage) json.RawMessage {
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil || obj == nil {
		return raw
	}
	if path, ok := obj["filePath"]; ok {
		obj["file_path"] = path
	}
	value, _ := json.Marshal(obj)
	return value
}

func codeBuddyResultContent(tool string, raw json.RawMessage) json.RawMessage {
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil {
		return raw
	}
	for _, field := range []string{"errorMessage", "message", "content"} {
		if (field != "content" || tool == "Read") && rawString(obj[field]) != "" {
			return obj[field]
		}
	}
	return raw
}

// Interpret host metadata only, never JSON embedded in generated output text.
func projectCodeBuddyResult(b *Behavior, tool string, raw json.RawMessage) {
	b.Status, b.ExitCode = "unknown", nil
	b.Basis, b.Uncertainty = []string{}, []string{}
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil || obj == nil {
		b.Uncertainty = []string{"host_result_not_provided"}
		return
	}
	invalid, conflict := false, false
	var failure *bool
	for _, key := range []string{"isError", "is_error", "success"} {
		if value, ok := obj[key]; ok {
			var flag bool
			if string(value) == "null" || json.Unmarshal(value, &flag) != nil {
				invalid = true
				continue
			}
			if key == "success" {
				flag = !flag
			}
			if failure != nil && *failure != flag {
				conflict = true
			}
			failure = &flag
		}
	}
	if failure != nil {
		b.Status, b.Basis = "reported_complete", []string{"is_error_false"}
		if *failure {
			b.Status, b.Basis = "reported_error", []string{"is_error_true"}
		}
	}
	if tool == "Bash" {
		if rawCode, exists := obj["exitCode"]; exists {
			var exit int
			if string(rawCode) == "null" || json.Unmarshal(rawCode, &exit) != nil || exit < -2147483648 || exit > 2147483647 {
				invalid = true
			} else {
				if failure != nil && *failure && exit == 0 {
					conflict = true
				}
				b.ExitCode = &exit
				b.Basis = append(b.Basis, "structured_exit_code")
				b.Status = "reported_success"
				if exit != 0 {
					b.Status = "reported_error"
				}
			}
		}
	}
	if invalid || conflict {
		b.Status, b.ExitCode = "unknown", nil
		b.Uncertainty = []string{"result_format_unsupported"}
		if conflict {
			b.Uncertainty = []string{"result_fields_conflict"}
		}
	} else if len(b.Basis) == 0 {
		b.Uncertainty = []string{"host_result_not_provided"}
	}
}

func ProjectCodeBuddyToolEvidence(tool, kind, cwd string, content json.RawMessage, outcome string, policy AuditPolicy) (*Behavior, error) {
	return projectToolEvidence(tool, kind, cwd, codeBuddyResultContent(tool, content), content, outcome, policy, projectCodeBuddyResult)
}

func codeBuddySkillResult(tool string, raw, meta json.RawMessage, policy *AuditPolicy) *SkillUse {
	if tool != "Skill" || rawString(rawObject(meta)["type"]) != "use_skill_tool_result" {
		return nil
	}
	text := rawString(rawObject(meta)["message"])
	const prefix = "Base directory for this skill: "
	if !strings.HasPrefix(text, prefix) {
		return nil
	}
	dir := strings.TrimSuffix(strings.SplitN(strings.TrimPrefix(text, prefix), "\n", 2)[0], "\r")
	if !filepath.IsAbs(dir) || len(dir) > 1000 {
		return nil
	}
	b := &Behavior{Version: 3, Policy: policy}
	path := safeText(filepath.Join(dir, "SKILL.md"), 1024, b)
	if b.Redacted || b.Truncated {
		return nil
	}
	return &SkillUse{Behavior: "invocation", Path: filepath.ToSlash(path), Basis: "result.base_directory", Phase: "host_loaded"}
}

func parseCodeBuddyMessage(raw []byte, id, turn string, complete bool) ([]draft, error) {
	var envelope codeBuddyMessage
	var extra codeBuddyExtra
	var message struct {
		Role    string
		Content []struct {
			Type, Text, ToolCallID, ToolName string
			Args, Result                     json.RawMessage
			IsError                          bool
		}
	}
	if json.Unmarshal(raw, &envelope) != nil || envelope.ID != id || envelope.CreatedAt.IsZero() ||
		json.Unmarshal([]byte(envelope.Message), &message) != nil || json.Unmarshal([]byte(envelope.Extra), &extra) != nil ||
		extra.RequestID != turn || message.Role != envelope.Role || len(message.Content) > 4096 {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	if !complete && envelope.Role != "user" {
		return nil, errors.New("aidr_log_snapshot_pending")
	}
	model := &ModelContext{Model: modelValue(extra.ModelID), Source: "codebuddy.message.extra"}
	if model.empty() {
		model = nil
	}
	content, _ := json.Marshal(message.Content)
	if envelope.Role == "user" && len(extra.SourceContentBlocks) > 0 {
		content = extra.SourceContentBlocks
	}
	phase := "unspecified"
	for _, block := range message.Content {
		if block.Type == "tool-call" {
			phase = "commentary"
		}
	}
	drafts := []draft{}
	if d, ok := messageDraft(envelope.Role, phase, id, turn, content, envelope.CreatedAt); ok {
		d.ModelContext = model
		drafts = append(drafts, d)
	}
	for i, block := range message.Content {
		if block.Type != "tool-call" && block.Type != "tool-result" {
			continue
		}
		if token(block.ToolCallID) == "" || token(block.ToolName) == "" {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		tool := CodeBuddyToolName(block.ToolName, block.Args)
		d := draft{ModelContext: model, Turn: turn, Call: block.ToolCallID, Time: envelope.CreatedAt, Block: i + 1, Outcome: "unknown"}
		if block.Type == "tool-call" {
			if message.Role != "assistant" || !json.Valid(block.Args) {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			d.Kind, d.Tool, d.Content = "tool_call", tool, NormalizeCodeBuddyInput(block.Args)
		} else {
			if message.Role != "tool" || !json.Valid(block.Result) {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			var wrapper map[string]json.RawMessage
			if json.Unmarshal(block.Result, &wrapper) != nil {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			payload := wrapper["result"]
			if len(payload) == 0 {
				payload = block.Result
			}
			tool = CodeBuddyToolName(block.ToolName, payload)
			meta := rawObject(payload)
			if meta == nil {
				meta = map[string]json.RawMessage{}
			}
			for _, key := range []string{"success", "isError", "is_error"} {
				if value, ok := wrapper[key]; ok {
					meta[key] = value
				}
			}
			meta["isError"], _ = json.Marshal(block.IsError)
			d.Kind, d.ResultTool, d.Content, d.ResultProjection = "tool_result", tool, codeBuddyResultContent(tool, payload), projectCodeBuddyResult
			d.ResultMeta, _ = json.Marshal(meta)
			if block.IsError {
				d.Outcome = "error"
			}
		}
		drafts = append(drafts, d)
	}
	return drafts, nil
}
