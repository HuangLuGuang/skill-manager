package agentlog

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"
)

// ZCode 3.16.3 stores mutable parts in SQLite; its anchor is the native turn.
func zcodeLogAdapter() logAdapter {
	return logAdapter{Read: func(ctx context.Context, s Source, c Cursor, b Budget, since time.Time, p *AuditPolicy, o *SkillObserver) (ReadBatch, error) {
		return readSQLiteParts(ctx, s, c, b, since, p, o, parseZcode)
	}, DraftTurn: true, ModelSource: "zcode.message", SourceFile: func(_, path string) bool { return filepath.Base(path) == "db.sqlite" },
		ReadOffset: func(s Source, c Cursor) int64 {
			if c.ScanComplete {
				if i, e := os.Stat(s.Path); e == nil {
					return i.Size()
				}
			}
			return 0
		},
		SkillField: func(tool string) string {
			if tool == "Skill" {
				return "skill"
			}
			return ""
		}}
}

func parseZcode(r sqlitePartRecord) ([]draft, error) {
	var m struct {
		Role, Finish, ModelID, ProviderID string
		Synthetic                         bool
		Anchor                            struct{ TurnID string }
		Semantics                         struct{ TranscriptVisibility string }
		Time                              struct{ Created, Completed int64 }
		ModelSelection                    struct {
			ModelID, ProviderID string
			Options             struct{ ReasoningLevel string }
		}
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
	if m.Synthetic || m.Semantics.TranscriptVisibility == "hidden" {
		return nil, nil
	}
	model := &ModelContext{Model: modelValue(m.ModelID), Provider: modelValue(m.ProviderID), Source: "zcode.message"}
	if m.Role == "user" {
		model.Model = modelValue(m.ModelSelection.ModelID)
		model.Provider = modelValue(m.ModelSelection.ProviderID)
		model.ReasoningEffort = modelValue(m.ModelSelection.Options.ReasoningLevel)
	}
	if model.empty() {
		model = nil
	}
	switch p.Type {
	case "text":
		if m.Role == "assistant" && m.Time.Completed == 0 {
			return nil, nil
		}
		if r.Created <= 0 {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		phase := "unspecified"
		if m.Finish == "stop" {
			phase = "final"
		} else if m.Finish == "tool-calls" {
			phase = "commentary"
		}
		raw, _ := json.Marshal(p.Text)
		if d, ok := messageDraft(m.Role, phase, r.ID, token(m.Anchor.TurnID), raw, time.UnixMilli(r.Created).UTC()); ok {
			d.ModelContext = model
			return []draft{d}, nil
		}
	case "tool":
		if p.State.Status != "completed" && p.State.Status != "error" {
			return nil, nil
		}
		if token(p.CallID) == "" || token(p.Tool) == "" || !json.Valid(p.State.Input) || p.State.Time.Start <= 0 || p.State.Time.End <= 0 {
			return nil, errors.New("aidr_log_schema_unsupported")
		}
		body, outcome := p.State.Output, "success"
		if p.State.Status == "error" {
			body, outcome = p.State.Error, "error"
		}
		raw, _ := json.Marshal(body)
		return []draft{{Turn: token(m.Anchor.TurnID), ModelContext: model, Call: p.CallID, Tool: p.Tool, Cwd: r.Cwd, Kind: "tool_call", Content: p.State.Input, Outcome: "unknown", Time: time.UnixMilli(p.State.Time.Start).UTC()},
			{Turn: token(m.Anchor.TurnID), ModelContext: model, Call: p.CallID, ResultTool: p.Tool, Kind: "tool_result", Content: raw, ResultMeta: p.State.Metadata, Outcome: outcome, Block: 1, Time: time.UnixMilli(p.State.Time.End).UTC()}}, nil
	case "step-start", "step-finish", "reasoning", "file", "patch", "snapshot", "subtask", "retry", "compaction", "agent", "timeline":
		return nil, nil
	default:
		return nil, errors.New("aidr_log_schema_unsupported")
	}
	return nil, nil
}

// Native Bash PostToolUse provides exitCode; SQLite parts do not preserve it.
func ProjectZcodeToolEvidence(tool, kind, cwd string, content json.RawMessage, outcome string, policy AuditPolicy) (*Behavior, error) {
	return projectToolEvidence(tool, kind, cwd, content, content, outcome, policy, func(b *Behavior, tool string, raw json.RawMessage) {
		if tool != "Bash" {
			return
		}
		var r struct {
			ExitCode                         *int
			Cancelled, Interrupted, TimedOut bool
		}
		if json.Unmarshal(raw, &r) != nil || r.ExitCode != nil && (*r.ExitCode < -2147483648 || *r.ExitCode > 2147483647) {
			b.Status = "unknown"
			b.ExitCode = nil
			b.Basis = []string{}
			b.Uncertainty = []string{"result_format_unsupported"}
			return
		}
		if r.ExitCode != nil {
			b.ExitCode = r.ExitCode
			b.Status = "reported_success"
			if *r.ExitCode != 0 {
				b.Status = "reported_error"
			}
			b.Basis = []string{"structured_exit_code"}
			b.Uncertainty = []string{}
		}
		if r.Cancelled || r.Interrupted {
			b.Status = "reported_cancelled"
			b.Basis = append(b.Basis, "interrupted")
		}
		if r.TimedOut {
			b.Status = "reported_error"
		}
	})
}
