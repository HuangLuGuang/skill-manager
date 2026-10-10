package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAgentLogReadCLIAndResume(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "fixture.jsonl")
	raw := `{"type":"assistant","timestamp":"2026-09-23T10:00:00Z","sessionId":"s","version":"2.1.220","message":{"content":[{"type":"tool_use","id":"c","name":"Read","input":{"path":"/tmp/audit.txt","password":"SYNTHETIC_SECRET"}}]}}` + "\n"
	os.WriteFile(path, []byte(raw), 0600)
	args := []string{"--agent", "claude", "--root", root, "--file", path, "--since", "2026-09-22T00:00:00Z"}
	var out bytes.Buffer
	if err := readAgentLog(args, &out); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "SYNTHETIC_SECRET") {
		t.Fatal("secret leaked")
	}
	var batch struct {
		Cursor json.RawMessage   `json:"cursor"`
		Events []json.RawMessage `json:"events"`
	}
	if json.Unmarshal(out.Bytes(), &batch) != nil || len(batch.Events) != 1 {
		t.Fatal(out.String())
	}
	cp := filepath.Join(root, "cursor.json")
	os.WriteFile(cp, batch.Cursor, 0600)
	out.Reset()
	if err := readAgentLog(append(args, "--cursor", cp), &out); err != nil {
		t.Fatal(err)
	}
	if json.Unmarshal(out.Bytes(), &batch) != nil || len(batch.Events) != 0 {
		t.Fatal("replayed cursor")
	}
	after, _ := os.ReadFile(path)
	if string(after) != raw {
		t.Fatal("source mutated")
	}
	checkpoint, _ := os.ReadFile(cp)
	if !bytes.Equal(checkpoint, batch.Cursor) {
		t.Fatal("cursor overwritten")
	}
}
func TestAgentLogCLIRejectsInvalidOptions(t *testing.T) {
	for _, args := range [][]string{{"--agent", "bad"}, {"--agent", "claude", "--max-bytes", "0"}, {"--agent", "codex", "--cursor", "unused"}, {"--agent", "claude", "--since", "bad"}} {
		if readAgentLog(args, &bytes.Buffer{}) == nil {
			t.Fatalf("accepted %v", args)
		}
	}
}
