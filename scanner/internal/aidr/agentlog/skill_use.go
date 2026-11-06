package agentlog

import (
	"context"
	"encoding/json"
	"path/filepath"
	"regexp"
	"strings"
)

// SkillUse is host evidence, independent of registry certification. It carries
// no Skill body and makes no claim that instructions were followed.
type SkillUse struct {
	Behavior      string `json:"behavior"`
	Name          string `json:"name,omitempty"`
	Path          string `json:"path,omitempty"`
	Basis         string `json:"basis"`
	Digest        string `json:"content_digest,omitempty"`
	CheckedAt     string `json:"content_observed_at,omitempty"`
	Phase         string `json:"phase,omitempty"`
	ContentStatus string `json:"content_status,omitempty"`
	ContentReason string `json:"content_reason,omitempty"`
}

func ProjectSkillResult(agent, tool string, raw, meta json.RawMessage, policy *AuditPolicy) *SkillUse {
	if f := logAdapters[agent].SkillResult; f != nil {
		return f(tool, raw, meta, policy)
	}
	return nil
}

// ObserveSkillContent runs on the asynchronous log reader, never on a Hook's
// decision path. This is a later inventory observation, not execution attestation.
func ObserveSkillContent(use *SkillUse) {
	NewSkillObserver().Observe(context.Background(), use, nil)
}

// Recognize a literal single-file read, not a search or a shell expression.
var skillCat = regexp.MustCompile("^(?:/bin/)?cat\\s+(?:--\\s+)?(?:\"([^\"$`\\\\]+)\"|'([^']+)'|([^\\s;&|<>$`\\\\]+))\\s*$")

func ProjectSkillUse(agent, tool, cwd string, input json.RawMessage, policy *AuditPolicy) *SkillUse {
	obj := rawObject(input)
	field := ""
	if f := logAdapters[agent].SkillField; f != nil {
		field = f(tool)
	}
	b := &Behavior{Version: 3, Policy: policy}
	if field != "" {
		name := safeText(strings.TrimSpace(rawString(obj[field])), 256, b)
		if name != "" && !b.Truncated && !b.Redacted {
			return &SkillUse{Behavior: "invocation", Name: name, Basis: "tool_input." + field}
		}
		return nil
	}
	path, basis := "", ""
	if category(tool) == "file_read" {
		for _, key := range []string{"file_path", "path"} {
			if path = rawString(obj[key]); path != "" {
				basis = "tool_input." + key
				break
			}
		}
	} else if category(tool) == "command" {
		command := rawString(obj["command"])
		if command == "" {
			command = rawString(obj["cmd"])
		}
		if match := skillCat.FindStringSubmatch(strings.TrimSpace(command)); match != nil {
			for _, value := range match[1:] {
				if value != "" {
					path = value
				}
			}
			basis = "literal_cat"
		}
		for _, key := range []string{"workdir", "cwd"} {
			if value := rawString(obj[key]); value != "" {
				cwd = value
				break
			}
		}
	}
	if filepath.Base(path) != "SKILL.md" || strings.ContainsAny(path, "\x00\r\n") {
		return nil
	}
	if !filepath.IsAbs(path) {
		if !filepath.IsAbs(cwd) {
			return nil
		}
		path = filepath.Join(cwd, path)
	}
	path = safeText(filepath.Clean(path), 1024, b)
	if b.Truncated || b.Redacted {
		return nil
	}
	return &SkillUse{Behavior: "file_access", Path: filepath.ToSlash(path), Basis: basis}
}
