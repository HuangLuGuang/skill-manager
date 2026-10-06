package agentlog

import (
	"encoding/json"
	"errors"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Behavior contains only bounded, policy-filtered intent and result metadata.
// A declared operation and a log result never prove an OS operation occurred.
type Target struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}
type Action struct {
	Tool     string   `json:"tool"`
	Category string   `json:"category"`
	Command  string   `json:"command,omitempty"`
	Cwd      string   `json:"cwd,omitempty"`
	Targets  []Target `json:"targets"`
	Fields   []string `json:"source_fields"`
}
type Behavior struct {
	Contents      []Content    `json:"contents,omitempty"`
	ContentStatus string       `json:"content_status,omitempty"`
	Policy        *AuditPolicy `json:"policy,omitempty"`
	BodyOmitted   bool         `json:"body_omitted,omitempty"`
	Version       int          `json:"version"`
	Category      string       `json:"category"`
	Method        string       `json:"method"`
	Actions       []Action     `json:"actions"`
	Status        string       `json:"status"`
	ExitCode      *int         `json:"exit_code,omitempty"`
	Basis         []string     `json:"result_basis"`
	Redacted      bool         `json:"redacted"`
	Truncated     bool         `json:"truncated"`
	Uncertainty   []string     `json:"uncertainty"`
}

var secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?is)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)`),
	regexp.MustCompile(`(?i)(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*[^\r\n]+`),
	regexp.MustCompile(`(?i)(?:[A-Za-z0-9_]*(?:token|password|passwd|secret|api[_-]?key|credential)[A-Za-z0-9_]*["']?\s*(?:=|:|\s)\s*)(?:"(?:\\.|[^"\\])*"|'[^']*'|[^\s;,]+)`),
	regexp.MustCompile(`(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+`),
	regexp.MustCompile(`\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b`),
	regexp.MustCompile(`(?i)https?://[^\s/@]+:[^\s/@]+@`),
	regexp.MustCompile(`\?[^\s"']+`),
}

func safeText(s string, limit int, b *Behavior) string {
	original := s
	if b.Version >= 3 {
		if b.Policy == nil || b.Policy.Enabled {
			s = redactValues(s)
		}
	} else {
		for _, pattern := range secretPatterns {
			s = pattern.ReplaceAllString(s, "[REDACTED]")
		}
	}
	// Control characters cannot create misleading rows or terminal escape effects.
	s = strings.Map(func(r rune) rune {
		if r < 32 && r != '\n' && r != '\t' {
			return -1
		}
		return r
	}, s)
	if s != original {
		b.Redacted = true
	}
	if len(s) > limit {
		s = s[:limit]
		for !utf8.ValidString(s) {
			s = s[:len(s)-1]
		}
		b.Truncated = true
	}
	return s
}

var shellQuoted = regexp.MustCompile("(?s)\"(?:\\\\.|[^\"\\\\])*\"|'[^']*'")
var safeShellControl = regexp.MustCompile(`^(?:exit [0-9]{1,3}|%[sd](?:\\n)?)$`)

func safeCommand(s string, b *Behavior) string {
	if b.Version >= 3 {
		return safeText(boundCommand(s, b), 1536, b)
	}
	// Secret replacement can change quote boundaries. Normalize to a fixed
	// point before persistence so the server applies the same payload boundary.
	for i := 0; i < 8; i++ {
		next := redactCommandPass(s, b)
		if next == s {
			return next
		}
		s = next
	}
	b.Redacted = true
	return "[REDACTED COMMAND]"
}
func redactCommandPass(s string, b *Behavior) string {
	s = safeText(s, 1<<22, b)
	if i := strings.Index(s, "<<"); i >= 0 {
		s = s[:i] + "[REDACTED HEREDOC]"
		b.Redacted = true
	}
	// Quoted payloads may contain prompts, file bodies or secrets without a label.
	// Keep explicit path literals and versioned control syntax; hide quoted bodies.
	s = shellQuoted.ReplaceAllStringFunc(s, func(q string) string {
		v := q[1 : len(q)-1]
		if (b.Version >= 2 && safeShellControl.MatchString(v)) || ((strings.HasPrefix(v, "/") || strings.HasPrefix(v, "./")) && !strings.ContainsAny(v, "\r\n")) {
			return q
		}
		b.Redacted = true
		return "'[REDACTED]'"
	})
	return safeText(s, 1536, b)
}
func rawObject(raw json.RawMessage) map[string]json.RawMessage {
	var str string
	if json.Unmarshal(raw, &str) == nil {
		raw = []byte(str)
	}
	var obj map[string]json.RawMessage
	_ = json.Unmarshal(raw, &obj)
	return obj
}
func rawString(raw json.RawMessage) string { var s string; _ = json.Unmarshal(raw, &s); return s }
func category(tool string) string {
	switch tool {
	case "Bash", "exec_command", "shell_command":
		return "command"
	case "Read", "read_file":
		return "file_read"
	case "Write", "write_file":
		return "file_write"
	case "Edit", "MultiEdit", "edit_file":
		return "file_edit"
	case "rename_file", "move_file":
		return "file_rename"
	case "WebFetch", "fetch":
		return "network_request"
	case "apply_patch":
		return "patch"
	case "exec", "js":
		return "wrapper"
	}
	return "unknown"
}
func directAction(tool string, raw json.RawMessage, b *Behavior) Action {
	a := Action{Tool: tool, Category: category(tool), Targets: []Target{}, Fields: []string{}}
	obj := rawObject(raw)
	field := func(keys ...string) string {
		for _, k := range keys {
			if v := rawString(obj[k]); v != "" {
				a.Fields = append(a.Fields, k)
				return v
			}
		}
		return ""
	}
	switch a.Category {
	case "command":
		a.Command = safeCommand(field("command", "cmd"), b)
		a.Cwd = safeText(field("workdir", "cwd"), 512, b)
	case "file_read", "file_write", "file_edit":
		if v := field("file_path", "path"); v != "" {
			a.Targets = append(a.Targets, Target{"file", safeText(v, 512, b)})
		}
	case "file_rename":
		for _, k := range []string{"old_path", "new_path"} {
			if v := field(k); v != "" {
				a.Targets = append(a.Targets, Target{k, safeText(v, 512, b)})
			}
		}
	case "network_request":
		if v := field("url"); v != "" {
			a.Targets = append(a.Targets, Target{"url", safeText(v, 512, b)})
		}
	case "patch":
		patch := rawString(raw)
		if patch == "" {
			patch = field("patch", "command")
		}
		for _, line := range strings.Split(patch, "\n") {
			for _, prefix := range []string{"*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "} {
				if strings.HasPrefix(line, prefix) {
					if len(a.Targets) == 4 {
						b.Truncated = true
						continue
					}
					a.Targets = append(a.Targets, Target{"file", safeText(strings.TrimPrefix(line, prefix), 512, b)})
					a.Fields = append(a.Fields, "patch.header")
				}
			}
		}
	}
	return a
}

// Scan JavaScript lexical boundaries, excluding comments and string literals.
// Only restricted literal arguments of explicitly named tools are extracted. Calls
// inside branches/functions are declared intentions, never execution evidence.
func wrapperActions(code string, b *Behavior) []Action {
	actions := []Action{}
	// A single const literal forwarded to apply_patch is a verified wrapper
	// shape. No substitution is attempted in arbitrary JavaScript programs.
	declaration := regexp.MustCompile(`^\s*const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*`)
	if match := declaration.FindStringSubmatchIndex(code); match != nil {
		arg, n, err := literalJSON(code[match[1]:])
		name := code[match[2]:match[3]]
		tail := strings.TrimSpace(code[match[1]+n:])
		expected := regexp.MustCompile(`^;\s*text\(await tools\.apply_patch\(` + regexp.QuoteMeta(name) + `\)\);?\s*$`)
		if err == nil && expected.MatchString(tail) {
			return []Action{directAction("apply_patch", arg, b)}
		}
	}
	for i := 0; i < len(code); {
		if code[i] == '\'' || code[i] == '"' || code[i] == '`' {
			quote := code[i]
			i++
			for i < len(code) {
				if code[i] == '\\' {
					i += 2
					continue
				}
				if code[i] == quote {
					i++
					break
				}
				i++
			}
			continue
		}
		if strings.HasPrefix(code[i:], "//") {
			if n := strings.IndexByte(code[i:], '\n'); n >= 0 {
				i += n + 1
			} else {
				break
			}
			continue
		}
		if strings.HasPrefix(code[i:], "/*") {
			if n := strings.Index(code[i+2:], "*/"); n >= 0 {
				i += n + 4
			} else {
				break
			}
			continue
		}
		if code[i] == '/' {
			i++
			for i < len(code) {
				if code[i] == '\\' {
					i += 2
					continue
				}
				if code[i] == '/' {
					i++
					break
				}
				i++
			}
			continue
		}
		if strings.HasPrefix(code[i:], "tools.") && (i == 0 || !strings.ContainsRune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$.", rune(code[i-1]))) {
			end := i + 6
			for end < len(code) && strings.ContainsRune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", rune(code[end])) {
				end++
			}
			name := code[i+6 : end]
			j := end
			for j < len(code) && strings.ContainsRune(" \r\n\t", rune(code[j])) {
				j++
			}
			if j < len(code) && code[j] == '(' && category(name) != "unknown" && category(name) != "wrapper" {
				arg, consumed, err := literalJSON(code[j+1:])
				if err == nil {
					n := j + 1 + consumed
					rest := strings.TrimLeft(code[n:], " \r\n\t")
					if strings.HasPrefix(rest, ")") || strings.HasPrefix(rest, ",") {
						if len(actions) < 4 {
							actions = append(actions, directAction(name, arg, b))
						} else {
							b.Truncated = true
						}
						i = n
						continue
					}
				}
			}
		}
		i++
	}
	return actions
}
func projectBehavior(d draft) *Behavior { return projectBehaviorVersion(d, 2) }

func projectBehaviorVersion(d draft, version int) *Behavior {
	return projectBehaviorPolicy(d, version, nil)
}
func projectBehaviorPolicy(d draft, version int, policy *AuditPolicy) *Behavior {
	if policy != nil && policy.Capture != nil {
		version = 4
		if policy.Lifecycle != nil {
			version = 5
		}
	}
	b := &Behavior{Policy: policy, Version: version, Category: "unknown", Method: "unsupported", Actions: []Action{}, Status: "unknown", Basis: []string{}, Uncertainty: []string{}}
	if version >= 4 {
		tool := d.Tool
		if tool == "" {
			tool = d.ResultTool
		}
		b.Contents, b.ContentStatus = projectContents(tool, d.Kind, d.Content, *policy)
	}
	if d.Kind == "tool_call" {
		b.Category = category(d.Tool)
		if b.Category == "wrapper" {
			b.Method = "literal_wrapper"
			code := rawString(d.Content)
			if d.Tool == "js" {
				code = rawString(rawObject(d.Content)["code"])
			}
			b.Actions = wrapperActions(code, b)
			b.Uncertainty = append(b.Uncertainty, "wrapper_execution_unknown")
		} else if b.Category != "unknown" {
			b.Method = "direct_fields"
			a := directAction(d.Tool, d.Content, b)
			if a.Cwd == "" && d.Cwd != "" {
				a.Cwd = safeText(d.Cwd, 512, b)
				a.Fields = append(a.Fields, "record.cwd")
			}
			b.Actions = append(b.Actions, a)
		}
		if len(b.Actions) == 0 {
			b.Uncertainty = append(b.Uncertainty, "unsupported_arguments")
		}
	} else {
		b.Method = "result_fields"
		if d.Outcome == "success" {
			b.Status = "reported_complete"
			b.Basis = append(b.Basis, "is_error_false")
		}
		if d.Outcome == "error" {
			b.Status = "reported_error"
			b.Basis = append(b.Basis, "is_error_true")
		}
		// Result bodies are not retained; inspect only structured top-level fields.
		objects := []map[string]json.RawMessage{}
		if obj := rawObject(d.ResultMeta); obj != nil {
			objects = append(objects, obj)
		}
		if d.HookResult {
			var obj map[string]json.RawMessage
			if json.Unmarshal(d.Content, &obj) == nil && obj != nil {
				objects = append(objects, obj)
			}
		} else if obj := rawObject(d.Content); obj != nil {
			objects = append(objects, obj)
		}
		var blocks []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		}
		if !d.HookResult && json.Unmarshal(d.Content, &blocks) == nil {
			for _, v := range blocks {
				if v.Type == "text" || v.Type == "input_text" {
					if obj := rawObject(json.RawMessage(mustJSON(v.Text))); obj != nil {
						objects = append(objects, obj)
					}
				}
			}
		}
		unsupportedResult := len(objects) > 8
		if len(objects) > 8 {
			objects = objects[:8]
			b.Truncated = true
		}
		codes := []int{}
		if d.Outcome == "error" && (!d.HookResult || d.Tool == "Bash" || d.Tool == "PowerShell") {
			if header := regexp.MustCompile(`^Exit code (-?[0-9]+)(?:\n|$)`).FindStringSubmatch(rawString(d.Content)); header != nil {
				if code, err := strconv.Atoi(header[1]); err == nil && code >= -2147483648 && code <= 2147483647 {
					codes = append(codes, code)
					b.Basis = append(b.Basis, "error_exit_header")
				}
			}
		}
		for _, obj := range objects {
			if d.HookResult {
				for _, unsupported := range []string{"exitCode", "exit_status", "success", "is_error", "isError"} {
					if _, exists := obj[unsupported]; exists {
						unsupportedResult = true
					}
				}
			}
			var code int
			if raw, ok := obj["exit_code"]; ok && string(raw) != "null" && json.Unmarshal(raw, &code) == nil && code >= -2147483648 && code <= 2147483647 {
				codes = append(codes, code)
			} else if _, exists := obj["exit_code"]; exists {
				unsupportedResult = true
			}
			for _, key := range []string{"cancelled", "interrupted"} {
				var flag bool
				if raw, exists := obj[key]; exists && json.Unmarshal(raw, &flag) != nil {
					unsupportedResult = true
				}
				if json.Unmarshal(obj[key], &flag) == nil && flag {
					b.Status = "reported_cancelled"
					if !slices.Contains(b.Basis, key) {
						b.Basis = append(b.Basis, key)
					}
				}
			}
		}
		conflict := false
		for _, code := range codes {
			if code != codes[0] {
				conflict = true
			}
		}
		if len(codes) > 0 && ((d.Outcome == "error" && codes[0] == 0) || (d.Outcome == "success" && codes[0] != 0)) {
			conflict = true
		}
		if len(codes) > 0 && !conflict {
			b.ExitCode = &codes[0]
			if !slices.Contains(b.Basis, "error_exit_header") {
				b.Basis = append(b.Basis, "structured_exit_code")
			}
			if b.Status != "reported_cancelled" {
				if codes[0] == 0 {
					b.Status = "reported_success"
				} else {
					b.Status = "reported_error"
				}
			}
		}
		if conflict {
			b.Status = "unknown"
			b.ExitCode = nil
			b.Uncertainty = append(b.Uncertainty, "result_fields_conflict")
		} else if unsupportedResult {
			b.Status = "unknown"
			b.ExitCode = nil
			b.Uncertainty = append(b.Uncertainty, "result_format_unsupported")
		} else if len(b.Basis) == 0 {
			reason := "result_semantics_unknown"
			if d.HookResult {
				reason = hookMissingResultReason(d.Content)
			}
			b.Uncertainty = append(b.Uncertainty, reason)
		}
	}
	return b
}
func mustJSON(s string) []byte { v, _ := json.Marshal(s); return v }

func validateBehavior(b *Behavior) error {
	invalid := func() error { return errors.New("aidr_log_behavior_invalid") }
	if b.Version < 1 || b.Version > 5 || len(b.Actions) > 4 || len(b.Basis) > 8 || len(b.Uncertainty) > 8 {
		return invalid()
	}
	if (b.Version >= 3 && (b.Policy == nil || !b.Policy.Valid())) || (b.Version < 3 && (b.Policy != nil || b.BodyOmitted)) {
		return invalid()
	}
	if b.Version < 4 && (len(b.Contents) > 0 || b.ContentStatus != "" || (b.Policy != nil && b.Policy.Capture != nil)) {
		return invalid()
	}
	if (b.Version < 5 && b.Policy != nil && b.Policy.Lifecycle != nil) || (b.Version == 5 && b.Policy.Lifecycle == nil) {
		return invalid()
	}
	if b.Version >= 4 && (b.Policy.Capture == nil || validateContents(b.Contents, b.ContentStatus, *b.Policy) != nil) {
		return invalid()
	}
	for _, content := range b.Contents {
		if content.Kind == "command_body" {
			if b.Method == "result_fields" || (b.Category != "command" && b.Category != "wrapper") || (content.Field == "input.code") != (b.Category == "wrapper") {
				return invalid()
			}
		}
		if content.Kind == "file_body" && content.Field == "input.command" {
			patch := false
			for _, action := range b.Actions {
				patch = patch || action.Tool == "apply_patch"
			}
			if b.Category != "patch" || !patch {
				return invalid()
			}
		}
	}
	allowed := func(v string, options string) bool { return strings.Contains("|"+options+"|", "|"+v+"|") }
	if !allowed(b.Category, "unknown|command|file_read|file_write|file_edit|file_rename|network_request|patch|wrapper") || !allowed(b.Method, "unsupported|direct_fields|literal_wrapper|result_fields") || !allowed(b.Status, "unknown|reported_complete|reported_error|reported_success|reported_cancelled") {
		return invalid()
	}
	if b.ExitCode != nil && (*b.ExitCode < -2147483648 || *b.ExitCode > 2147483647) {
		return invalid()
	}
	if b.Status == "reported_success" && (b.ExitCode == nil || *b.ExitCode != 0) {
		return invalid()
	}
	if b.Status == "reported_complete" && !slices.Contains(b.Basis, "is_error_false") {
		return invalid()
	}
	if b.Status == "reported_cancelled" && !slices.Contains(b.Basis, "cancelled") && !slices.Contains(b.Basis, "interrupted") {
		return invalid()
	}
	if b.Status == "reported_error" && !slices.Contains(b.Basis, "is_error_true") && (b.ExitCode == nil || *b.ExitCode == 0) {
		return invalid()
	}
	if b.ExitCode != nil && !slices.Contains(b.Basis, "structured_exit_code") && !slices.Contains(b.Basis, "error_exit_header") {
		return invalid()
	}
	for _, v := range b.Basis {
		if !allowed(v, "is_error_false|is_error_true|structured_exit_code|error_exit_header|cancelled|interrupted") {
			return invalid()
		}
	}
	for _, reason := range b.Uncertainty {
		if (reason == "host_result_not_provided" || reason == "result_format_unsupported" || reason == "result_fields_conflict") && b.Method != "result_fields" {
			return invalid()
		}
		if (reason == "result_format_unsupported" || reason == "result_fields_conflict") && (b.Status != "unknown" || b.ExitCode != nil) {
			return invalid()
		}
		if reason == "host_result_not_provided" && (b.Status != "unknown" || b.ExitCode != nil || len(b.Basis) != 0) {
			return invalid()
		}
	}
	for _, v := range b.Uncertainty {
		if !allowed(v, "wrapper_execution_unknown|unsupported_arguments|multiple_result_codes|result_semantics_unknown|host_result_not_provided|result_format_unsupported|result_fields_conflict") {
			return invalid()
		}
	}
	for _, a := range b.Actions {
		if category(a.Tool) != a.Category || a.Category == "unknown" || a.Category == "wrapper" || len(a.Fields) > 8 || len(a.Targets) > 4 || len(a.Tool) > 128 {
			return invalid()
		}
		check := &Behavior{Version: b.Version, Policy: b.Policy}
		if safeCommand(a.Command, check) != a.Command || len(a.Command) > 1536 || safeText(a.Cwd, 512, check) != a.Cwd {
			return invalid()
		}
		for _, t := range a.Targets {
			if !allowed(t.Kind, "file|url|old_path|new_path") || len(t.Value) == 0 || safeText(t.Value, 512, check) != t.Value {
				return invalid()
			}
		}
		for _, f := range a.Fields {
			if !allowed(f, "command|cmd|workdir|cwd|file_path|path|old_path|new_path|url|patch|patch.header|record.cwd") {
				return invalid()
			}
		}
	}
	return nil
}

// Hook stdout is display text, including text that happens to encode JSON.
// Only a direct host object can carry the structured result contract.
func hookMissingResultReason(raw json.RawMessage) string {
	var text string
	if len(raw) == 0 || string(raw) == "null" || json.Unmarshal(raw, &text) == nil {
		return "host_result_not_provided"
	}
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) == nil && obj != nil {
		known := true
		for key := range obj {
			switch key {
			case "stdout", "stderr", "interrupted", "cancelled", "isImage", "type", "file", "content", "output":
			default:
				known = false
			}
		}
		if known {
			return "host_result_not_provided"
		}
	}
	return "result_format_unsupported"
}
