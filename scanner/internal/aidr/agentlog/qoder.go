package agentlog

import (
	"encoding/json"
	"errors"
)

// Persist native ancestry across incremental reads, including attachment nodes.
// Missing/evicted parents stay unassigned rather than borrowing the latest turn.
const maxQoderLinks = 512

type QoderLink struct {
	ID   string `json:"id"`
	Turn string `json:"turn"`
}

// Qoder CLI 1.1.57/1.1.61 shares the tool block format with Claude, but has
// distinct metadata records and an explicit entry point. IDE/Work logs must
// not acquire the CLI identity merely because they share this directory.
func normalizeQoder(raw []byte, c *Cursor) ([]draft, error) {
	return normalizeRequestSetTranscript(raw, c)
}

// Native request-set ancestry is also present in QwenWork CN 1.4.0 transcripts.
func normalizeRequestSetTranscript(raw []byte, c *Cursor) ([]draft, error) {
	var r struct {
		Type, Entrypoint string
		Session          string `json:"sessionId"`
		ID               string `json:"uuid"`
		Parent           string `json:"parentUuid"`
		RequestSet       string `json:"requestSetId"`
	}
	if json.Unmarshal(raw, &r) != nil || r.Type == "" {
		return nil, errors.New("aidr_log_invalid_json")
	}
	switch r.Type {
	case "workspace-directories", "runtime-config", "worktree-state", "active-leaf", "last-prompt", "file-history-snapshot", "file-history-delta":
		return nil, nil
	case "user", "assistant", "attachment":
		if r.Type != "attachment" && r.Entrypoint != "cli" {
			return nil, errors.New("aidr_log_entry_unsupported")
		}
		if r.Session != "" && token(r.Session) == "" || r.ID != "" && token(r.ID) == "" || r.Parent != "" && token(r.Parent) == "" || r.RequestSet != "" && token(r.RequestSet) == "" {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		if r.Session != "" && r.Session != c.Session {
			c.QoderLinks, c.CallTurns = nil, nil
			c.Session = r.Session
		}
		turn := r.RequestSet
		if turn == "" && r.Parent != "" {
			for _, link := range c.QoderLinks {
				if link.ID == r.Parent {
					turn = link.Turn
					break
				}
			}
		}
		var drafts []draft
		var err error
		if r.Type != "attachment" {
			drafts, err = parseTranscriptBlocks(raw, c, turn)
			if err != nil {
				return nil, err
			}
		}
		for i := range drafts {
			if drafts[i].Kind != "tool_result" {
				drafts[i].Turn = turn
			}
		}
		if r.ID != "" && turn != "" {
			c.QoderLinks = append([]QoderLink(nil), c.QoderLinks...)
			for _, link := range c.QoderLinks {
				if link.ID == r.ID {
					if link.Turn != turn {
						return nil, errors.New("aidr_log_schema_unsupported")
					}
					return drafts, nil
				}
			}
			c.QoderLinks = append(c.QoderLinks, QoderLink{ID: r.ID, Turn: turn})
			if len(c.QoderLinks) > maxQoderLinks {
				c.QoderLinks = c.QoderLinks[len(c.QoderLinks)-maxQoderLinks:]
			}
		}
		return drafts, nil
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
}
