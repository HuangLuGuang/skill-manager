package agentlog

import (
	"context"
	"encoding/json"
	"strconv"
	"strings"
)

type doubaoMessageLink struct{ Turn, Phase string }

// A closed native tool exchange binds messages through call IDs, never text or time.
func doubaoMessageLinks(ctx context.Context, source Source, turns, retained map[string]string) map[string]doubaoMessageLink {
	var size int64
	raw, err := readDoubaoFile(ctx, source.Path, &size)
	if err != nil {
		return nil
	}
	parts := doubaoTrajectory(source.Root, source.Path)
	if len(retained) > 0 && parts != nil {
		cursor := Cursor{}
		for _, line := range strings.Split(string(raw), "\n") {
			if ctx.Err() != nil {
				return nil
			}
			drafts, err := normalizeDoubaoWork(source, []byte(line), &cursor)
			if err != nil {
				continue
			}
			for _, d := range drafts {
				if d.Kind != "tool_call" {
					continue
				}
				id := policyToolID("behavior/3", source.Agent, source.ID+":"+parts[0], "", d, digest(canonical(d.Content)))
				uniqueDoubaoID(turns, d.Call, retained[id])
			}
		}
	}
	return doubaoTranscriptLinks(ctx, raw, turns)
}

func doubaoTranscriptLinks(ctx context.Context, raw []byte, turns map[string]string) map[string]doubaoMessageLink {
	result := map[string]doubaoMessageLink{}
	messages := map[string]string{}
	calls := map[string]bool{}
	turn, valid := "", true
	offset := 0
	for _, line := range strings.SplitAfter(string(raw), "\n") {
		if ctx.Err() != nil || len(result) > 10000 {
			return nil
		}
		if !strings.HasSuffix(line, "\n") {
			break
		}
		id := "message:trajectory:" + strconv.Itoa(offset)
		offset += len(line)
		var row struct {
			Role    string          `json:"role"`
			Content json.RawMessage `json:"content"`
			Call    string          `json:"tool_call_id"`
			Calls   []struct {
				ID string `json:"id"`
			} `json:"tool_calls"`
		}
		if json.Unmarshal([]byte(line), &row) != nil {
			return nil
		}
		if row.Role == "user" {
			messages = map[string]string{id: ""}
			calls = map[string]bool{}
			turn = ""
			valid = true
			continue
		}
		switch row.Role {
		case "assistant":
			if len(row.Calls) > 0 {
				messages[id] = "commentary"
				for _, call := range row.Calls {
					next := turns[call.ID]
					if next == "" || (turn != "" && next != turn) {
						valid = false
					}
					if _, exists := calls[call.ID]; exists {
						valid = false
					}
					calls[call.ID] = false
					turn = next
				}
			} else {
				messages[id] = "final"
				complete := valid && turn != "" && len(calls) > 0 && strings.TrimSpace(rawString(row.Content)) != ""
				for _, returned := range calls {
					complete = complete && returned
				}
				if complete {
					for key, phase := range messages {
						result[key] = doubaoMessageLink{turn, phase}
					}
				}
				// Another exchange needs an explicit user boundary.
				valid = false
			}
		case "tool":
			returned, exists := calls[row.Call]
			if !exists || returned {
				valid = false
			}
			calls[row.Call] = true
		default:
			valid = false
		}
	}
	return result
}
