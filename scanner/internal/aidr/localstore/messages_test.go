package localstore

import (
	"encoding/json"
	"os"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"testing"
)

func TestMessagePolicyReplayPreservesFrozenContent(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	defer s.Close()
	raw := `{"type":"assistant","uuid":"reply-a","sessionId":"s","version":"2.1.220","timestamp":"2026-09-23T10:00:00Z","message":{"stop_reason":"end_turn","content":[{"type":"text","text":"A bounded model reply"}]}}` + "\n"
	src := source(t, raw)
	policy := agentlog.AuditPolicy{MessageSchema: 1, Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &agentlog.CaptureScope{ModelResponse: true}}
	if err := s.SavePolicy(testContext, policy); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(frozen.Payload), "A bounded model reply") {
		t.Fatal("message absent from durable outbox")
	}
	policy.Version = "3"
	policy.Receipt = strings.Repeat("b", 32)
	policy.Capture.ModelResponse = false
	if err := s.SavePolicy(testContext, policy); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(src.Path, src.Path+".old"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(src.Path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	again, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || string(again.Payload) != string(frozen.Payload) {
		t.Fatal("frozen batch changed")
	}
	page, err := s.Events(testContext, "", 500)
	if err != nil || len(page.Events) != 1 {
		t.Fatal("message replay duplicated")
	}
	var event agentlog.Event
	if json.Unmarshal(page.Events[0], &event) != nil || event.Message == nil || event.Message.Policy.Version != "2" || len(event.Message.Contents) != 1 {
		t.Fatal("original message projection lost")
	}
}
