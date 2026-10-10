package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestAgentLogDurableCLI(t *testing.T) {
	root, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	src := filepath.Join(root, "claude.jsonl")
	body, e := os.ReadFile("../../internal/aidr/agentlog/testdata/claude-2.1.220.jsonl")
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(src, body, 0600); e != nil {
		t.Fatal(e)
	}
	dir := filepath.Join(root, "state")
	args := []string{"--state-dir", dir, "--agent", "claude", "--root", root, "--file", src, "--since", "1970-01-01T00:00:00Z"}
	for n := 0; n < 2; n++ {
		var out bytes.Buffer
		if e = agentLogState("agent-log-collect", args, &out); e != nil {
			t.Fatal(e)
		}
		if !json.Valid(out.Bytes()) {
			t.Fatal("invalid output")
		}
	}
	var out bytes.Buffer
	if e = agentLogState("agent-log-state", []string{"--state-dir", dir}, &out); e != nil {
		t.Fatal(e)
	}
	var status struct {
		LogicalEvents int    `json:"logical_events"`
		Evidence      int    `json:"evidence"`
		Acknowledged  string `json:"acknowledged_sequence"`
	}
	if e = json.Unmarshal(out.Bytes(), &status); e != nil {
		t.Fatal(e)
	}
	if status.LogicalEvents != 16 || status.Evidence != 16 || status.Acknowledged != "0" {
		t.Fatal(status)
	}
	current, _ := os.ReadFile(src)
	if !bytes.Equal(current, body) {
		t.Fatal("source modified")
	}
	if e = agentLogState("agent-log-state", []string{"--state-dir", dir, "--action", "ack"}, &out); e == nil {
		t.Fatal("unknown operation accepted")
	}
}
