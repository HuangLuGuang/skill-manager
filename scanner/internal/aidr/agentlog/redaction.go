package agentlog

import (
	"regexp"
	"strings"
)

// AuditPolicy identifies a server-issued policy for one device collection stream.
// Version zero is the initial fail-closed policy, not a server override.
type AuditPolicy struct {
	MessageSchema int             `json:"message_schema,omitempty"`
	Version       string          `json:"version"`
	Enabled       bool            `json:"enabled"`
	Receipt       string          `json:"receipt"`
	Capture       *CaptureScope   `json:"capture,omitempty"`
	Lifecycle     *AuditLifecycle `json:"lifecycle,omitempty"`
}

type AuditLifecycle struct {
	Enabled       bool `json:"enabled"`
	RetentionDays int  `json:"retention_days"`
}

func (p AuditPolicy) CollectionEnabled() bool { return p.Lifecycle == nil || p.Lifecycle.Enabled }

type CaptureScope struct {
	CommandBody      bool `json:"command_body,omitempty"`
	MaxFragmentBytes int  `json:"max_fragment_bytes,omitempty"`
	MaxEventBytes    int  `json:"max_event_bytes,omitempty"`
	ModelResponse    bool `json:"model_response,omitempty"`
	Prompt           bool `json:"prompt"`
	ToolOutput       bool `json:"tool_output"`
	FileBody         bool `json:"file_body"`
}

func (p AuditPolicy) ContentLimits() (int, int) {
	fragment, event := 1024, 2048
	if p.Capture != nil {
		if p.Capture.MaxFragmentBytes != 0 {
			fragment = p.Capture.MaxFragmentBytes
		}
		if p.Capture.MaxEventBytes != 0 {
			event = p.Capture.MaxEventBytes
		}
	}
	return fragment, event
}

func (p AuditPolicy) Equal(other AuditPolicy) bool {
	if p.MessageSchema != other.MessageSchema || p.Version != other.Version || p.Enabled != other.Enabled || p.Receipt != other.Receipt {
		return false
	}
	if (p.Lifecycle == nil) != (other.Lifecycle == nil) || (p.Lifecycle != nil && *p.Lifecycle != *other.Lifecycle) {
		return false
	}
	if p.Capture == nil || other.Capture == nil {
		return p.Capture == other.Capture
	}
	return *p.Capture == *other.Capture
}

func DefaultAuditPolicy() AuditPolicy { return AuditPolicy{Version: "0", Enabled: true} }

var policyVersion = regexp.MustCompile(`^[1-9][0-9]{0,18}$`)
var policyReceipt = regexp.MustCompile(`^[0-9a-f]{32}$`)

func (p AuditPolicy) Valid() bool {
	fragment, event := p.ContentLimits()
	if fragment < 256 || event < fragment || event > 32768 {
		return false
	}
	if p.MessageSchema < 0 || p.MessageSchema > 1 || (p.MessageSchema == 1 && (p.Capture == nil || p.Version == "0")) {
		return false
	}
	if p.Lifecycle != nil && (p.Capture == nil || p.Lifecycle.RetentionDays < 1 || p.Lifecycle.RetentionDays > 365) {
		return false
	}
	return (p.Version == "0" && p.Enabled && p.Receipt == "" && p.Capture == nil && p.Lifecycle == nil) || (policyVersion.MatchString(p.Version) && policyReceipt.MatchString(p.Receipt))
}

// Capture only explicit credential values. Quotes, labels and shell operators
// remain outside the replacement. Bare prose containing a credential word is not a field.
var valueRules = []*regexp.Regexp{
	regexp.MustCompile(`(?i)((?:--[a-z0-9_-]*(?:token|password|passwd|secret|api[_-]?key|credential)[a-z0-9_-]*[ \t]+|\b[a-z0-9_-]*(?:token|password|passwd|secret|api[_-]?key|credential)[a-z0-9_-]*["']?[ \t]*[:=][ \t]*))("(?:\\.|[^"\\])*"|'[^']*'|(?:\\.|[^\s;,&|<>"'\\])+)`),
	regexp.MustCompile(`(?i)((?:authorization|proxy-authorization|cookie|set-cookie)[ \t]*[:=][ \t]*(?:Bearer[ \t]+|Basic[ \t]+)?)("(?:\\.|[^"\\])*"|'[^']*'|(?:\\.|[^\s;,&|<>"'\\])+)`),
	regexp.MustCompile(`(?i)(\bBearer[ \t]+)([a-z0-9._~+/=-]+)`),
}
var formatRules = []*regexp.Regexp{secretPatterns[0], secretPatterns[4]}
var quotedCookie = regexp.MustCompile(`(?i)(["'](?:cookie|set-cookie)[ \t]*:[ \t]*)([^"'\r\n]*)(["'])`)
var urlPassword = regexp.MustCompile(`(?i)(https?://[^\s/@:]+:)([^\s/@]+)(@)`)

func redactValues(s string) string {
	for _, r := range valueRules {
		s = r.ReplaceAllStringFunc(s, func(v string) string {
			parts := r.FindStringSubmatch(v)
			value := parts[2]
			if value == "[REDACTED]" || value == "\"[REDACTED]\"" || value == "'[REDACTED]'" {
				return v
			}
			if len(value) >= 2 && (value[0] == '\'' || value[0] == '"') {
				value = value[:1] + "[REDACTED]" + value[len(value)-1:]
			} else {
				value = "[REDACTED]"
			}
			return parts[1] + value
		})
	}
	for _, r := range formatRules {
		s = r.ReplaceAllString(s, "[REDACTED]")
	}
	s = urlPassword.ReplaceAllString(s, "${1}[REDACTED]${3}")
	return quotedCookie.ReplaceAllString(s, "${1}[REDACTED]${3}")
}

// Command summaries omit inline payloads. Opt-in command bodies are stored
// separately in protected contents with the configured redaction and byte limits.
var scriptBody = regexp.MustCompile(`(?s)(\b(?:sh|bash|zsh|python[0-9.]*|node|perl|ruby)[ \t]+(?:-c|-e|--eval|--command)[ \t]+|\bclaude[ \t]+(?:-p|--print)[ \t]+|\bcodex[ \t]+exec[ \t]+)("(?:\\.|[^"\\])*"|'[^']*')`)
var inlineBody = regexp.MustCompile(`(?s)(\b(?:echo|printf)[ \t]+|--(?:data|data-raw|data-binary|prompt|body|content)(?:=|[ \t]+))((?:"(?:\\.|[^"\\])*"|'[^']*')(?:[ \t]+(?:"(?:\\.|[^"\\])*"|'[^']*'))*)`)

func boundCommand(s string, b *Behavior) string {
	next := scriptBody.ReplaceAllStringFunc(s, func(v string) string {
		parts := scriptBody.FindStringSubmatch(v)
		q := parts[2]
		if strings.HasPrefix(q[1:len(q)-1], "exit ") && safeShellControl.MatchString(q[1:len(q)-1]) {
			return v
		}
		return parts[1] + "'[BODY OMITTED]'"
	})
	next = inlineBody.ReplaceAllString(next, "${1}'[BODY OMITTED]'")
	if i := strings.Index(next, "<<"); i >= 0 {
		next = next[:i] + "[HEREDOC OMITTED]"
	}
	if next != s {
		b.BodyOmitted = true
	}
	return next
}
