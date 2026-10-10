package agentlog

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestSkillUseAdaptersAndEvidenceBoundaries(t *testing.T) {
	for _, tc := range []struct{ agent, tool, input, behavior string }{
		{"workbuddy", "Skill", `{"skill":"sample"}`, "invocation"},
		{"claude", "Skill", `{"skill":"sample"}`, "invocation"},
		{"qoder-cli", "Skill", `{"skill":"sample"}`, "invocation"},
		{"opencode", "skill", `{"name":"sample"}`, "invocation"},
		{"cursor", "Skill", `{"skill":"sample"}`, ""},
		{"codex", "Skill", `{"skill":"sample"}`, ""},
		{"codex", "exec_command", `{"cmd":"cat /tmp/sample/SKILL.md"}`, "file_access"},
		{"codex", "exec_command", `{"cmd":"cat '/tmp/a b/SKILL.md'"}`, "file_access"},
		{"codex", "exec_command", `{"cmd":"rg sample /tmp/sample/SKILL.md"}`, ""},
		{"codex", "exec_command", `{"cmd":"ls /tmp/sample/SKILL.md"}`, ""},
		{"codex", "exec_command", `{"cmd":"echo cat /tmp/sample/SKILL.md"}`, ""},
		{"codex", "exec_command", `{"cmd":"cat /tmp/sample/SKILL.md; exit 0"}`, ""},
		{"codex", "exec_command", `{"cmd":"cat $HOME/sample/SKILL.md"}`, ""},
		{"claude", "Read", `{"file_path":"./sample/SKILL.md"}`, "file_access"},
	} {
		got := ProjectSkillUse(tc.agent, tc.tool, "/tmp", json.RawMessage(tc.input), nil)
		if tc.behavior == "" {
			if got != nil {
				t.Errorf("%+v unexpectedly recognized: %+v", tc, got)
			}
			continue
		}
		if got == nil || got.Behavior != tc.behavior {
			t.Errorf("%+v: %+v", tc, got)
		}
	}
}

func TestSkillContentObservationIsSeparateAndBounded(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "SKILL.md")
	if err := os.WriteFile(path, []byte("---\nname: sample\n---\nSay hello.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	use := &SkillUse{Behavior: "file_access", Path: path, Basis: "tool_input.path"}
	ObserveSkillContent(use)
	if len(use.Digest) != 64 || use.CheckedAt == "" {
		t.Fatalf("missing observation: %+v", use)
	}
	old := use.Digest
	os.WriteFile(path, []byte("changed"), 0600)
	ObserveSkillContent(use)
	if old == use.Digest {
		t.Fatal("content change not detected")
	}
	missing := &SkillUse{Behavior: "file_access", Path: filepath.Join(root, "missing", "SKILL.md"), Basis: "tool_input.path"}
	ObserveSkillContent(missing)
	if missing.Digest != "" {
		t.Fatal("unreadable source certified")
	}
}

func TestSkillResultSources(t *testing.T) {
	for _, tc := range []struct {
		agent, tool, result, meta string
		want                      bool
	}{
		{"workbuddy", "Skill", `{"text":"Base directory for this skill: /Users/test/skills/sample\n\nBenign body"}`, `{}`, true},
		{"workbuddy", "Skill", `"Quoted text: Base directory for this skill: /Users/test/skills/sample"`, `{}`, false},
		{"qoder-cli", "Skill", `"Base directory for this skill: /tmp/sample"`, `{}`, false},
		{"opencode", "skill", `"ignored body"`, `{"name":"sample","dir":"/Users/test/skills/sample"}`, true},
		{"opencode", "skill", `"ignored body"`, `{"name":"sample","dir":"relative"}`, false},
	} {
		got := ProjectSkillResult(tc.agent, tc.tool, json.RawMessage(tc.result), json.RawMessage(tc.meta), nil)
		if (got != nil) != tc.want {
			t.Fatalf("%s: expected %v, got %+v", tc.agent, tc.want, got)
		}
		if got != nil && (got.Phase != "host_loaded" || filepath.Base(got.Path) != "SKILL.md" || got.Digest != "") {
			t.Fatalf("invalid projection: %+v", got)
		}
	}
}
