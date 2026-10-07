package agentlog

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// SourceFile selects only primary evidence. OpenCode's storage files are
// mutable JSON snapshots; message/session files supply identity, not events.
func SourceFile(agent, root, path string) bool {
	if agent == "opencode" {
		rel, err := filepath.Rel(root, path)
		return err == nil && strings.HasPrefix(rel, "part"+string(filepath.Separator)) && strings.HasSuffix(path, ".json")
	}
	return strings.HasSuffix(path, ".jsonl")
}
func sourceAnchor(s Source, f *os.File, offset int64) (string, error) {
	if s.Agent != "opencode" {
		return anchor(f, offset)
	}
	if offset > 4<<20 {
		return "", errors.New("aidr_log_record_too_large")
	}
	b := make([]byte, offset)
	_, err := f.ReadAt(b, 0)
	return digest(string(b)), err
}
func snapshotMetadata(root, path string, v any) error {
	if _, err := NewSource("opencode", root, path); err != nil {
		return err
	}
	if err := checkPath(path); err != nil {
		return errors.New("aidr_log_snapshot_metadata_unavailable")
	}
	f, err := openLog(path)
	if err != nil {
		return errors.New("aidr_log_snapshot_metadata_unavailable")
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 256<<10+1))
	if err != nil || len(b) > 256<<10 || json.Unmarshal(b, v) != nil {
		return errors.New("aidr_log_snapshot_metadata_unavailable")
	}
	return nil
}
func storageID(s string) bool {
	return token(s) != "" && !strings.ContainsAny(s, "/\\") && s != "." && s != ".."
}
func normalizeOpenCode(s Source, raw []byte, c *Cursor) ([]draft, error) {
	var p struct {
		ID, SessionID, MessageID, Type, Text, CallID, Tool string
		Time                                               struct{ Start, End int64 }
		State                                              struct {
			Status, Output, Error string
			Input                 json.RawMessage
			Metadata              json.RawMessage
			Time                  struct{ Start, End int64 }
		}
	}
	if json.Unmarshal(raw, &p) != nil {
		return nil, errors.New("aidr_log_invalid_json")
	}
	if !storageID(p.ID) || !storageID(p.SessionID) || !storageID(p.MessageID) {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	switch p.Type {
	case "text", "tool":
	case "step-start", "step-finish", "reasoning", "file", "patch", "snapshot", "subtask", "retry", "compaction", "agent":
		return nil, nil
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	var m struct {
		ID, SessionID, Role, Finish string
		Time                        struct{ Created, Completed int64 }
	}
	if err := snapshotMetadata(s.Root, filepath.Join(s.Root, "message", p.SessionID, p.MessageID+".json"), &m); err != nil {
		return nil, err
	}
	if m.ID != p.MessageID || m.SessionID != p.SessionID || m.Time.Created <= 0 {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	c.Session = p.SessionID
	if p.Type == "text" {
		// Mutable assistant text is emitted only when its message is complete.
		if m.Role == "assistant" && m.Time.Completed == 0 {
			return nil, errors.New("aidr_log_snapshot_pending")
		}
		phase := "unspecified"
		if m.Finish == "stop" {
			phase = "final"
		} else if m.Finish == "tool-calls" {
			phase = "commentary"
		}
		body, _ := json.Marshal(p.Text)
		d, ok := messageDraft(m.Role, phase, p.ID, "", body, time.UnixMilli(m.Time.Created).UTC())
		if ok {
			return []draft{d}, nil
		}
		return nil, nil
	}
	if p.State.Status != "completed" && p.State.Status != "error" {
		return nil, errors.New("aidr_log_snapshot_pending")
	}
	if token(p.CallID) == "" || token(p.Tool) == "" || p.State.Time.Start <= 0 || p.State.Time.End <= 0 || !json.Valid(p.State.Input) {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	result, outcome := p.State.Output, "success"
	if p.State.Status == "error" {
		result, outcome = p.State.Error, "error"
	}
	body, _ := json.Marshal(result)
	return []draft{{Call: p.CallID, Tool: p.Tool, Kind: "tool_call", Content: p.State.Input, Outcome: "unknown", Time: time.UnixMilli(p.State.Time.Start).UTC()}, {Call: p.CallID, ResultTool: p.Tool, Kind: "tool_result", Content: body, ResultMeta: p.State.Metadata, Outcome: outcome, Block: 1, Time: time.UnixMilli(p.State.Time.End).UTC()}}, nil
}
