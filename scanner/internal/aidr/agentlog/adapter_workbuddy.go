package agentlog

import (
	"encoding/json"
	"path/filepath"
	"strings"
)

func workbuddyLogAdapter() logAdapter {
	a := lineAdapter(normalizeWorkBuddy)
	a.ModelSource = "workbuddy.providerData.model"
	a.Model = func(raw []byte, c *Cursor, drafts []draft) {
		var r modelRecord
		if json.Unmarshal(raw, &r) != nil || c.Session == "" {
			return
		}
		assignModel(drafts, &ModelContext{Model: modelValue(r.ProviderData.Model), Source: a.ModelSource})
	}
	a.DraftTurn = true
	a.SkillField = transcriptSkillField
	a.SkillResult = workbuddySkillResult
	return a
}

func workbuddySkillResult(tool string, raw, meta json.RawMessage, policy *AuditPolicy) *SkillUse {
	if tool != "Skill" {
		return nil
	}
	text := rawString(raw)
	if text == "" {
		text = rawString(rawObject(raw)["text"])
	}
	const prefix = "Base directory for this skill: "
	if !strings.HasPrefix(text, prefix) {
		return nil
	}
	directory := strings.TrimSuffix(strings.SplitN(strings.TrimPrefix(text, prefix), "\n", 2)[0], "\r")
	if !filepath.IsAbs(directory) || len(directory) > 1000 {
		return nil
	}
	b := &Behavior{Version: 3, Policy: policy}
	path := safeText(filepath.ToSlash(filepath.Join(directory, "SKILL.md")), 1024, b)
	if b.Redacted || b.Truncated {
		return nil
	}
	return &SkillUse{Behavior: "invocation", Path: path, Basis: "result.base_directory", Phase: "host_loaded"}

}

// WorkBuddy sends the native rawResponse as tool_response. Its text output is
// a separate log field and must not be interpreted as structured result data.
func ProjectWorkBuddyToolEvidence(tool, kind, cwd string, content json.RawMessage, outcome string, policy AuditPolicy) (*Behavior, error) {
	meta := content
	var obj map[string]json.RawMessage
	if json.Unmarshal(content, &obj) == nil {
		for _, field := range []string{"content", "error"} {
			var text string
			if json.Unmarshal(obj[field], &text) == nil && text != "" {
				content = obj[field]
				break
			}
		}
	}
	return projectToolEvidence(tool, kind, cwd, content, meta, outcome, policy, projectWorkBuddyResult)
}
