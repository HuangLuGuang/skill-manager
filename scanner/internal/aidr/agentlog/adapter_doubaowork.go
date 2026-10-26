package agentlog

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

func doubaoTrajectory(root, path string) []string {
	rel, err := filepath.Rel(root, path)
	parts := strings.Split(filepath.ToSlash(rel), "/")
	if err != nil || len(parts) != 5 || token(parts[0]) == "" || parts[0] == ".." || parts[1] != "agents" || token(parts[2]) == "" || parts[2] == ".." || parts[3] != "system" || parts[4] != "trajectory.jsonl" {
		return nil
	}
	return parts
}

func doubaoWorkLogAdapter() logAdapter {
	return logAdapter{
		Roots: doubaoRoots,
		Read:  readDoubaoWork,
		ReadOffset: func(s Source, c Cursor) int64 {
			if doubaoCacheSource(s.Root, s.Path) {
				if c.ScanComplete {
					if info, err := os.Stat(s.Path); err == nil {
						return info.Size()
					}
				}
				return 0
			}
			if c.ContextRepair != nil {
				return 0
			}
			return c.Offset
		},
		Parse: normalizeDoubaoWork, DraftTurn: true, ObservedAtSource: "collection",
		SourceFile: func(root, path string) bool {
			return doubaoTrajectory(root, path) != nil || doubaoCacheSource(root, path)
		},
	}
}

func readDoubaoWork(ctx context.Context, s Source, c Cursor, b Budget, since time.Time, policy *AuditPolicy, observer *SkillObserver) (ReadBatch, error) {
	if doubaoCacheSource(s.Root, s.Path) {
		return readDoubaoCache(ctx, s, c, b, since, policy, observer)
	}
	collectMessages := policy != nil && policy.CollectionEnabled() && policy.MessageSchema == 1 && policy.Capture != nil
	var turns map[string]string
	var revision string
	if parts := doubaoTrajectory(s.Root, s.Path); parts != nil && policy != nil && policy.CollectionEnabled() {
		if feishuProfile(s.Root) != "" {
			indexCtx, cancel := context.WithTimeout(ctx, b.Duration)
			turns, revision = feishuTurns(indexCtx, s.Root, parts[0])
			cancel()
		} else {
			turns, revision = doubaoTurns(ctx, s.Root, parts[0])
		}
	}
	b.Events = min(b.Events, 128)
	var messages map[string]doubaoMessageLink
	if policy != nil && policy.MessageLinkSchema == 1 && (len(turns) > 0 || len(b.RetainedTurns) > 0) {
		if turns == nil {
			turns = map[string]string{}
		}
		messages = doubaoMessageLinks(ctx, s, turns, b.RetainedTurns)
		metadata, _ := json.Marshal(messages)
		revision = digest("doubao-message-links/1", revision, string(metadata))
	}
	enrich := func(out ReadBatch) ReadBatch {
		for _, e := range out.Events {
			if turn := turns[e.CallID]; turn != "" && (e.Kind == "tool_call" || e.Kind == "tool_result") {
				out.TurnLinks = append(out.TurnLinks, TurnLink{e.LogicalEventID, e.SessionID, e.CallID, turn, e.ContentDigest, ""})
			} else if link, ok := messages[e.CallID]; ok && e.Message != nil {
				out.TurnLinks = append(out.TurnLinks, TurnLink{e.LogicalEventID, e.SessionID, e.CallID, link.Turn, e.ContentDigest, link.Phase})
			}
		}
		return out
	}
	if ((collectMessages && !c.DoubaoMessages) || (revision != "" && revision != c.DoubaoTurns)) && c.Offset > 0 {
		// Keep the committed offset while replay advances in a separate checkpoint.
		checkpoint := Cursor{}
		if c.ContextRepair != nil && c.ContextRepair.DoubaoTurns == revision {
			checkpoint = *c.ContextRepair
		}
		out, err := readWithPolicy(ctx, s, checkpoint, b, c.Since, policy, c.Offset, true, observer)
		if err != nil {
			return out, err
		}
		if out.Cursor.FileIdentity != c.FileIdentity || (out.Coverage.Status == "complete" && out.Cursor.Offset < c.Offset) {
			return readWithPolicy(ctx, s, c, b, since, policy, 0, false, observer)
		}
		if out.Cursor.Offset == c.Offset {
			c.DoubaoMessages, c.ContextRepair = c.DoubaoMessages || collectMessages, nil
			c.DoubaoTurns = revision
		} else {
			progress := out.Cursor
			progress.DoubaoTurns = revision
			c.ContextRepair = &progress
		}
		out.Cursor = c
		return enrich(out), nil
	}
	out, err := readWithPolicy(ctx, s, c, b, since, policy, 0, false, observer)
	if err == nil && out.Cursor.SchemaVersion != 0 && collectMessages {
		out.Cursor.DoubaoMessages = true
	}
	if err == nil && out.Cursor.SchemaVersion != 0 && revision != "" {
		out.Cursor.DoubaoTurns = revision
	}
	return enrich(out), err
}

func normalizeDoubaoWork(s Source, raw []byte, c *Cursor) ([]draft, error) {
	parts := doubaoTrajectory(s.Root, s.Path)
	if parts == nil {
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	var row struct {
		Role    string          `json:"role"`
		Content json.RawMessage `json:"content"`
		Call    string          `json:"tool_call_id"`
		Calls   []struct {
			ID       string `json:"id"`
			Function struct {
				Name      string          `json:"name"`
				Arguments json.RawMessage `json:"arguments"`
			} `json:"function"`
		} `json:"tool_calls"`
	}
	if err := json.Unmarshal(raw, &row); err != nil {
		return nil, err
	}
	c.Session = parts[0]
	// trajectory has no execution timestamps; never label file mtime as execution time.
	now := time.Now().UTC()
	drafts := []draft{}
	switch row.Role {
	case "assistant":
		for i, call := range row.Calls {
			tool, args := call.Function.Name, call.Function.Arguments
			if value := rawString(args); value != "" {
				args = json.RawMessage(value)
			}
			if tool == "execute_defer_tool" {
				obj := rawObject(args)
				if name := rawString(obj["toolName"]); strings.HasPrefix(name, "mcp__") {
					tool, args = name, obj["params"]
				}
			}
			if rawObject(args) == nil {
				return nil, errors.New("aidr_log_schema_unsupported")
			}
			rememberTool(c, call.ID, "", tool, args)
			drafts = append(drafts, draft{Call: call.ID, Kind: "tool_call", Tool: tool, Outcome: "unknown", Content: args, Time: now, Block: i})
		}
	case "tool":
		turn, tool := completeTool(c, row.Call, "")
		drafts = append(drafts, draft{Call: row.Call, Kind: "tool_result", Tool: tool, Turn: turn, Outcome: "unknown", Content: row.Content, Time: now, ResultProjection: doubaoResult})
	case "user", "system":
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	if row.Role == "user" || row.Role == "assistant" {
		// Offsets distinguish repeated identical messages without inventing host turn IDs.
		id := "trajectory:" + strconv.FormatInt(c.Offset, 10)
		if message, ok := messageDraft(row.Role, "unspecified", id, "", row.Content, now); ok {
			message.Block = len(row.Calls)
			drafts = append(drafts, message)
		}
	}
	return validateDrafts(drafts)
}

func doubaoResult(b *Behavior, _ string, _ json.RawMessage) {
	// Returned text (including JSON in file/MCP output) is not an execution receipt.
	b.Status, b.ExitCode = "unknown", nil
	b.Basis = []string{}
	b.Uncertainty = []string{"result_semantics_unknown"}
}
