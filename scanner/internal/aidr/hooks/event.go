// Package hooks adapts host lifecycle evidence without treating it as operating
// system evidence or as a credential authorizing a resource operation.
package hooks

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"slices"
	"strings"
	"unicode"

	"skill-manager/scanner/internal/aidr/agentlog"
)

const MaxRecordBytes = 256 << 10

// Catalog describes adapter schema coverage, not proof that a particular
// installed host has enabled, trusted or emitted these events.
var catalog = map[string]map[string]string{
	"codex": {
		"SessionStart": "session.start", "SessionEnd": "session.end",
		"UserPromptSubmit": "turn.submit", "PreToolUse": "tool.pre",
		"PostToolUse": "tool.post", "PermissionRequest": "permission.request",
		"SubagentStart": "agent.start", "SubagentStop": "agent.stop",
		"PreCompact": "context.compact.start", "PostCompact": "context.compact.end",
		"Stop": "turn.stop", "Interrupt": "turn.interrupt",
	},
	"claude": {
		"SessionStart": "session.start", "SessionEnd": "session.end",
		"UserPromptSubmit": "turn.submit", "PreToolUse": "tool.pre",
		"PostToolUse": "tool.post", "PostToolUseFailure": "tool.failure",
		"PermissionRequest": "permission.request", "PermissionDenied": "permission.denied",
		"SubagentStart": "agent.start", "SubagentStop": "agent.stop",
		"PreCompact": "context.compact.start", "PostCompact": "context.compact.end",
		"Stop": "turn.stop", "Notification": "notification",
		"TaskCompleted": "task.completed", "TeammateIdle": "agent.idle",
	},
}

type Event struct {
	Schema          int                  `json:"schema_version"`
	Agent           string               `json:"agent"`
	Hook            string               `json:"hook_event"`
	Kind            string               `json:"kind"`
	Session         string               `json:"session_id"`
	Turn            string               `json:"turn_id,omitempty"`
	Call            string               `json:"native_call_id,omitempty"`
	Subagent        string               `json:"native_agent_id,omitempty"`
	Tool            string               `json:"tool,omitempty"`
	Behavior        *agentlog.Behavior   `json:"behavior,omitempty"`
	Policy          agentlog.AuditPolicy `json:"policy"`
	Contents        []agentlog.Content   `json:"contents,omitempty"`
	ContentStatus   string               `json:"content_status,omitempty"`
	InputDigest     string               `json:"input_digest,omitempty"`
	EvidenceDigest  string               `json:"evidence_digest"`
	ProcessRelation string               `json:"process_relation"`
}

type input struct {
	Event       string          `json:"hook_event_name"`
	Session     string          `json:"session_id"`
	Turn        string          `json:"turn_id"`
	Prompt      string          `json:"prompt_id"`
	PromptText  string          `json:"prompt"`
	Call        string          `json:"tool_use_id"`
	Subagent    string          `json:"agent_id"`
	Tool        string          `json:"tool_name"`
	Cwd         string          `json:"cwd"`
	Input       json.RawMessage `json:"tool_input"`
	Response    json.RawMessage `json:"tool_response"`
	Error       string          `json:"error"`
	Interrupted bool            `json:"is_interrupt"`
}

func code(s string) error { return errors.New(s) }
func validID(s string, required bool) bool {
	if (required && s == "") || len(s) > 256 {
		return false
	}
	for _, r := range s {
		if unicode.IsControl(r) || unicode.IsSpace(r) {
			return false
		}
	}
	return true
}

func digest(key []byte, domain string, raw []byte) string {
	h := hmac.New(sha256.New, key)
	h.Write([]byte(domain))
	h.Write([]byte{0})
	h.Write(raw)
	return hex.EncodeToString(h.Sum(nil))
}

// Normalize accepts bounded untrusted host JSON. key is a persistent receiver
// secret, not supplied by a plugin: keyed digests avoid exposing low-entropy
// omitted inputs through an offline dictionary of public SHA256 values.
// Only explicitly selected, bounded source fields leave this function. A
// receiver must authenticate its peer independently before persisting them.
func Normalize(agent, hook string, raw []byte, policy agentlog.AuditPolicy, key []byte) (Event, error) {
	e := Event{}
	if len(raw) > MaxRecordBytes {
		return e, code("aidr_hook_record_oversized")
	}
	if len(key) < 32 || !policy.Valid() {
		return e, code("aidr_hook_config_invalid")
	}
	kind, ok := catalog[agent][hook]
	if !ok {
		return e, code("aidr_hook_event_unsupported")
	}
	var in input
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(&in); err != nil {
		return e, code("aidr_hook_record_invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || in.Event != hook {
		return e, code("aidr_hook_record_invalid")
	}
	if !validID(in.Session, true) || !validID(in.Turn, false) || !validID(in.Prompt, false) || !validID(in.Call, false) || !validID(in.Subagent, false) || !validID(in.Tool, false) {
		return e, code("aidr_hook_identity_invalid")
	}
	turn := in.Turn
	// Keep the host namespace: Claude prompt IDs are not Codex turn IDs.
	if agent == "claude" && in.Prompt != "" {
		turn = in.Prompt
	}
	e = Event{Schema: 1, Agent: agent, Hook: hook, Kind: kind, Session: in.Session, Turn: turn, Call: in.Call, Subagent: in.Subagent, Policy: policy, ProcessRelation: "unknown", EvidenceDigest: digest(key, "hook-evidence/1", raw)}
	if policy.Capture != nil {
		e.Schema = 2
		if policy.Lifecycle != nil {
			e.Schema = 3
		}
		e.ContentStatus = "not_requested"
		if kind == "turn.submit" {
			e.Contents, e.ContentStatus = agentlog.ProjectPrompt(in.PromptText, policy)
		}
	}
	if strings.HasPrefix(kind, "tool.") || strings.HasPrefix(kind, "permission.") {
		if in.Tool == "" {
			return Event{}, code("aidr_hook_tool_missing")
		}
		e.Tool = in.Tool
		if len(in.Input) != 0 {
			// Canonicalize object key ordering with json.Number precision before
			// binding an approval to exact arguments. Never shell-normalize them.
			d := json.NewDecoder(bytes.NewReader(in.Input))
			d.UseNumber()
			var value any
			if err := d.Decode(&value); err != nil {
				return Event{}, code("aidr_hook_record_invalid")
			}
			canonical, err := json.Marshal(struct {
				Tool  string `json:"tool"`
				Cwd   string `json:"cwd"`
				Input any    `json:"input"`
			}{in.Tool, in.Cwd, value})
			if err != nil {
				return Event{}, code("aidr_hook_record_invalid")
			}
			e.InputDigest = digest(key, "hook-input/1", canonical)
		}
		toolKind, outcome := "tool_call", "unknown"
		content := in.Input
		if kind == "tool.post" || kind == "tool.failure" {
			toolKind, content = "tool_result", in.Response
			// Arrival of PostToolUse alone is not evidence of success.
			if kind == "tool.failure" {
				outcome = "error"
				content, _ = json.Marshal(in.Error)
			}
		}
		var err error
		e.Behavior, err = agentlog.ProjectToolEvidence(in.Tool, toolKind, in.Cwd, content, nil, outcome, policy)
		if err != nil {
			return Event{}, err
		}
		if in.Interrupted && kind == "tool.failure" && !slices.Contains(e.Behavior.Uncertainty, "result_fields_conflict") && !slices.Contains(e.Behavior.Uncertainty, "result_format_unsupported") {
			e.Behavior.Status = "reported_cancelled"
			e.Behavior.Basis = append(e.Behavior.Basis, "interrupted")
		}
	}
	return e, nil
}

// CallKey is scoped by independently authenticated device/user and native
// identity. Missing call IDs are left uncorrelated. Lifecycle receipt IDs must
// be assigned by the receiver, never by hashing a prompt or timestamp.
func (e Event) CallKey(device, user string) string {
	if device == "" || user == "" || e.Session == "" || e.Call == "" {
		return ""
	}
	b, _ := json.Marshal([]string{device, user, e.Agent, e.Session, e.Subagent, e.Turn, e.Call})
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
