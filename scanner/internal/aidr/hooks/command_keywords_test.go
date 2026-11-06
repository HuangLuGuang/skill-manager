package hooks

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestCommandKeywordsSharedVectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/command_keywords.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Keywords KeywordCondition `json:"keywords"`
		Command  string           `json:"command"`
		Want     string           `json:"want"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		c := &CommandCondition{Keywords: &tc.Keywords}
		if !c.valid() {
			t.Fatal("valid condition rejected")
		}
		if got := commandMatch(c, tc.Command, "", "deny"); got != tc.Want {
			t.Errorf("%q: got %s, want %s", tc.Command, got, tc.Want)
		}
	}
}

func TestCommandKeywordsValidationAndPolicy(t *testing.T) {
	for _, terms := range [][]string{nil, {""}, {"  "}, {"a\nb"}, {strings.Repeat("密", 86)}, make([]string, 17)} {
		if (&CommandCondition{Keywords: &KeywordCondition{Terms: terms, Mode: "any"}}).valid() {
			t.Fatalf("invalid terms accepted: %q", terms)
		}
	}
	c := &CommandCondition{Keywords: &KeywordCondition{Terms: []string{"test.txt"}, Mode: "any"}}
	p := ToolPolicy{Revision: "1", Default: "allow", Rules: []ToolRule{{ID: "keyword", Agent: "*", Tool: "*", Decision: "deny", Command: c}}}
	raw := []byte(`{"hook_event_name":"PreToolUse","session_id":"test-session","tool_use_id":"call","tool_name":"Bash","tool_input":{"command":"rm test.txt"}}`)
	e := Event{Agent: "qoder-hooks", Hook: "PreToolUse", Kind: "tool.pre", Tool: "Bash"}
	e.CommandMatch = p.observeCommand(e, raw)
	if got := p.Evaluate(e, time.Now()); got.Decision != "deny" || got.Rule != "keyword" {
		t.Fatalf("keyword denial missing: %+v", got)
	}
	c.Executable = "rm"
	if c.valid() {
		t.Fatal("mixed keyword and executable condition accepted")
	}
}
