package hooks

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestCommandBodyHookBudgetPersistence(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 20)
	defer s.Close()
	p := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{CommandBody: true, MaxFragmentBytes: 32768, MaxEventBytes: 32768}}
	if err := s.SetPolicy(ctx, p); err != nil {
		t.Fatal(err)
	}
	command := "cat <<'EOF'\n" + strings.Repeat("<", 40000) + "\nEOF"
	raw, _ := json.Marshal(map[string]any{"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash", "tool_input": map[string]string{"command": command}})
	r, err := s.Receive(ctx, testID(9), "501", "claude", "PreToolUse", raw)
	if err != nil {
		t.Fatal(err)
	}
	body := r.Event.Behavior.Contents[0]
	if !body.Truncated || len(body.Text) != 32768 || !strings.HasPrefix(body.Text, "cat <<'EOF'\n") {
		t.Fatal(body)
	}
	encoded, _ := json.Marshal(r)
	if len(encoded) >= MaxRecordBytes {
		t.Fatal("encoded hook exceeds storage contract", len(encoded))
	}
	frozen, err := s.Prepare(ctx)
	if err != nil || frozen == nil || !bytes.Contains(frozen.Payload, []byte("command_body")) {
		t.Fatal(err)
	}
	p.Capture = &agentlog.CaptureScope{}
	p.Version, p.Receipt = "3", strings.Repeat("b", 32)
	if err := s.SetPolicy(ctx, p); err != nil {
		t.Fatal(err)
	}
	retained, err := s.Prepare(ctx)
	if err != nil || !bytes.Equal(frozen.Payload, retained.Payload) {
		t.Fatal("pending batch changed after policy update", err)
	}
}

func TestContentPolicyPersistenceFrozenMigrationAndReplay(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 20)
	oldID := testID(1)
	if _, err := s.Receive(ctx, oldID, "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
		t.Fatal(err)
	}
	frozen, err := s.Prepare(ctx)
	if err != nil || frozen == nil {
		t.Fatal(err)
	}
	policy := agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &agentlog.CaptureScope{Prompt: true, FileBody: true, ToolOutput: true}}
	if err := s.SetPolicy(ctx, policy); err != nil {
		t.Fatal(err)
	}
	raw := []byte(`{"hook_event_name":"UserPromptSubmit","session_id":"s","prompt":"TOKEN=SYNTHETIC-PERSIST-SECRET"}`)
	record, err := s.Receive(ctx, testID(2), "501", "codex", "UserPromptSubmit", raw)
	if err != nil || record.Event.Schema != 2 || record.Event.Contents[0].Text != "TOKEN=[REDACTED]" {
		t.Fatal(record, err)
	}
	files, _ := filepath.Glob(filepath.Join(dir, "*"))
	for _, file := range files {
		data, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		if bytes.Contains(data, []byte("SYNTHETIC-PERSIST-SECRET")) {
			t.Fatal("raw secret persisted", filepath.Base(file))
		}
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openTestStore(t, dir, 20)
	status, err := s.Status(ctx)
	if err != nil || !status.Policy.Equal(policy) {
		t.Fatal(status, err)
	}
	next, err := s.Prepare(ctx)
	if err != nil || !bytes.Equal(frozen.Payload, next.Payload) || frozen.Digest != next.Digest {
		t.Fatal("old frozen batch changed", err)
	}
	old, err := s.Receive(ctx, oldID, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || old.Event.Schema != 1 || old.Event.ContentStatus != "" {
		t.Fatal("old projection reprocessed", old, err)
	}
	newer := policy
	newer.Version = "3"
	newer.Receipt = strings.Repeat("b", 32)
	newer.Capture = &agentlog.CaptureScope{}
	if err := s.SetPolicy(ctx, newer); err != nil {
		t.Fatal(err)
	}
	replay, err := s.Receive(ctx, record.EventID, "501", "codex", "UserPromptSubmit", raw)
	a, _ := json.Marshal(record)
	b, _ := json.Marshal(replay)
	if err != nil || !bytes.Equal(a, b) {
		t.Fatal("policy switch changed pending record", err)
	}
	nextRecord, err := s.Receive(ctx, testID(3), "501", "codex", "UserPromptSubmit", raw)
	if err != nil || len(nextRecord.Event.Contents) != 0 || nextRecord.Event.ContentStatus != "not_requested" {
		t.Fatal(nextRecord, err)
	}
}
