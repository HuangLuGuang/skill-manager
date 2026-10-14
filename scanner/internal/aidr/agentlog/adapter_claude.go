package agentlog

import (
	"encoding/json"
	"os"
	"path/filepath"
)

func quarantineClaude(raw []byte) (bool, bool) {
	var record map[string]json.RawMessage
	if json.Unmarshal(raw, &record) != nil || record == nil {
		return false, false
	}
	var kind string
	if json.Unmarshal(record["type"], &kind) != nil || kind == "" {
		return false, false
	}
	switch kind {
	case "assistant", "user", "system", "attachment", "file-history-snapshot", "file-history-delta", "mode", "permission-mode", "last-prompt", "ai-title", "queue-operation", "progress", "summary":
		return false, false
	default:
		return true, true
	}
}

func claudeLogAdapter() logAdapter {
	a := lineAdapter(func(raw []byte, c *Cursor) ([]draft, error) { return parseTranscriptBlocks(raw, c, "") })
	a.ModelSource = "claude.message.model"
	a.Model = messageModel(a.ModelSource)
	a.Quarantine = quarantineClaude
	a.SkillField = transcriptSkillField
	a.Roots = func(home string) []string {
		base := os.Getenv("CLAUDE_CONFIG_DIR")
		if base == "" {
			base = filepath.Join(home, ".claude")
		}
		return []string{filepath.Join(base, "projects")}
	}

	return a
}
