package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestWorkBuddyRequestTurnsAcrossResume(t *testing.T) {
	line := func(kind, id, role, request string) string {
		r := map[string]any{"type": kind, "id": id, "sessionId": "session-1", "timestamp": 1791340000000,
			"providerData": map[string]any{"conversationRequestId": request}}
		if kind == "message" {
			r["role"], r["content"] = role, []map[string]string{{"type": "text", "text": id}}
		} else {
			r["callId"], r["name"], r["arguments"] = id, "Bash", `{"command":"echo safe"}`
			r["output"] = map[string]string{"type": "text", "text": "safe"}
		}
		b, err := json.Marshal(r)
		if err != nil {
			t.Fatal(err)
		}
		return string(b) + "\n"
	}
	s := source(t, "workbuddy", line("message", "user-a", "user", "request-a")+
		line("function_call", "call-a", "", "request-a")+
		line("message", "user-b", "user", "request-b")+line("function_call", "call-b", "", "request-b"))
	policy := &AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true,
		Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	readBatch := func(c Cursor, want []string) ReadBatch {
		t.Helper()
		b, err := ReadWithPolicy(context.Background(), s, c, DefaultBudget(), time.Unix(0, 0), policy)
		if err != nil || len(b.Events) != len(want) {
			t.Fatalf("events=%d err=%v coverage=%v", len(b.Events), err, b.Coverage.Reasons)
		}
		for i, event := range b.Events {
			if event.TurnID != want[i] {
				t.Fatalf("event %d (%s): turn=%q want=%q", i, event.Kind, event.TurnID, want[i])
			}
			if err := ValidateEvent(event); err != nil {
				t.Fatal(err)
			}
		}
		return b
	}
	first := readBatch(Cursor{}, []string{"request-a", "request-a", "request-b", "request-b"})
	checkpoint, err := json.Marshal(first.Cursor)
	if err != nil {
		t.Fatal(err)
	}
	var resumed Cursor
	if err := json.Unmarshal(checkpoint, &resumed); err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.WriteString(line("function_call_result", "call-b", "", "request-b") +
		line("function_call_result", "call-a", "", "request-a") +
		line("message", "reply-a", "assistant", "request-a") + line("message", "reply-b", "assistant", "request-b") +
		line("message", "no-request", "user", ""))
	closeErr := f.Close()
	if err != nil {
		t.Fatal(err)
	}
	if closeErr != nil {
		t.Fatal(closeErr)
	}
	second := readBatch(resumed, []string{"request-b", "request-a", "request-a", "request-b", ""})
	if first.Events[1].LogicalCallID != second.Events[1].LogicalCallID || first.Events[3].LogicalCallID != second.Events[0].LogicalCallID {
		t.Fatal("call/result identity changed across resume")
	}
	readBatch(second.Cursor, nil)
}
