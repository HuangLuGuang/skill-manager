package agentlog

import (
	"encoding/json"
	"path/filepath"
	"strings"
)

func openCodeLogAdapter() logAdapter {
	return logAdapter{Parse: normalizeOpenCode, Snapshot: true, ModelSource: "opencode.message",
		SourceFile: func(root, path string) bool {
			rel, err := filepath.Rel(root, path)
			return err == nil && strings.HasPrefix(rel, "part"+string(filepath.Separator)) && strings.HasSuffix(path, ".json")
		},
		SkillField: func(tool string) string {
			if tool == "skill" {
				return "name"
			}
			return ""
		}, SkillResult: openCodeSkillResult}
}

func openCodeSkillResult(tool string, raw, meta json.RawMessage, policy *AuditPolicy) *SkillUse {
	if tool != "skill" {
		return nil
	}
	obj := rawObject(meta)
	directory, name := rawString(obj["dir"]), rawString(obj["name"])
	if !filepath.IsAbs(directory) || name == "" {
		return nil
	}
	b := &Behavior{Version: 3, Policy: policy}
	path := safeText(filepath.ToSlash(filepath.Join(directory, "SKILL.md")), 1024, b)
	name = safeText(name, 256, b)
	if b.Redacted || b.Truncated {
		return nil
	}
	return &SkillUse{Behavior: "invocation", Name: name, Path: path, Basis: "result.metadata", Phase: "host_loaded"}
}
