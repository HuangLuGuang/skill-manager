package agentlog

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var traeHookStart = regexp.MustCompile(`^\[([0-9]+)\] \[([a-zA-Z0-9-]+)\] --- Hook Execution Start ---$`)
var traeHookField = regexp.MustCompile(`^\[([a-zA-Z0-9-]+)\] (.*)$`)

func traeLogAdapter() logAdapter {
	a := lineAdapter(normalizeTrae)
	a.SourceFile = func(_, path string) bool { return filepath.Base(path) == "agent-hooks.log" }
	a.SkillField = func(tool string) string {
		if tool == "Skill" {
			return "name"
		}
		return ""
	}
	a.SkillResult = traeSkillResult
	return a
}

func traeSkillResult(tool string, raw, meta json.RawMessage, policy *AuditPolicy) *SkillUse {
	if tool != "Skill" {
		return nil
	}
	directory := rawString(rawObject(raw)["skill_path"])
	if !filepath.IsAbs(directory) {
		return nil
	}
	b := &Behavior{Version: 3, Policy: policy}
	path := safeText(filepath.ToSlash(filepath.Join(directory, "SKILL.md")), 1024, b)
	if b.Redacted || b.Truncated {
		return nil
	}
	return &SkillUse{Behavior: "invocation", Path: path, Basis: "result.metadata", Phase: "host_loaded"}
}

// Native Hook logs contain interleaved execution headers and single-line JSON
// stdin records. Keep bounded header state in the checkpoint across read budgets.
func normalizeTrae(raw []byte, c *Cursor) ([]draft, error) {
	line := strings.TrimSpace(string(raw))
	if m := traeHookStart.FindStringSubmatch(line); m != nil {
		at, err := strconv.ParseInt(m[1], 10, 64)
		if err != nil || at <= 0 {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		if c.TraeHooks == nil {
			c.TraeHooks = map[string]int64{}
		}
		if len(c.TraeHooks) >= 128 {
			return nil, errors.New("aidr_log_call_capacity")
		}
		c.TraeHooks[m[2]] = at
		c.TraeInput = ""
		return nil, nil
	}
	if m := traeHookField.FindStringSubmatch(line); m != nil {
		c.TraeInput = ""
		if m[2] == "stdin:" {
			c.TraeInput = m[1]
		}
		if m[2] == "--- Hook Execution End ---" {
			delete(c.TraeHooks, m[1])
		}
		return nil, nil
	}
	id := c.TraeInput
	c.TraeInput = ""
	if id == "" {
		return nil, nil
	}
	at := c.TraeHooks[id]
	delete(c.TraeHooks, id)
	if at <= 0 {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	var r struct {
		Event    string          `json:"hook_event_name"`
		Session  string          `json:"session_id"`
		Call     string          `json:"tool_use_id"`
		Tool     string          `json:"tool_name"`
		Cwd      string          `json:"cwd"`
		Prompt   json.RawMessage `json:"prompt"`
		Final    json.RawMessage `json:"last_assistant_message"`
		Input    json.RawMessage `json:"tool_input"`
		Response json.RawMessage `json:"tool_response"`
	}
	if json.Unmarshal(raw, &r) != nil {
		return nil, errors.New("aidr_log_invalid_json")
	}
	if token(r.Session) == "" {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	c.Session, c.Turn = r.Session, ""
	timestamp := time.UnixMilli(at).UTC()
	switch r.Event {
	case "UserPromptSubmit", "Stop":
		role, phase, content := "user", "unspecified", r.Prompt
		if r.Event == "Stop" {
			role, phase, content = "assistant", "final", r.Final
		}
		if d, ok := messageDraft(role, phase, id, "", content, timestamp); ok {
			return []draft{d}, nil
		}
	case "PreToolUse", "PostToolUse":
		if token(r.Call) == "" || token(r.Tool) == "" {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		kind, content := "tool_call", r.Input
		if r.Event == "PostToolUse" {
			kind, content = "tool_result", r.Response
		}
		if len(content) == 0 {
			content = json.RawMessage(`{}`)
		}
		return []draft{{Call: r.Call, Kind: kind, Tool: r.Tool, ResultTool: r.Tool, Cwd: r.Cwd, Content: content, Outcome: "unknown", Time: timestamp}}, nil
	case "SessionStart", "Notification":
		return nil, nil
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	return nil, nil
}
