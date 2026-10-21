package agentlog

import (
	"encoding/json"
	"errors"
	"path/filepath"
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
		Parse: normalizeDoubaoWork, DraftTurn: true, ObservedAtSource: "collection",
		SourceFile: func(root, path string) bool { return doubaoTrajectory(root, path) != nil },
	}
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
	return validateDrafts(drafts)
}

func doubaoResult(b *Behavior, _ string, _ json.RawMessage) {
	// Returned text (including JSON in file/MCP output) is not an execution receipt.
	b.Status, b.ExitCode = "unknown", nil
	b.Basis = []string{}
	b.Uncertainty = []string{"result_semantics_unknown"}
}
