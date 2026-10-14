package agentlog

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"skill-manager/scanner/internal/aidr/catalog"
	"strings"
	"time"
)

// logAdapter owns host formats and identity semantics. The reader owns budgets,
// checkpoints, projection and delivery. Adapters never call another product.
type logAdapter struct {
	Roots            func(string) []string
	Read             func(context.Context, Source, Cursor, Budget, time.Time, *AuditPolicy, *SkillObserver) (ReadBatch, error)
	ReadOffset       func(Source, Cursor) int64
	Parse            func(Source, []byte, *Cursor) ([]draft, error)
	Model            func([]byte, *Cursor, []draft)
	ModelSource      string
	Snapshot         bool
	DraftTurn        bool
	SourceFile       func(string, string) bool
	Repair           func(Cursor) bool
	Restore          func(*os.File, *Cursor)
	PreservesContext func([]byte) bool
	Quarantine       func([]byte) (bool, bool)
	SkillField       func(string) string
	SkillResult      func(string, json.RawMessage, json.RawMessage, *AuditPolicy) *SkillUse
}

var logAdapters map[string]logAdapter

func init() {
	logAdapters = map[string]logAdapter{
		"claude":    claudeLogAdapter(),
		"codex":     codexLogAdapter(),
		"workbuddy": workbuddyLogAdapter(),
		"qoder-cli": qoderLogAdapter(),
		"opencode":  openCodeLogAdapter(),
		"teleagent": teleAgentLogAdapter(),
	}
}

func lineAdapter(parse func([]byte, *Cursor) ([]draft, error)) logAdapter {
	return logAdapter{Parse: func(_ Source, raw []byte, c *Cursor) ([]draft, error) { return parse(raw, c) }}
}

func normalizeSource(s Source, raw []byte, c *Cursor) ([]draft, error) {
	a, ok := logAdapters[s.Agent]
	if !ok || a.Parse == nil {
		return nil, errors.New("aidr_log_agent_unsupported")
	}
	drafts, err := a.Parse(s, raw, c)
	if err == nil && a.Model != nil {
		a.Model(raw, c, drafts)
	}
	return drafts, err
}

func SourceFile(agent, root, path string) bool {
	a, ok := logAdapters[agent]
	if !ok {
		return false
	}
	if a.SourceFile != nil {
		return a.SourceFile(root, path)
	}
	return strings.HasSuffix(path, ".jsonl")
}

func sourceAnchor(s Source, f *os.File, offset int64) (string, error) {
	if !logAdapters[s.Agent].Snapshot {
		return anchor(f, offset)
	}
	if offset > 4<<20 {
		return "", errors.New("aidr_log_record_too_large")
	}
	b := make([]byte, offset)
	_, err := f.ReadAt(b, 0)
	return digest(string(b)), err
}

func validateDrafts(drafts []draft) ([]draft, error) {
	for _, d := range drafts {
		if token(d.Call) == "" || (d.Kind == "tool_call" && token(d.Tool) == "") || len(d.Content) == 0 || d.Time.IsZero() {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
	}
	return drafts, nil
}

// DefaultRoots is the product-owned default for interactive log readers.
func DefaultRoots(agent, home string) []string {
	if f := logAdapters[agent].Roots; f != nil {
		return f(home)
	}
	return catalog.LogRoots(agent, home)
}
