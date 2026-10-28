package agentlog

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestQwenWorkNativeSkillKeepsAliasWithoutInventingPath(t *testing.T) {
	raw, err := os.ReadFile("testdata/qwenwork-cn-1.4.0/skill.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	c := Cursor{}
	found := false
	for _, line := range bytes.Split(bytes.TrimSpace(raw), []byte("\n")) {
		drafts, err := normalize("qwenwork", line, &c)
		if err != nil {
			t.Fatal(err)
		}
		for _, d := range drafts {
			if d.Kind != "tool_call" || d.Tool != "Skill" {
				continue
			}
			found = true
			var record struct {
				Message struct {
					Content []struct {
						Type  string
						Input json.RawMessage
					}
				}
			}
			if err := json.Unmarshal(line, &record); err != nil {
				t.Fatal(err)
			}
			for _, block := range record.Message.Content {
				if block.Type != "tool_use" {
					continue
				}
				use := ProjectSkillUse("qwenwork", "Skill", "", block.Input, nil)
				if use == nil || !strings.HasPrefix(use.Name, "qwenwork-extension-") || use.Path != "" {
					t.Fatal("native alias changed", use)
				}
			}
		}
	}
	if !found {
		t.Fatal("native Skill call missing")
	}
}

func TestQwenWorkNativeTranscriptAndRestart(t *testing.T) {
	raw, err := os.ReadFile("testdata/qwenwork-cn-1.4.0/session.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	c := Cursor{}
	tools, results, models := 0, 0, 0
	for _, line := range bytes.Split(bytes.TrimSpace(raw), []byte("\n")) {
		ds, err := normalize("qwenwork", line, &c)
		if err != nil {
			t.Fatal(err)
		}
		for _, d := range ds {
			if d.Turn == "" {
				t.Fatalf("lost native ancestry: %s %s", d.Kind, d.Call)
			}
			if d.Kind == "tool_call" {
				tools++
			}
			if d.Kind == "tool_result" {
				results++
			}
			if d.ModelContext != nil {
				models++
			}
		}
		checkpoint, _ := json.Marshal(c)
		c = Cursor{}
		if err := json.Unmarshal(checkpoint, &c); err != nil {
			t.Fatal(err)
		}
	}
	if tools != 4 || results != 4 || models == 0 {
		t.Fatalf("tools=%d results=%d models=%d", tools, results, models)
	}
	s := source(t, "qwenwork", string(raw))
	first := read(t, s, Cursor{})
	if len(first.Events) == 0 || first.Coverage.Status != "complete" {
		t.Fatalf("%+v", first.Coverage)
	}
	if next := read(t, s, first.Cursor); len(next.Events) != 0 {
		t.Fatal("unchanged transcript replayed")
	}
}

func TestQwenWorkMissingAncestryStaysUnassigned(t *testing.T) {
	ds, err := normalize("qwenwork", []byte(`{"type":"assistant","entrypoint":"cli","sessionId":"s","uuid":"a","parentUuid":"missing","timestamp":"2026-10-28T00:00:00Z","message":{"content":[{"type":"tool_use","id":"c","name":"Read","input":{"file_path":"/tmp/probe"}}]}}`), &Cursor{})
	if err != nil || len(ds) != 1 || ds[0].Turn != "" {
		t.Fatal(ds, err)
	}
}
