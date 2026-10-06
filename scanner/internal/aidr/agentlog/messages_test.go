package agentlog

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestConversationCaptureAndPhases(t *testing.T) {
	s := source(t, "codex", codexRecord("session_meta", `{"id":"session-a","cli_version":"0.160.0"}`)+
		codexRecord("event_msg", `{"type":"task_started","turn_id":"turn-a"}`)+
		codexRecord("response_item", `{"type":"message","id":"u","role":"user","content":[{"type":"input_text","text":"Explain the result"}]}`)+
		codexRecord("response_item", `{"type":"message","id":"p","role":"assistant","phase":"commentary","content":[{"type":"output_text","text":"Checking TOKEN=SYNTHETIC_SECRET"}]}`)+
		codexRecord("response_item", `{"type":"message","id":"f","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"The result is ready"}]}`)+
		codexRecord("response_item", `{"type":"message","id":"x","role":"assistant","content":[{"type":"output_text","text":"Unspecified reply"}]}`))
	p := AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	b, e := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if e != nil || len(b.Events) != 4 {
		t.Fatalf("count=%d err=%v coverage=%+v", len(b.Events), e, b.Coverage)
	}
	for i, phase := range []string{"unspecified", "commentary", "final", "unspecified"} {
		ev := b.Events[i]
		if ValidateEvent(ev) != nil || ev.Message.Phase != phase || ev.TurnID != "turn-a" || len(ev.Message.Contents) != 1 {
			t.Fatalf("invalid message %d", i)
		}
	}
	raw, _ := json.Marshal(b.Events)
	if strings.Contains(string(raw), "SYNTHETIC_SECRET") {
		t.Fatal("unredacted content")
	}
	again, e := ReadWithPolicy(context.Background(), s, b.Cursor, DefaultBudget(), time.Unix(0, 0), &p)
	if e != nil || len(again.Events) != 0 {
		t.Fatal("cursor replay")
	}
	p.Capture.ModelResponse = false
	off, _ := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if len(off.Events[0].Message.Contents) != 1 || len(off.Events[1].Message.Contents) != 0 || off.Events[1].Message.ContentStatus != "not_requested" {
		t.Fatal("scope isolation")
	}
	p.MessageSchema = 0
	legacy, _ := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if len(legacy.Events) != 0 {
		t.Fatal("server without message support received new events")
	}
}

func TestClaudeTextPhasesAndSyntheticErrors(t *testing.T) {
	lines := `{"type":"user","uuid":"u","sessionId":"s","version":"2.1.220","timestamp":"2026-09-23T10:00:00Z","message":{"content":"question"}}` + "\n"
	for _, reason := range []string{"tool_use", "end_turn", ""} {
		lines += `{"type":"assistant","uuid":"` + reason + `","sessionId":"s","version":"2.1.220","timestamp":"2026-09-23T10:00:00Z","message":{"stop_reason":"` + reason + `","content":[{"type":"text","text":"reply"}]}}` + "\n"
	}
	lines += `{"type":"assistant","isApiErrorMessage":true,"sessionId":"s","timestamp":"2026-09-23T10:00:00Z","message":{"model":"<synthetic>","content":[{"type":"text","text":"API ERROR"}]}}` + "\n"
	s := source(t, "claude", lines)
	p := AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	b, e := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if e != nil || len(b.Events) != 4 {
		t.Fatalf("count=%d err=%v", len(b.Events), e)
	}
	for i, phase := range []string{"unspecified", "commentary", "final", "unspecified"} {
		if b.Events[i].Message.Phase != phase || ValidateEvent(b.Events[i]) != nil {
			t.Fatalf("phase %d", i)
		}
	}
}
