package agentlog

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"time"

	_ "modernc.org/sqlite"

	"skill-manager/scanner/internal/aidr/privatefs"
)

func teleAgentLogAdapter() logAdapter {
	return logAdapter{Read: readTeleAgent, DraftTurn: true, ModelSource: "teleagent.message",
		SourceFile: func(_, path string) bool { return filepath.Base(path) == "teleagent.db" },
		ReadOffset: func(s Source, c Cursor) int64 {
			if c.ScanComplete {
				if info, err := os.Stat(s.Path); err == nil {
					return info.Size()
				}
			}
			return 0
		},
	}
}

// ReadOffset translates a source-specific checkpoint into scheduler progress.
func ReadOffset(s Source, c Cursor) int64 {
	if f := logAdapters[s.Agent].ReadOffset; f != nil {
		return f(s, c)
	}
	return c.Offset
}

type sqlitePartRecord struct {
	ID, Session, Version, Cwd string
	Created                   int64
	Message                   json.RawMessage
	Part                      json.RawMessage
}

// TeleAgent updates existing rows (and the owning message) in place. Bounded
// snapshot cycles revisit rows rather than assuming an append-only timestamp.
// Stable evidence/logical IDs let the common store deduplicate unchanged rows.
func readTeleAgent(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, observer *SkillObserver) (ReadBatch, error) {
	return readSQLiteParts(ctx, s, old, b, since, policy, observer, parseTeleAgent)
}

func readSQLiteParts(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, observer *SkillObserver, parse func(sqlitePartRecord) ([]draft, error)) (ReadBatch, error) {
	out := ReadBatch{SchemaVersion: SchemaVersion, Source: s, Cursor: old, Events: []Event{}, Coverage: Coverage{Status: "complete", Reasons: []string{}}}
	expected, err := NewSource(s.Agent, s.Root, s.Path)
	if err != nil || expected.ID != s.ID || !b.valid() {
		return out, errors.New("aidr_log_request_invalid")
	}
	if old.SchemaVersion != 0 {
		if err := ValidateCursor(old, s); err != nil {
			return out, err
		}
	}
	if err := checkPath(s.Path); err != nil {
		out.Coverage.mark("unavailable", ioReason(err))
		return out, nil
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		if err := checkPath(s.Path + suffix); err != nil && !os.IsNotExist(err) {
			out.Coverage.mark("unavailable", ioReason(err))
			return out, nil
		}
	}
	f, err := openLog(s.Path)
	if err != nil {
		out.Coverage.mark("unavailable", ioReason(err))
		return out, nil
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		out.Coverage.mark("unavailable", "aidr_log_not_regular")
		return out, nil
	}
	identity, err := fileIdentity(f, info)
	if err != nil {
		return out, err
	}
	c := old
	if c.SchemaVersion == 0 {
		if since.IsZero() {
			since = time.Now().Add(-24 * time.Hour)
		}
		c = Cursor{SchemaVersion: SchemaVersion, ParserVersion: ParserVersion, SourceID: s.ID, FileIdentity: identity, Generation: 1, Since: since, ProjectionVersion: 2, ContextRepairVersion: contextRepairVersion, Gaps: []string{}}
	} else if c.ScanComplete || c.FileIdentity != identity {
		if c.Generation == ^uint64(0) {
			return out, errors.New("aidr_log_generation_exhausted")
		}
		c.Generation++
		c.Offset = 0
		c.ScanComplete = false
		c.FileIdentity = identity
	}
	deadline := time.Now().Add(b.Duration)
	work, cancel := context.WithDeadline(ctx, deadline)
	defer cancel()
	dsn := privatefs.SQLiteURI(s.Path, "mode=ro&_pragma=query_only(1)&_pragma=busy_timeout(100)")
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return out, errors.New("aidr_log_io_error")
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	// Limit each metadata envelope independently of the event read budget.
	if b.Events > 128 {
		b.Events = 128
	}
	rows, err := db.QueryContext(work, `SELECT p.rowid,p.id,p.session_id,s.version,s.directory,p.time_created,
 CASE WHEN length(CAST(m.data AS BLOB))<=? THEN m.data ELSE '' END,
 CASE WHEN length(CAST(p.data AS BLOB))<=? THEN p.data ELSE '' END,
 CASE WHEN json_extract(m.data,'$.role')='user' THEN m.id
 WHEN json_extract(m.data,'$.role')='assistant' AND json_extract(parent.data,'$.role')='user' THEN parent.id ELSE '' END
 FROM part p JOIN message m ON m.id=p.message_id AND m.session_id=p.session_id
 LEFT JOIN message parent ON parent.id=json_extract(m.data,'$.parentID') AND parent.session_id=m.session_id
 JOIN session s ON s.id=p.session_id WHERE p.rowid>? ORDER BY p.rowid LIMIT ?`, b.LineBytes, b.LineBytes, c.Offset, b.Events+1)
	if err != nil {
		out.Coverage.mark("unavailable", "aidr_log_schema_unsupported")
		return out, nil
	}
	defer rows.Close()
	exhausted := true
	scanned := 0
	for rows.Next() {
		if time.Now().After(deadline) || out.Coverage.Bytes >= b.Bytes || len(out.Events) >= b.Events {
			exhausted = false
			out.Coverage.mark("partial", "aidr_log_read_budget")
			break
		}
		var row int64
		var r sqlitePartRecord
		var message, part, turn string
		if rows.Scan(&row, &r.ID, &r.Session, &r.Version, &r.Cwd, &r.Created, &message, &part, &turn) != nil {
			return out, errors.New("aidr_log_io_error")
		}
		scanned++
		if row > (1<<63-1)/2 {
			return out, errors.New("aidr_log_schema_unsupported")
		}
		r.Message, r.Part = json.RawMessage(message), json.RawMessage(part)
		if message == "" || part == "" || len(message)+len(part) > b.LineBytes {
			out.Coverage.mark("partial", "aidr_log_record_too_large")
			c.Offset = row
			continue
		}
		if out.Coverage.Bytes+int64(len(message)+len(part)) > b.Bytes {
			exhausted = false
			out.Coverage.mark("partial", "aidr_log_read_budget")
			break
		}
		drafts, err := parse(r)
		if err != nil {
			out.Coverage.mark("partial", err.Error())
			c.Offset = row
			continue
		}
		if len(drafts) > b.Events-len(out.Events) {
			exhausted = false
			out.Coverage.mark("partial", "aidr_log_event_budget")
			break
		}
		candidate := c
		candidate.Session = r.Session
		candidate.AgentVersion = r.Version
		raw, _ := json.Marshal(r)
		position := c
		position.Offset = row * 2
		start := len(out.Events)
		projectDrafts(ctx, s, drafts, &candidate, position, identity, raw, policy, b, observer, deadline, 0, &out)
		for i := start; i < len(out.Events); i++ {
			e := &out.Events[i]
			e.SourceInstanceID = digest(s.ID, identity, "sqlite/1")
			e.EventID = digest("sqlite/1", s.ID, identity, r.ID, strconv.Itoa(e.Block), string(raw))
			if s.Agent == "teleagent" && token(turn) != "" {
				out.TurnLinks = append(out.TurnLinks, TurnLink{e.LogicalEventID, e.SessionID, e.CallID, turn, e.ContentDigest, ""})
			}
		}
		c = candidate
		c.Offset = row
		out.Coverage.Bytes += int64(len(message) + len(part))
		out.Coverage.Records++
		if len(drafts) == 0 {
			out.Coverage.Ignored++
		}
	}
	if scanned >= b.Events+1 {
		exhausted = false
		out.Coverage.mark("partial", "aidr_log_read_budget")
	}
	if rows.Err() != nil {
		exhausted = false
		out.Coverage.mark("partial", "aidr_log_read_budget")
	}
	current, err := os.Lstat(s.Path)
	if err != nil || !os.SameFile(info, current) || checkPath(s.Path) != nil {
		out.Events = nil
		out.Coverage.mark("unavailable", "aidr_log_source_changed")
		return out, nil
	}
	c.ScanComplete = exhausted
	c.Anchor = digest(identity)
	out.Cursor = c
	return out, nil
}

func parseTeleAgent(r sqlitePartRecord) ([]draft, error) {
	var m struct {
		Role, Finish, ModelID, ProviderID string
		Time                              struct{ Created, Completed int64 }
	}
	var p struct {
		Type, Text, CallID, Tool string
		State                    struct {
			Status, Output, Error string
			Input, Metadata       json.RawMessage
			Time                  struct{ Start, End int64 }
		}
	}
	if json.Unmarshal(r.Message, &m) != nil || json.Unmarshal(r.Part, &p) != nil || token(r.Session) == "" || token(r.ID) == "" || len(r.Version) > 80 {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	model := &ModelContext{Model: modelValue(m.ModelID), Provider: modelValue(m.ProviderID), Source: "teleagent.message"}
	if model.empty() {
		model = nil
	}
	switch p.Type {
	case "text":
		if m.Role == "assistant" && m.Time.Completed == 0 {
			return nil, nil
		}
		phase := "unspecified"
		if m.Finish == "stop" {
			phase = "final"
		} else if m.Finish == "tool_calls" {
			phase = "commentary"
		}
		raw, _ := json.Marshal(p.Text)
		if r.Created <= 0 {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		if d, ok := messageDraft(m.Role, phase, r.ID, "", raw, time.UnixMilli(r.Created).UTC()); ok {
			d.ModelContext = model
			return []draft{d}, nil
		}
		return nil, nil
	case "tool":
		if p.State.Status != "completed" && p.State.Status != "error" {
			return nil, nil
		}
		if token(p.CallID) == "" || token(p.Tool) == "" || !json.Valid(p.State.Input) || p.State.Time.Start <= 0 || p.State.Time.End <= 0 {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		content := NormalizeTeleAgentInput(p.State.Input)
		output, outcome := p.State.Output, "success"
		if p.State.Status == "error" {
			output, outcome = p.State.Error, "error"
		}
		body, _ := json.Marshal(output)
		return []draft{{ModelContext: model, Call: p.CallID, Tool: p.Tool, Cwd: r.Cwd, Kind: "tool_call", Content: content, Outcome: "unknown", Time: time.UnixMilli(p.State.Time.Start).UTC()}, {ModelContext: model, Call: p.CallID, ResultTool: p.Tool, Kind: "tool_result", Content: body, ResultMeta: p.State.Metadata, Outcome: outcome, Block: 1, Time: time.UnixMilli(p.State.Time.End).UTC()}}, nil
	case "step-start", "step-finish", "reasoning", "file", "patch", "snapshot", "subtask", "retry", "compaction", "agent":
		return nil, nil
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
}

// The native input is retained for identity digests; this copy supplies the
// standard file target to the common behavior projector.
func NormalizeTeleAgentInput(raw json.RawMessage) json.RawMessage {
	var input map[string]json.RawMessage
	if json.Unmarshal(raw, &input) != nil || input == nil {
		return raw
	}
	if path, ok := input["filePath"]; ok {
		input["file_path"] = path
	}
	result, _ := json.Marshal(input)
	return result
}
