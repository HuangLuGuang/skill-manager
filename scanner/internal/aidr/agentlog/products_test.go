package agentlog

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestWorkBuddyIdentityResumeAndUnknownOutcome(t *testing.T) {
	s := source(t, "workbuddy", `{"type":"message","id":"msg-1","sessionId":"session-1","role":"user","timestamp":1791340000000,"content":[{"type":"input_text","text":"Run a harmless command"}]}`+"\n"+`{"type":"function_call","sessionId":"session-1","callId":"call-1","name":"Bash","timestamp":1791340000001,"arguments":"{\"command\":\"echo safe\"}"}`+"\n"+`{"type":"function_call_result","sessionId":"session-1","callId":"call-1","name":"Bash","status":"completed","timestamp":1791340000002,"output":{"type":"text","text":"safe"}}`+"\n")
	p := &AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true}}
	b, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), p)
	if err != nil || len(b.Events) != 3 {
		t.Fatalf("events=%d error=%v coverage=%v", len(b.Events), err, b.Coverage.Reasons)
	}
	if b.Events[2].Outcome != "unknown" || b.Events[1].LogicalCallID != b.Events[2].LogicalCallID || b.Events[1].Agent != "workbuddy" {
		t.Fatal("native identity/outcome lost")
	}
	again := read(t, s, b.Cursor)
	if len(again.Events) != 0 {
		t.Fatal("checkpoint replay")
	}
}

func TestOpenCodeSnapshotCompletionRewriteAndResume(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
	message := filepath.Join(root, "message", "ses_test", "msg_test.json")
	part := filepath.Join(root, "part", "msg_test", "prt_test.json")
	os.MkdirAll(filepath.Dir(message), 0700)
	os.MkdirAll(filepath.Dir(part), 0700)
	os.WriteFile(message, []byte(`{"id":"msg_test","sessionID":"ses_test","role":"assistant","time":{"created":1791340000000}}`), 0600)
	os.WriteFile(part, []byte(`{"id":"prt_test","sessionID":"ses_test","messageID":"msg_test","type":"text","text":"draft"}`), 0600)
	s, err := NewSource("opencode", root, part)
	if err != nil {
		t.Fatal(err)
	}
	p := &AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{ModelResponse: true}}
	first, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), p)
	if err != nil || len(first.Events) != 0 || first.Cursor.Offset != 0 || !has(first, "aidr_log_snapshot_pending") {
		t.Fatal("incomplete snapshot consumed", err)
	}
	os.WriteFile(message, []byte(`{"id":"msg_test","sessionID":"ses_test","role":"assistant","finish":"stop","time":{"created":1791340000000,"completed":1791340001000}}`), 0600)
	os.WriteFile(part, []byte(`{"id":"prt_test","sessionID":"ses_test","messageID":"msg_test","type":"text","text":"final"}`), 0600)
	final, err := ReadWithPolicy(context.Background(), s, first.Cursor, DefaultBudget(), time.Unix(0, 0), p)
	if err != nil || len(final.Events) != 1 || final.Events[0].Message.Phase != "final" {
		t.Fatal("completed snapshot missing", err)
	}
	again, err := ReadWithPolicy(context.Background(), s, final.Cursor, DefaultBudget(), time.Unix(0, 0), p)
	if err != nil || len(again.Events) != 0 {
		t.Fatal("snapshot duplicated", err)
	}
}

// Opt-in, read-only validation against installed products. Output contains only
// aggregate metadata. Real conversations are never copied into fixtures.
func TestLocalProductSamples(t *testing.T) {
	if os.Getenv("AIDR_LOCAL_PRODUCT_SAMPLES") != "1" {
		t.Skip("local samples not requested")
	}
	home, _ := os.UserHomeDir()
	for agent, dir := range map[string]string{"workbuddy": ".workbuddy/projects", "qoder-cli": ".qoder/projects", "opencode": ".local/share/opencode/storage"} {
		root := filepath.Join(home, dir)
		counts := map[string]int{}
		files := 0
		err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() || !SourceFile(agent, root, path) {
				return nil
			}
			s, err := NewSource(agent, root, path)
			if err != nil {
				return err
			}
			files++
			p := &AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
			c := Cursor{}
			for i := 0; i < 1000; i++ {
				b, err := ReadWithPolicy(context.Background(), s, c, DefaultBudget(), time.Unix(0, 0), p)
				if err != nil {
					return err
				}
				for _, e := range b.Events {
					if err := ValidateEvent(e); err != nil {
						t.Logf("invalid agent=%s kind=%s bytes=%d callValid=%t timeZero=%t", agent, e.Kind, e.ContentBytes, token(e.CallID) != "", e.ObservedAt.IsZero())
						return err
					}
					counts[e.Kind]++
				}
				if b.Cursor.Offset == c.Offset {
					if b.Coverage.Status != "complete" && !has(b, "aidr_log_snapshot_pending") {
						t.Errorf("%s stalled reasons=%v", agent, b.Coverage.Reasons)
					}
					break
				}
				c = b.Cursor
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("%s files=%d event_counts=%v", agent, files, counts)
		if files == 0 || counts["tool_call"] == 0 {
			t.Fatal("no real sample coverage")
		}
	}
}
