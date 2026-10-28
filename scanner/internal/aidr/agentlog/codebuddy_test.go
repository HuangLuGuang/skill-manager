package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func codeBuddyFixture(t *testing.T) Source {
	t.Helper()
	root, _ := filepath.EvalSymlinks(t.TempDir())
	err := os.CopyFS(root, os.DirFS("testdata/codebuddy-4.12.2"))
	if err != nil {
		t.Fatal(err)
	}
	d := Discover(context.Background(), "codebuddy", root, 10, 100, time.Second)
	if len(d.Sources) != 1 {
		t.Fatalf("discovery: %+v", d)
	}
	return d.Sources[0]
}

func codeBuddyPolicy() *AuditPolicy {
	return &AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, MessageSchema: 1, ModelContextSchema: 1, Capture: &CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true, FileBody: true}}
}

func TestCodeBuddyRealSessionAndSnapshotUpdates(t *testing.T) {
	s := codeBuddyFixture(t)
	cache := &ReadCache{}
	first, err := cache.Read(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy(), NewSkillObserver())
	if err != nil || first.Coverage.Status != "complete" || !first.Cursor.ScanComplete {
		t.Fatalf("%v %+v", err, first.Coverage)
	}
	counts := map[string]int{}
	calls := map[string]string{}
	denied, exit, skill := false, false, false
	for _, e := range first.Events {
		if e.TurnID == "" || e.SessionID == "" || e.ModelContext == nil {
			t.Fatalf("missing context: %+v", e)
		}
		counts[e.Kind]++
		if e.Kind == "tool_call" {
			calls[e.CallID] = e.LogicalCallID
			if len(e.Behavior.Actions) > 0 && e.Behavior.Actions[0].Cwd != "/workspace/codebuddy" {
				t.Fatal("workspace lost", e.Behavior)
			}
		}
		if e.Kind == "tool_result" {
			if calls[e.CallID] != e.LogicalCallID {
				t.Fatal("call/result mismatch", e.CallID)
			}
			denied = denied || e.Outcome == "error" && e.Behavior.Status == "reported_error"
			exit = exit || e.Behavior.ExitCode != nil && *e.Behavior.ExitCode == 0
			skill = skill || e.SkillUse != nil && e.SkillUse.Path == "/workspace/codebuddy/.codebuddy/skills/aidr-probe/SKILL.md"
		}
	}
	if counts["user_message"] != 2 || counts["tool_call"] != 4 || counts["tool_result"] != 4 || !denied || !exit || !skill {
		t.Fatalf("counts=%v denied=%v exit=%v skill=%v", counts, denied, exit, skill)
	}
	second, err := cache.Read(context.Background(), s, first.Cursor, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy(), NewSkillObserver())
	if err != nil || len(second.Events) != 0 {
		t.Fatal("unchanged cache replay", err)
	}
	// A fresh collector can replay the snapshot with the exact same evidence IDs.
	replay, err := ReadWithPolicy(context.Background(), s, first.Cursor, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy())
	if err != nil || len(replay.Events) != len(first.Events) {
		t.Fatal("restart replay", err)
	}
	for i, e := range replay.Events {
		if e.EventID != first.Events[i].EventID || e.LogicalEventID != first.Events[i].LogicalEventID {
			t.Fatal("unstable identity")
		}
	}
	path := filepath.Join(filepath.Dir(s.Path), "messages", "5982f19b33f64b4498924144e344e96d.json")
	body, _ := os.ReadFile(path)
	if err := os.WriteFile(path, []byte(strings.ReplaceAll(string(body), "CODEBUDDY_ALLOWED_OK", "CODEBUDDY_UPDATED_OK")), 0600); err != nil {
		t.Fatal(err)
	}
	changed, err := cache.Read(context.Background(), s, second.Cursor, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy(), NewSkillObserver())
	if err != nil || len(changed.Events) == 0 {
		t.Fatal("message-only change missed", err)
	}
}

func TestCodeBuddyPendingBudgetsAndUnsafeMessagePaths(t *testing.T) {
	s := codeBuddyFixture(t)
	raw, _ := os.ReadFile(s.Path)
	var index codeBuddyIndex
	json.Unmarshal(raw, &index)
	index.Requests[0].State = "running"
	updated, _ := json.Marshal(index)
	os.WriteFile(s.Path, updated, 0600)
	first, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy())
	if err != nil || !has(first, "aidr_log_snapshot_pending") {
		t.Fatal("pending request accepted", err)
	}
	os.WriteFile(s.Path, raw, 0600)
	budget := DefaultBudget()
	budget.Events = 3
	cursor := first.Cursor
	ids := map[string]bool{}
	for i := 0; i < 20; i++ {
		batch, e := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), codeBuddyPolicy())
		if e != nil {
			t.Fatal(e)
		}
		cursor = batch.Cursor
		for _, event := range batch.Events {
			if ids[event.EventID] {
				t.Fatal("duplicate within snapshot")
			}
			ids[event.EventID] = true
		}
		if cursor.ScanComplete {
			break
		}
	}
	if !cursor.ScanComplete || len(ids) < 12 {
		t.Fatal("budget resume lost data", len(ids))
	}
	path := filepath.Join(filepath.Dir(s.Path), "messages", index.Messages[0].ID+".json")
	os.Remove(path)
	os.Symlink("/etc/passwd", path)
	unsafe, e := ReadWithPolicy(context.Background(), s, cursor, DefaultBudget(), time.Unix(0, 0), codeBuddyPolicy())
	if e != nil || !has(unsafe, "aidr_log_symlink") {
		t.Fatal("symlink not reported", e, unsafe.Coverage)
	}
}

func TestCodeBuddyResultDoesNotTrustOutputText(t *testing.T) {
	for _, tc := range []struct{ raw, want string }{
		{`{"serverName":"aidr_probe","toolName":"deny_probe","arguments":"{}"}`, "mcp__aidr_probe__deny_probe"},
		{`{"type":"mcp_call_tool_result","serverName":"aidr_probe","toolName":"allow_probe"}`, "mcp__aidr_probe__allow_probe"},
		{`{"serverName":"aidr_probe"}`, "mcp_call_tool"},
	} {
		if got := CodeBuddyToolName("mcp_call_tool", json.RawMessage(tc.raw)); got != tc.want {
			t.Fatal(got, tc.want)
		}
	}
	for _, tc := range []struct{ raw, status string }{
		{`{"exitCode":7}`, "reported_error"},
		{`{"exitCode":0,"stdout":"exitCode=9"}`, "reported_success"},
		{`"{\"exitCode\":0}"`, "unknown"},
		{`{"exitCode":null}`, "unknown"},
		{`{"exitCode":0,"isError":true}`, "unknown"},
	} {
		b, err := ProjectCodeBuddyToolEvidence("Bash", "tool_result", "", json.RawMessage(tc.raw), "unknown", *codeBuddyPolicy())
		if err != nil || b.Status != tc.status {
			t.Fatal(tc, err, b)
		}
	}
}
