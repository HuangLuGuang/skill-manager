// Package agentlog reads local Agent logs as untrusted, read-only evidence.
package agentlog

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"skill-manager/scanner/internal/aidr/catalog"
	"time"
)

const SchemaVersion = 1
const ParserVersion = "agentlog/1"

// Offsets and generations are strings on the wire to preserve integer precision.
type Source struct {
	ID    string `json:"source_id"`
	Agent string `json:"agent"`
	Root  string `json:"root"`
	Path  string `json:"path"`
}
type Coverage struct {
	Gaps                []Gap    `json:"gaps"`
	GapDetailsTruncated bool     `json:"gap_details_truncated"`
	Status              string   `json:"status"`
	Reasons             []string `json:"reason_codes"`
	Records             int      `json:"records"`
	Ignored             int      `json:"ignored"`
	Filtered            int      `json:"filtered"`
	SkippedBytes        int64    `json:"skipped_bytes"`
	Bytes               int64    `json:"bytes"`
}
type Gap struct {
	Start          int64  `json:"start,string"`
	End            int64  `json:"end,string"`
	Reason         string `json:"reason_code"`
	EvidenceDigest string `json:"evidence_digest,omitempty"`
}

func (c *Coverage) gap(start, end int64, reason string) {
	c.mark("partial", reason)
	if n := len(c.Gaps); n > 0 && c.Gaps[n-1].Start == start && c.Gaps[n-1].Reason == reason {
		c.Gaps[n-1].End = end
		return
	}
	if len(c.Gaps) < 32 {
		c.Gaps = append(c.Gaps, Gap{Start: start, End: end, Reason: reason})
	} else {
		c.GapDetailsTruncated = true
	}
}

func (c *Coverage) mark(status, reason string) {
	if c.Status == "" || c.Status == "complete" || status == "unavailable" {
		c.Status = status
	}
	for _, old := range c.Reasons {
		if old == reason {
			return
		}
	}
	c.Reasons = append(c.Reasons, reason)
}

type CallTurn struct {
	Call          string `json:"call"`
	Turn          string `json:"turn"`
	Tool          string `json:"tool,omitempty"`
	Ambiguous     bool   `json:"ambiguous"`
	Completed     bool   `json:"completed,omitempty"`
	ContentDigest string `json:"content_digest,omitempty"`
}
type Cursor struct {
	TraeHooks                map[string]int64 `json:"trae_hooks,omitempty"`
	TraeInput                string           `json:"trae_input,omitempty"`
	DoubaoMessages           bool             `json:"doubao_messages,omitempty"`
	DoubaoTurns              string           `json:"doubao_turns,omitempty"`
	CompletionSchema         int              `json:"completion_schema,omitempty"`
	ScanComplete             bool             `json:"scan_complete,omitempty"`
	QoderLinks               []QoderLink      `json:"qoder_links,omitempty"`
	ModelHeaderRead          bool             `json:"model_header_read,omitempty"`
	ModelContext             *ModelContext    `json:"model_context,omitempty"`
	ModelProvider            string           `json:"model_provider,omitempty"`
	ModelTurn                string           `json:"model_turn,omitempty"`
	ContextRepairVersion     int              `json:"context_repair_version,omitempty"`
	ContextRepair            *Cursor          `json:"context_repair,omitempty"`
	RecoveryGaps             []Gap            `json:"recovery_gaps,omitempty"`
	RecoveryDetailsTruncated bool             `json:"recovery_details_truncated,omitempty"`
	ProjectionVersion        int              `json:"projection_version,omitempty"`
	CallTurns                []CallTurn       `json:"call_turns,omitempty"`
	SchemaVersion            int              `json:"schema_version"`
	ParserVersion            string           `json:"parser_version"`
	SourceID                 string           `json:"source_id"`
	FileIdentity             string           `json:"file_identity"`
	Generation               uint64           `json:"generation,string"`
	Discarding               bool             `json:"discarding_oversized_record"`
	DiscardStart             int64            `json:"discard_start,string"`
	Offset                   int64            `json:"offset,string"`
	Anchor                   string           `json:"anchor"`
	Session                  string           `json:"session_id"`
	Turn                     string           `json:"turn_id"`
	AgentVersion             string           `json:"agent_version"`
	Since                    time.Time        `json:"since"`
	Gaps                     []string         `json:"gap_codes"`
}
type Event struct {
	Completion         *ToolCompletion `json:"completion,omitempty"`
	ModelContext       *ModelContext   `json:"model_context,omitempty"`
	UserScope          string          `json:"user_scope,omitempty"`
	SkillUse           *SkillUse       `json:"skill_use,omitempty"`
	Message            *Message        `json:"message,omitempty"`
	PreviousLogicalIDs []string        `json:"-"`
	Behavior           *Behavior       `json:"behavior,omitempty"`
	SchemaVersion      int             `json:"schema_version"`
	LogicalEventID     string          `json:"logical_event_id"`
	EventID            string          `json:"event_id"`
	SourceID           string          `json:"source_id"`
	SourceInstanceID   string          `json:"source_instance_id"`
	SourceSeq          int64           `json:"source_seq,string"`
	RecordOffset       int64           `json:"record_offset,string"`
	Block              int             `json:"block"`
	Agent              string          `json:"agent"`
	AgentVersion       string          `json:"agent_version"`
	Source             string          `json:"source"`
	SessionID          string          `json:"session_id"`
	TurnID             string          `json:"turn_id"`
	CallID             string          `json:"native_call_id"`
	LogicalCallID      string          `json:"logical_call_id"`
	Kind               string          `json:"kind"`
	Tool               string          `json:"tool"`
	Outcome            string          `json:"outcome"`
	ObservedAtSource   string          `json:"observed_at_source,omitempty"`
	ObservedAt         time.Time       `json:"observed_at"`
	ReceivedAt         time.Time       `json:"received_at"`
	ContentDigest      string          `json:"content_digest"`
	ContentBytes       int             `json:"content_bytes"`
	EvidenceDigest     string          `json:"evidence_digest"`
	ProcessRelation    string          `json:"process_relation"`
}
type ReadBatch struct {
	TurnLinks     []TurnLink `json:"turn_links,omitempty"`
	SchemaVersion int        `json:"schema_version"`
	Source        Source     `json:"source"`
	Events        []Event    `json:"events"`
	Cursor        Cursor     `json:"cursor"`
	Coverage      Coverage   `json:"coverage"`
}

// ToolCompletion is host-reported lifecycle evidence, not a Hook or tool output.
type ToolCompletion struct {
	Source   string `json:"source"`
	Status   string `json:"status"`
	ExitCode *int32 `json:"exit_code,omitempty"`
}

// TurnLink enriches retained evidence without replaying its captured content.
type TurnLink struct {
	LogicalEventID string `json:"logical_event_id"`
	SessionID      string `json:"session_id"`
	CallID         string `json:"native_call_id"`
	TurnID         string `json:"turn_id"`
	ContentDigest  string `json:"content_digest"`
	MessagePhase   string `json:"message_phase,omitempty"`
}

func ValidateTurnLink(link TurnLink) bool {
	for _, h := range []string{link.LogicalEventID, link.ContentDigest} {
		if decoded, err := hex.DecodeString(h); err != nil || len(decoded) != 32 {
			return false
		}
	}
	return token(link.SessionID) != "" && token(link.CallID) != "" && token(link.TurnID) != "" && (link.MessagePhase == "" || link.MessagePhase == "commentary" || link.MessagePhase == "final")
}

type Budget struct {
	Bytes     int64
	Events    int
	LineBytes int
	Duration  time.Duration
	// Local resume boundary, not part of the platform policy or source cursor.
	CollectionResumeAt time.Time
	RetainedTurns      map[string]string
}

func DefaultBudget() Budget {
	return Budget{Bytes: 4 << 20, Events: 500, LineBytes: 2 << 20, Duration: time.Second}
}
func (b Budget) valid() bool {
	return b.Bytes > 0 && b.Bytes <= 64<<20 && b.Events > 0 && b.Events <= 4096 && b.LineBytes > 0 && b.LineBytes <= 4<<20 && b.Duration > 0 && b.Duration <= time.Minute
}
func digest(parts ...string) string {
	h := sha256.New()
	for _, p := range parts {
		data, _ := json.Marshal(p)
		h.Write(data)
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}
func validAgent(agent string) bool { return catalog.Log(agent) }
func ValidateCursor(c Cursor, s Source) error {
	if c.ContextRepairVersion < 0 || c.ContextRepairVersion > contextRepairVersion {
		return errors.New("aidr_log_cursor_invalid")
	}
	if r := c.ContextRepair; r != nil {
		if r.ContextRepair != nil || r.Offset > c.Offset || r.FileIdentity != c.FileIdentity || ValidateCursor(*r, s) != nil {
			return errors.New("aidr_log_cursor_invalid")
		}
	}
	if c.ProjectionVersion < 0 || c.ProjectionVersion > 2 || c.DiscardStart < 0 || c.DiscardStart > c.Offset || len(c.FileIdentity) > 128 || c.Since.IsZero() {
		return errors.New("aidr_log_cursor_invalid")
	}
	if decoded, err := hex.DecodeString(c.Anchor); err != nil || len(decoded) != 32 {
		return errors.New("aidr_log_cursor_invalid")
	}
	for _, gap := range c.Gaps {
		if len(gap) > 80 || token(gap) == "" {
			return errors.New("aidr_log_cursor_invalid")
		}
	}

	if c.SchemaVersion != SchemaVersion || c.ParserVersion != ParserVersion || c.SourceID != s.ID || c.Offset < 0 || c.FileIdentity == "" || c.Generation == 0 || len(c.Gaps) > 32 || len(c.Session) > 256 || len(c.Turn) > 256 || len(c.AgentVersion) > 80 {
		return errors.New("aidr_log_cursor_invalid")
	}
	if len(c.CallTurns) > maxToolBindings {
		return errors.New("aidr_log_cursor_invalid")
	}
	if len(c.QoderLinks) > maxQoderLinks {
		return errors.New("aidr_log_cursor_invalid")
	}
	seenLinks := map[string]bool{}
	for _, link := range c.QoderLinks {
		if token(link.ID) == "" || token(link.Turn) == "" || seenLinks[link.ID] {
			return errors.New("aidr_log_cursor_invalid")
		}
		seenLinks[link.ID] = true
	}
	if len(c.RecoveryGaps) > 32 {
		return errors.New("aidr_log_cursor_invalid")
	}
	for _, gap := range c.RecoveryGaps {
		decoded, err := hex.DecodeString(gap.EvidenceDigest)
		if gap.Start < 0 || gap.End < gap.Start || gap.End > c.Offset || token(gap.Reason) == "" || err != nil || len(decoded) != 32 {
			return errors.New("aidr_log_cursor_invalid")
		}
	}
	seenCalls := make(map[string]bool, len(c.CallTurns))
	for _, binding := range c.CallTurns {
		if seenCalls[binding.Call] {
			return errors.New("aidr_log_cursor_invalid")
		}
		seenCalls[binding.Call] = true
		if binding.ContentDigest != "" {
			if decoded, err := hex.DecodeString(binding.ContentDigest); err != nil || len(decoded) != 32 {
				return errors.New("aidr_log_cursor_invalid")
			}
		}
		if token(binding.Call) == "" || len(binding.Turn) > 256 || (binding.Tool != "" && token(binding.Tool) == "") {
			return errors.New("aidr_log_cursor_invalid")
		}
	}
	return nil
}

// ValidateEvent is the local ingestion envelope contract. Device
// authentication and upload ACK belong to the later authenticated transport.
func ValidateEvent(e Event) error {
	if e.ObservedAtSource != "" && (e.ObservedAtSource != "collection" || e.Agent != "doubaowork") {
		return errors.New("aidr_log_event_invalid")
	}
	if e.Completion != nil && (e.Agent != "codex" || e.SchemaVersion != 2 || e.Kind != "tool_result" || token(e.Tool) == "" || token(e.SessionID) == "" || token(e.TurnID) == "" || e.Outcome != "unknown" || e.Behavior == nil || e.Behavior.Policy == nil || e.Behavior.Policy.CompletionSchema < 1 || (e.Tool == "Bash" && e.Behavior.Policy.CompletionSchema < 2) || (e.Completion.ExitCode != nil && e.Tool != "Bash") || e.Completion.Source != "codex.item_completed" || (e.Completion.Status != "failed" && e.Completion.Status != "completed")) {
		return errors.New("aidr_log_completion_invalid")
	}
	if !e.ModelContext.valid(e.Agent) || (e.ModelContext != nil && (e.SessionID == "" || (e.Agent == "codex" && e.TurnID == ""))) {
		return errors.New("aidr_log_model_context_invalid")
	}
	if e.SchemaVersion == 3 {
		if e.Behavior != nil || e.Message == nil || validateMessage(e.Message, e.Kind) != nil {
			return errors.New("aidr_log_message_invalid")
		}
	} else if e.Message != nil {
		return errors.New("aidr_log_message_invalid")
	}

	if (e.SchemaVersion == 1 && e.Behavior != nil) || (e.SchemaVersion == 2 && (e.Behavior == nil || validateBehavior(e.Behavior) != nil)) {
		return errors.New("aidr_log_event_invalid")
	}
	hashes := []string{e.EventID, e.LogicalEventID, e.SourceID, e.SourceInstanceID, e.LogicalCallID, e.ContentDigest, e.EvidenceDigest}
	for _, s := range hashes {
		b, err := hex.DecodeString(s)
		if err != nil || len(b) != 32 {
			return errors.New("aidr_log_event_invalid")
		}
	}
	if (e.SchemaVersion != 1 && e.SchemaVersion != 2 && e.SchemaVersion != 3) || !validAgent(e.Agent) || e.Source != "agent_log" || e.ProcessRelation != "unknown" || e.SourceSeq < 0 || e.RecordOffset < 0 || e.Block < 0 || int64(e.Block) != e.SourceSeq-e.RecordOffset || e.ContentBytes < 1 || e.ContentBytes > 4<<20 || e.ObservedAt.IsZero() || e.ReceivedAt.IsZero() || token(e.CallID) == "" || len(e.AgentVersion) > 80 {
		return errors.New("aidr_log_event_invalid")
	}
	if (e.Kind != "tool_call" && e.Kind != "tool_result" && !(e.SchemaVersion == 3 && (e.Kind == "user_message" || e.Kind == "assistant_message"))) || (e.Kind == "tool_call" && token(e.Tool) == "") || (e.Outcome != "unknown" && e.Outcome != "success" && e.Outcome != "error") {
		return errors.New("aidr_log_event_invalid")
	}
	return nil
}
