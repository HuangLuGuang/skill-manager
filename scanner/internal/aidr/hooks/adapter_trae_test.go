package hooks

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestTraeNativeCommandAndRejectedPost(t *testing.T) {
	for _, agent := range []string{"trae", "trae-cn"} {
		raw := `{"hook_event_name":"PreToolUse","session_id":"s","agent_id":"solo_agent","tool_use_id":"call-1","tool_name":"RunCommand","cwd":"/test","workspace_roots":["/test"],"tool_input":{"command":"printf test","cwd":"/test"}}`
		e := normalize(t, agent, "PreToolUse", raw, true)
		if e.Behavior.Category != "command" || e.Context.WorkspaceRoots[0] != "/test" || e.Call != "call-1" {
			t.Fatalf("%+v", e)
		}
		post := `{"hook_event_name":"PostToolUse","session_id":"s","tool_use_id":"call-1","tool_name":"RunCommand","tool_response":{}}`
		e = normalize(t, agent, "PostToolUse", post, true)
		if e.Behavior.Status != "unknown" || e.Behavior.ExitCode != nil {
			t.Fatalf("rejected result became success: %+v", e.Behavior)
		}
		var out bytes.Buffer
		if err := WriteHostDecision(&out, agent, "PreToolUse", "deny", "test policy"); err != nil {
			t.Fatal(err)
		}
		var decision struct {
			Output struct {
				Decision string `json:"permissionDecision"`
			} `json:"hookSpecificOutput"`
		}
		if json.Unmarshal(out.Bytes(), &decision) != nil || decision.Output.Decision != "deny" {
			t.Fatal(out.String())
		}
		out.Reset()
		if err := WriteHostDecision(&out, agent, "PreToolUse", "ask", "approval required"); err != nil {
			t.Fatal(err)
		}
		if json.Unmarshal(out.Bytes(), &decision) != nil || decision.Output.Decision != "ask" {
			t.Fatal(out.String())
		}
		skill := normalize(t, agent, "PreToolUse", `{"hook_event_name":"PreToolUse","session_id":"s","tool_use_id":"skill","tool_name":"Skill","tool_input":{"name":"aidr-probe"}}`, true)
		if skill.SkillUse == nil || skill.SkillUse.Name != "aidr-probe" {
			t.Fatal(skill)
		}
		mcp := normalize(t, agent, "PreToolUse", `{"hook_event_name":"PreToolUse","session_id":"s","tool_use_id":"mcp","tool_name":"mcp__probe__echo","tool_input":{"text":"test"}}`, true)
		if mcp.Tool != "mcp__probe__echo" {
			t.Fatal(mcp)
		}
	}
}
