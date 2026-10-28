package hooks

import (
	"encoding/json"
	"path"
	"regexp"
	"strings"
)

// CommandCondition matches literal argv, never redacted display summaries.
type CommandCondition struct {
	Executable string   `json:"executable"`
	ArgsAll    []string `json:"args_all"`
	ArgsAny    []string `json:"args_any"`
	PathPrefix string   `json:"path_prefix"`
	PipeTo     []string `json:"pipe_to"`
}
type CommandObservation struct {
	Schema     int      `json:"schema_version"`
	Revision   string   `json:"policy_revision"`
	Matched    []string `json:"matched"`
	Unresolved []string `json:"unresolved"`
}

var commandName = regexp.MustCompile(`^[A-Za-z0-9_./+-]{1,128}$`)
var pipeName = regexp.MustCompile(`^[A-Za-z0-9_.+-]{1,128}$`)
var shortFlags = regexp.MustCompile(`^-[A-Za-z]{2,}$`)

func (c *CommandCondition) valid() bool {
	if !commandName.MatchString(c.Executable) || len(c.ArgsAll) > 16 || len(c.ArgsAny) > 16 || len(c.PipeTo) > 8 || len(c.PathPrefix) > 512 {
		return false
	}
	if c.PathPrefix != "" && (!strings.HasPrefix(c.PathPrefix, "/") || path.Clean(c.PathPrefix) != c.PathPrefix) {
		return false
	}
	for _, a := range append(append([]string{}, c.ArgsAll...), c.ArgsAny...) {
		if a == "" || len(a) > 256 || strings.IndexFunc(a, func(r rune) bool { return r < 32 }) >= 0 {
			return false
		}
	}
	for _, a := range c.PipeTo {
		if !pipeName.MatchString(a) {
			return false
		}
	}
	return true
}

type shellPart struct {
	args []string
	op   string
}

func parseCommand(command string) ([]shellPart, bool) {
	if command == "" || len(command) > 32768 {
		return nil, false
	}
	parts := []shellPart{}
	args := []string{}
	var token strings.Builder
	quote := rune(0)
	started := false
	chars := []rune(command)
	flush := func() {
		if started {
			args = append(args, token.String())
			token.Reset()
			started = false
		}
	}
	for i := 0; i < len(chars); i++ {
		c := chars[i]
		if c < 32 && c != '\n' && c != '\t' {
			return nil, false
		}
		if quote != 0 {
			if c == quote {
				quote = 0
			} else if quote == '"' && strings.ContainsRune("$`\\", c) {
				return nil, false
			} else {
				token.WriteRune(c)
			}
			continue
		}
		switch {
		case c == '\'' || c == '"':
			quote = c
			started = true
		case c == '\\':
			i++
			if i == len(chars) || chars[i] == '\n' {
				return nil, false
			}
			token.WriteRune(chars[i])
			started = true
		case strings.ContainsRune("$`<>()[{}~*?#!", c):
			return nil, false
		case strings.ContainsRune(" \t\n;|&", c):
			flush()
			if strings.ContainsRune("\n;|&", c) {
				op := string(c)
				if (c == '|' || c == '&') && i+1 < len(chars) && chars[i+1] == c {
					op += string(c)
					i++
				}
				if len(args) == 0 {
					if (c == '\n' || c == ';') && len(parts) > 0 {
						continue
					}
					return nil, false
				}
				parts = append(parts, shellPart{args, op})
				args = []string{}
			}
		default:
			token.WriteRune(c)
			started = true
		}
	}
	if quote != 0 {
		return nil, false
	}
	flush()
	if len(args) > 0 {
		parts = append(parts, shellPart{args, ""})
	} else if len(parts) > 0 {
		op := parts[len(parts)-1].op
		if op == "|" || op == "&&" || op == "||" {
			return nil, false
		}
	}
	if len(parts) == 0 || len(parts) > 128 {
		return nil, false
	}
	for i, p := range parts {
		name := path.Base(p.args[0])
		pipeShell := (name == "sh" || name == "bash") && len(p.args) == 1 && i > 0 && parts[i-1].op == "|"
		if p.args[0] == "" || strings.Contains(p.args[0], "=") {
			return nil, false
		}
		switch name {
		case "sudo", "env", "sh", "bash", "zsh", "eval", "exec", "command", "xargs", "find", "cd", "source", ".", "time", "nohup", "timeout", "nice", "doas", "busybox", "builtin", "setsid", "if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "function", "select":
			if !pipeShell {
				return nil, false
			}
		}
	}
	return parts, true
}
func commandMatch(c *CommandCondition, command, cwd, decision string) string {
	parts, ok := parseCommand(command)
	if !ok {
		return "unresolved"
	}
	anyMatch := false
	allMatch := true
	for i, p := range parts {
		name := p.args[0]
		if !strings.Contains(c.Executable, "/") {
			name = path.Base(name)
		}
		args := map[string]bool{}
		for _, a := range p.args[1:] {
			args[a] = true
			if shortFlags.MatchString(a) {
				for _, r := range a[1:] {
					args["-"+string(r)] = true
				}
			}
		}
		match := name == c.Executable
		for _, a := range c.ArgsAll {
			match = match && args[a]
		}
		if len(c.ArgsAny) > 0 {
			one := false
			for _, a := range c.ArgsAny {
				one = one || args[a]
			}
			match = match && one
		}
		if match && c.PathPrefix != "" {
			one := false
			all := true
			for _, a := range p.args[1:] {
				if strings.HasPrefix(a, "-") {
					continue
				}
				if !strings.HasPrefix(a, "/") {
					if !strings.HasPrefix(cwd, "/") {
						return "unresolved"
					}
					a = path.Join(cwd, a)
				}
				a = path.Clean(a)
				inPath := a == c.PathPrefix || strings.HasPrefix(a, strings.TrimRight(c.PathPrefix, "/")+"/")
				one = one || inPath
				all = all && inPath
			}
			match = one
			if decision == "allow" {
				match = one && all
			}
		}
		if len(c.PipeTo) > 0 {
			one := false
			if p.op == "|" && i+1 < len(parts) {
				for _, n := range c.PipeTo {
					one = one || path.Base(parts[i+1].args[0]) == n
				}
			}
			match = match && one
		}
		anyMatch = anyMatch || match
		allMatch = allMatch && match
	}
	if (decision == "allow" && allMatch) || (decision != "allow" && anyMatch) {
		return "matched"
	}
	return "unmatched"
}
func shellTool(tool string) bool {
	parts := strings.Split(strings.ToLower(tool), ".")
	switch parts[len(parts)-1] {
	case "bash", "exec", "exec_command", "shell", "runcommand", "run_terminal_cmd", "run_shell_command", "mcp__qw-builtin__mcp_workspace_bash":
		return true
	}
	return false
}
func containsRule(ids []string, id string) bool {
	for _, s := range ids {
		if s == id {
			return true
		}
	}
	return false
}
func (p ToolPolicy) observeCommand(e Event, raw []byte) *CommandObservation {
	has := false
	for _, r := range p.Rules {
		has = has || r.Command != nil
	}
	if !has || e.Kind != "tool.pre" {
		return nil
	}
	o := &CommandObservation{1, p.Revision, []string{}, []string{}}
	if !shellTool(e.Tool) {
		return o
	}
	var fields map[string]json.RawMessage
	var cwd string
	if adapter, ok := hookAdapters[e.Agent]; ok {
		if decoded, err := adapter.Decode(e.Hook, raw); err == nil {
			_ = json.Unmarshal(decoded.Input, &fields)
			cwd = decoded.Cwd
		}
	}
	command := ""
	if e.Agent == "qwenwork" && e.Tool == "mcp__qw-builtin__mcp_workspace_bash" {
		_ = json.Unmarshal(fields["dir_path"], &cwd)
	}
	var c string
	for _, key := range []string{"command", "cmd"} {
		if json.Unmarshal(fields[key], &c) == nil {
			command = c
			break
		}
	}
	for _, r := range p.Rules {
		if r.Command == nil || (r.Agent != "*" && r.Agent != e.Agent) || (r.Tool != "*" && r.Tool != e.Tool) {
			continue
		}
		switch commandMatch(r.Command, command, cwd, r.Decision) {
		case "matched":
			o.Matched = append(o.Matched, r.ID)
		case "unresolved":
			o.Unresolved = append(o.Unresolved, r.ID)
		}
	}
	return o
}
