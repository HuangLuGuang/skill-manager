package agentlog

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

func codeBuddyLogAdapter() logAdapter {
	return logAdapter{Read: readCodeBuddy, DraftTurn: true, ModelSource: "codebuddy.message.extra",
		SourceFile: func(_, path string) bool {
			return filepath.Base(path) == "index.json" && filepath.Base(filepath.Dir(filepath.Dir(filepath.Dir(path)))) == "history" && strings.Contains(filepath.ToSlash(path), "/CodeBuddyIDE/")
		},
		ReadOffset: func(s Source, c Cursor) int64 {
			if c.ScanComplete {
				if info, err := os.Stat(s.Path); err == nil {
					return info.Size()
				}
			}
			return 0
		},
		SkillField: func(tool string) string {
			if tool == "Skill" {
				return "command"
			}
			return ""
		},
		SkillResult: codeBuddySkillResult,
	}
}

func codeBuddyReadFile(path string, limit int64) ([]byte, os.FileInfo, error) {
	if err := checkPath(path); err != nil {
		return nil, nil, errors.New(ioReason(err))
	}
	f, err := openLog(path)
	if err != nil {
		return nil, nil, errors.New(ioReason(err))
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return nil, nil, errors.New("aidr_log_not_regular")
	}
	if info.Size() > limit {
		return nil, nil, errors.New("aidr_log_record_too_large")
	}
	raw, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, nil, errors.New("aidr_log_io_error")
	}
	current, err := checkedPathInfo(path)
	if err != nil || len(raw) > int(limit) || !sameLogReadVersion(info, current) {
		return nil, nil, errors.New("aidr_log_source_changed")
	}
	return raw, info, nil
}

// The host-generated user envelope is accepted only when its workspace hashes
// to this native history directory; arbitrary quoted paths are not workspace metadata.
func codeBuddyWorkspace(raw []byte, path string) string {
	var e codeBuddyMessage
	var m struct{ Content []struct{ Type, Text string } }
	if json.Unmarshal(raw, &e) != nil || e.Role != "user" || json.Unmarshal([]byte(e.Message), &m) != nil || len(m.Content) == 0 {
		return ""
	}
	text := m.Content[0].Text
	if !strings.HasPrefix(text, "<user_info>\n") {
		return ""
	}
	end := strings.Index(text, "</user_info>")
	if end < 0 {
		return ""
	}
	for _, line := range strings.Split(text[:end], "\n") {
		if !strings.HasPrefix(line, "Workspace Folder: ") {
			continue
		}
		cwd := strings.TrimPrefix(line, "Workspace Folder: ")
		if !filepath.IsAbs(cwd) || len(cwd) > 2048 {
			return ""
		}
		cwd = filepath.Clean(cwd)
		hash := md5.Sum([]byte(cwd))
		if hex.EncodeToString(hash[:]) == filepath.Base(filepath.Dir(filepath.Dir(path))) {
			return cwd
		}
	}
	return ""
}

func readCodeBuddy(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, observer *SkillObserver) (ReadBatch, error) {
	out := ReadBatch{SchemaVersion: SchemaVersion, Source: s, Cursor: old, Events: []Event{}, Coverage: Coverage{Status: "complete", Reasons: []string{}}}
	expected, err := NewSource(s.Agent, s.Root, s.Path)
	if err != nil || expected.ID != s.ID || !b.valid() || !SourceFile(s.Agent, s.Root, s.Path) {
		return out, errors.New("aidr_log_request_invalid")
	}
	if old.SchemaVersion != 0 {
		if err := ValidateCursor(old, s); err != nil {
			return out, err
		}
	}
	deadline := time.Now().Add(b.Duration)
	rawIndex, info, err := codeBuddyReadFile(s.Path, min(b.Bytes, 4<<20))
	if err != nil {
		out.Coverage.mark("unavailable", err.Error())
		return out, nil
	}
	var index codeBuddyIndex
	if json.Unmarshal(rawIndex, &index) != nil || index.Messages == nil || index.Requests == nil || len(index.Messages) > 50000 {
		out.Coverage.mark("unavailable", "aidr_log_schema_unsupported")
		return out, nil
	}
	session := filepath.Base(filepath.Dir(s.Path))
	if !storageID(session) {
		return out, errors.New("aidr_log_schema_unsupported")
	}
	requests := map[string]codeBuddyRequest{}
	for _, request := range index.Requests {
		if !storageID(request.ID) {
			out.Coverage.mark("unavailable", "aidr_log_schema_unsupported")
			return out, nil
		}
		for _, id := range request.Messages {
			if !storageID(id) || requests[id].ID != "" {
				out.Coverage.mark("unavailable", "aidr_log_schema_unsupported")
				return out, nil
			}
			requests[id] = request
		}
	}
	c := old
	revision := digest(string(rawIndex))
	if c.SchemaVersion == 0 {
		if since.IsZero() {
			since = time.Now().Add(-24 * time.Hour)
		}
		c = Cursor{SchemaVersion: SchemaVersion, ParserVersion: ParserVersion, SourceID: s.ID, FileIdentity: s.ID, Generation: 1, Since: since, ProjectionVersion: 2, ContextRepairVersion: contextRepairVersion, Gaps: []string{}}
	} else if c.ScanComplete || c.Anchor != revision {
		if c.Generation == ^uint64(0) {
			return out, errors.New("aidr_log_generation_exhausted")
		}
		c.Generation++
		c.Offset = 0
		c.ScanComplete = false
	}
	c.Session, c.Anchor = session, revision
	out.Coverage.Bytes = int64(len(rawIndex))
	for c.Offset < int64(len(index.Messages)) {
		if ctx.Err() != nil || time.Now().After(deadline) || out.Coverage.Bytes >= b.Bytes || len(out.Events) >= b.Events {
			out.Coverage.mark("partial", "aidr_log_read_budget")
			break
		}
		entry := index.Messages[c.Offset]
		request := requests[entry.ID]
		if !storageID(entry.ID) || request.ID == "" {
			out.Coverage.mark("partial", "aidr_log_schema_unsupported")
			c.Offset++
			continue
		}
		path := filepath.Join(filepath.Dir(s.Path), "messages", entry.ID+".json")
		raw, _, err := codeBuddyReadFile(path, int64(b.LineBytes))
		if err != nil {
			out.Coverage.mark("partial", err.Error())
			c.Offset++
			continue
		}
		if out.Coverage.Bytes+int64(len(raw)) > b.Bytes {
			out.Coverage.mark("partial", "aidr_log_read_budget")
			break
		}
		out.Coverage.Bytes += int64(len(raw))
		drafts, err := parseCodeBuddyMessage(raw, entry.ID, request.ID, request.State == "complete")
		if err != nil {
			out.Coverage.mark("partial", err.Error())
			c.Offset++
			continue
		}
		if len(drafts) > b.Events-len(out.Events) {
			out.Coverage.mark("partial", "aidr_log_event_budget")
			break
		}
		if cwd := codeBuddyWorkspace(raw, s.Path); cwd != "" {
			c.CodeBuddyWorkspace = cwd
		}
		for i := range drafts {
			drafts[i].Cwd = c.CodeBuddyWorkspace
		}
		position := c
		position.Offset *= 4097
		start := len(out.Events)
		projectDrafts(ctx, s, drafts, &c, position, s.ID, raw, policy, b, observer, deadline, 0, &out)
		for i := start; i < len(out.Events); i++ {
			e := &out.Events[i]
			e.SourceInstanceID = digest(s.ID, "codebuddy-session/1")
			e.EventID = digest("codebuddy-session/1", s.ID, entry.ID, strconv.Itoa(e.Block), string(raw))
		}
		out.Coverage.Records++
		c.Offset++
		if len(drafts) == 0 {
			out.Coverage.Ignored++
		}
	}
	current, err := checkedPathInfo(s.Path)
	if err != nil || !sameLogReadVersion(info, current) {
		out.Events = nil
		out.Coverage.mark("unavailable", "aidr_log_source_changed")
		return out, nil
	}
	c.ScanComplete = c.Offset == int64(len(index.Messages))
	out.Cursor = c
	return out, nil
}
