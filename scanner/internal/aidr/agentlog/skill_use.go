package agentlog

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"skill-manager/scanner/internal/manifest"
	"strconv"
	"strings"
	"time"
)

// SkillUse is host evidence, independent of registry certification. It carries
// no Skill body and makes no claim that instructions were followed.
type SkillUse struct {
	Behavior  string `json:"behavior"`
	Name      string `json:"name,omitempty"`
	Path      string `json:"path,omitempty"`
	Basis     string `json:"basis"`
	Digest    string `json:"content_digest,omitempty"`
	CheckedAt string `json:"content_observed_at,omitempty"`
	Phase     string `json:"phase,omitempty"`
}

// WorkBuddy's native Skill result starts with this host-generated source field.
// Other products require their own result adapter; arbitrary text is not a path.
func ProjectSkillResult(agent, tool string, raw, meta json.RawMessage, policy *AuditPolicy) *SkillUse {
	if agent == "opencode" && tool == "skill" {
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
	if agent != "workbuddy" || tool != "Skill" {
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

// ObserveSkillContent runs on the asynchronous log reader, never on a Hook's
// decision path. This is a later inventory observation, not execution attestation.
func ObserveSkillContent(use *SkillUse) {
	if use == nil || use.Path == "" {
		return
	}
	root := filepath.Dir(filepath.FromSlash(use.Path))
	if checkPath(use.Path) != nil {
		return
	}
	info, err := os.Lstat(use.Path)
	if err != nil || !info.Mode().IsRegular() {
		return
	}
	value, err := manifest.Build(root, manifest.Options{
		IgnoreDirs:   map[string]bool{".git": true, ".venv": true, "node_modules": true, "__pycache__": true, "dist": true, "build": true, ".DS_Store": true},
		MaxFileBytes: 2 << 20, MaxTotalBytes: 8 << 20, MaxFiles: 256,
	})
	if err != nil {
		return
	}
	use.Digest = manifest.ContentSignature(value.Files)
	use.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
}

// Recognize a literal single-file read, not a search or a shell expression.
var skillCat = regexp.MustCompile("^(?:/bin/)?cat\\s+(?:--\\s+)?(?:\"([^\"$`\\\\]+)\"|'([^']+)'|([^\\s;&|<>$`\\\\]+))\\s*$")

func ProjectSkillUse(agent, tool, cwd string, input json.RawMessage, policy *AuditPolicy) *SkillUse {
	obj := rawObject(input)
	field := ""
	switch agent {
	case "claude", "workbuddy", "qoder-cli":
		if tool == "Skill" {
			field = "skill"
		}
	case "opencode":
		if tool == "skill" {
			field = "name"
		}
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

func sourceUserScope() string {
	if uid := os.Getuid(); uid >= 0 {
		return strconv.Itoa(uid)
	}
	return ""
}
