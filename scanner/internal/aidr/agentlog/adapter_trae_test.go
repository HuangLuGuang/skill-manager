package agentlog

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func traeRecord(id, raw string) string {
	return fmt.Sprintf("[1793024046944] [%s] --- Hook Execution Start ---\n[%s] stdin:\n%s\n[%s] --- Hook Execution End ---\n", id, id, raw, id)
}

func TestTraeSkillNativeEvidence(t *testing.T) {
	for _, agent := range []string{"trae", "trae-cn"} {
		call := ProjectSkillUse(agent, "Skill", "/test", json.RawMessage(`{"name":"aidr-probe"}`), nil)
		if call == nil || call.Name != "aidr-probe" || call.Basis != "tool_input.name" {
			t.Fatal(call)
		}
		result := ProjectSkillResult(agent, "Skill", json.RawMessage(`{"skill_path":"/test/.trae/skills/aidr-probe","skill_type":"skill"}`), nil, nil)
		if result == nil || result.Path != "/test/.trae/skills/aidr-probe/SKILL.md" || result.Phase != "host_loaded" {
			t.Fatal(result)
		}
		if ProjectSkillResult(agent, "Skill", json.RawMessage(`{"skill_path":"relative"}`), nil, nil) != nil {
			t.Fatal("relative result accepted")
		}
		if ProjectSkillResult(agent, "Skill", json.RawMessage(`{}`), nil, nil) != nil {
			t.Fatal("empty result marked loaded")
		}
	}
}

// Captured from TRAE 3.6.4 in an isolated test project; filesystem paths sanitized.
func TestTraeNativeFixture(t *testing.T) {
	data, err := os.ReadFile("testdata/trae-3.6.4/agent-hooks.txt")
	if err != nil {
		t.Fatal(err)
	}
	s := source(t, "trae", string(data))
	logPath := filepath.Join(s.Root, "agent-hooks.log")
	if err := os.Rename(s.Path, logPath); err != nil {
		t.Fatal(err)
	}
	discovery := Discover(context.Background(), "trae", s.Root, 10, 100, time.Second)
	if len(discovery.Sources) != 1 {
		t.Fatal(discovery)
	}
	p := AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
	b, err := ReadWithPolicy(context.Background(), discovery.Sources[0], Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || b.Coverage.Status != "complete" {
		t.Fatal(err, b.Coverage)
	}
	var calls, results, loaded, messages int
	for _, e := range b.Events {
		if err := ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
		if e.Kind == "tool_call" {
			calls++
		}
		if e.Kind == "tool_result" {
			results++
		}
		if e.SkillUse != nil && e.SkillUse.Phase == "host_loaded" {
			loaded++
		}
		if e.Message != nil {
			messages++
		}
	}
	if calls != 3 || results != 3 || loaded != 1 || messages < 3 {
		t.Fatalf("calls=%d results=%d loaded=%d messages=%d", calls, results, loaded, messages)
	}
}

func TestTraeCheckpointRemainsImmutableAndReset(t *testing.T) {
	header := "[1793024046944] [a] --- Hook Execution Start ---\n[a] stdin:\n"
	s := source(t, "trae", header)
	first := read(t, s, Cursor{})
	f, err := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(`{"session_id":"s","hook_event_name":"SessionStart"}` + "\n")
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	second := read(t, s, first.Cursor)
	if len(first.Cursor.TraeHooks) != 1 || first.Cursor.TraeInput != "a" || len(second.Cursor.TraeHooks) != 0 {
		t.Fatal("checkpoint mutated")
	}
	if err := os.WriteFile(s.Path, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	reset := read(t, s, first.Cursor)
	if len(reset.Cursor.TraeHooks) != 0 || reset.Cursor.TraeInput != "" {
		t.Fatal("stale header after truncation")
	}
}

func TestTraeLogReplayPrivacyAndResult(t *testing.T) {
	for _, agent := range []string{"trae", "trae-cn"} {
		body := traeRecord("a", `{"session_id":"s","hook_event_name":"UserPromptSubmit","prompt":"test TOKEN=SYNTHETIC_SECRET"}`) +
			traeRecord("b", `{"session_id":"s","hook_event_name":"PreToolUse","tool_use_id":"c","tool_name":"RunCommand","tool_input":{"command":"printf test"}}`) +
			traeRecord("c", `{"session_id":"s","hook_event_name":"PostToolUse","tool_use_id":"c","tool_name":"RunCommand","tool_response":{"exit_code":0,"stdout":"allowed"}}`) +
			traeRecord("d", `{"session_id":"s","hook_event_name":"PostToolUse","tool_use_id":"denied","tool_name":"RunCommand","tool_response":{}}`) +
			traeRecord("e", `{"session_id":"s","hook_event_name":"Stop","last_assistant_message":"done"}`)
		s := source(t, agent, body)
		p := AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
		b, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
		if err != nil || len(b.Events) != 5 {
			t.Fatalf("%s count %d err %v coverage %+v", agent, len(b.Events), err, b.Coverage)
		}
		for _, e := range b.Events {
			if err := ValidateEvent(e); err != nil {
				t.Fatal(err)
			}
		}
		if b.Events[2].Behavior.Status != "reported_success" || b.Events[3].Behavior.Status != "unknown" || b.Events[4].Message.Phase != "final" {
			t.Fatal("result semantics")
		}
		wire, _ := json.Marshal(b.Events)
		if strings.Contains(string(wire), "SYNTHETIC_SECRET") {
			t.Fatal("credential leaked")
		}
		again, err := ReadWithPolicy(context.Background(), s, b.Cursor, DefaultBudget(), time.Unix(0, 0), &p)
		if err != nil || len(again.Events) != 0 {
			t.Fatal("checkpoint replay", err)
		}
	}
}

func TestTraeHeaderCheckpointAndMissingHeader(t *testing.T) {
	c := Cursor{}
	for _, line := range []string{"[1793024046944] [a] --- Hook Execution Start ---", "[a] stdin:"} {
		if _, err := normalizeTrae([]byte(line), &c); err != nil {
			t.Fatal(err)
		}
	}
	b, _ := json.Marshal(c)
	var restored Cursor
	json.Unmarshal(b, &restored)
	d, err := normalizeTrae([]byte(`{"session_id":"s","hook_event_name":"Stop","last_assistant_message":"done"}`), &restored)
	if err != nil || len(d) != 1 {
		t.Fatal("lost header checkpoint", err)
	}
	missing := Cursor{TraeInput: "absent"}
	if _, err := normalizeTrae([]byte(`{}`), &missing); err == nil {
		t.Fatal("invented timestamp")
	}
}
