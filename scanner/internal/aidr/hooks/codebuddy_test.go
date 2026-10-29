package hooks

import (
	"bytes"
	"encoding/json"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"testing"
)

func TestCodeBuddyHookNativeIdentityFieldsAndDecision(t *testing.T) {
	p := agentlog.AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &agentlog.CaptureScope{ToolOutput: true}}
	key := []byte(strings.Repeat("k", 32))
	raw := []byte(`{"hook_event_name":"PreToolUse","session_id":"s","generation_id":"request-1","cwd":"/","tool_name":"Read","tool_input":{"filePath":"/workspace/SKILL.md"},"model":"auto"}`)
	e, err := Normalize("codebuddy", "PreToolUse", raw, p, key)
	if err != nil || e.Turn != "request-1" || e.Call != "" || e.Context.Cwd != "" || e.SkillUse == nil || e.SkillUse.Path != "/workspace/SKILL.md" {
		t.Fatal(err, e)
	}
	if e.CallKey("device", "user") != "" {
		t.Fatal("fabricated native call identity")
	}
	if e.Behavior.Actions[0].Targets[0].Value != "/workspace/SKILL.md" {
		t.Fatal("filePath missing")
	}
	raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"s","generation_id":"request-2","tool_name":"Skill","tool_input":{"command":"aidr-probe"}}`)
	e, err = Normalize("codebuddy", "PreToolUse", raw, p, key)
	if err != nil || e.SkillUse == nil || e.SkillUse.Name != "aidr-probe" || e.SkillUse.Basis != "tool_input.command" {
		t.Fatal(err, e)
	}
	var out bytes.Buffer
	raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"s","generation_id":"request-3","tool_name":"mcp_call_tool","tool_input":{"serverName":"aidr_probe","toolName":"deny_probe","arguments":"{}"}}`)
	e, err = Normalize("codebuddy", "PreToolUse", raw, p, key)
	if err != nil || e.Tool != "mcp__aidr_probe__deny_probe" {
		t.Fatal(err, e)
	}
	if err := hookAdapters["codebuddy"].WriteDecision(&out, "PreToolUse", "deny", "test rule"); err != nil {
		t.Fatal(err)
	}
	var decision struct {
		Continue           bool
		HookSpecificOutput struct{ PermissionDecision string }
	}
	if json.Unmarshal(out.Bytes(), &decision) != nil || decision.Continue || decision.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal(out.String())
	}
	raw = []byte(`{"hook_event_name":"PostToolUse","session_id":"s","generation_id":"request-2","tool_name":"Bash","tool_response":{"exitCode":0,"stdout":"CODEBUDDY_OK","stderr":""}}`)
	e, err = Normalize("codebuddy", "PostToolUse", raw, p, key)
	if err != nil || e.Behavior.Status != "reported_success" || len(e.Behavior.Contents) != 1 {
		t.Fatal(err, e)
	}
}
