package agentlog

import (
	"encoding/json"
	"errors"
)

// Qoder CLI 1.1.57/1.1.61 shares the tool block format with Claude, but has
// distinct metadata records and an explicit entry point. IDE/Work logs must
// not acquire the CLI identity merely because they share this directory.
func normalizeQoder(raw []byte, c *Cursor) ([]draft, error) {
	var r struct{ Type, Entrypoint string }
	if json.Unmarshal(raw, &r) != nil || r.Type == "" {
		return nil, errors.New("aidr_log_invalid_json")
	}
	switch r.Type {
	case "workspace-directories", "runtime-config", "worktree-state", "active-leaf", "last-prompt", "attachment":
		return nil, nil
	case "user", "assistant":
		if r.Entrypoint != "cli" {
			return nil, errors.New("aidr_log_entry_unsupported")
		}
		return normalizeLegacy("claude", raw, c)
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
}
