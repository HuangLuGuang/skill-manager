package hooks

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestCommandNetworksSharedVectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/command_networks.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Networks NetworkCondition `json:"networks"`
		Command  string           `json:"command"`
		Want     string           `json:"want"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		c := &CommandCondition{Networks: &tc.Networks}
		if !c.valid() {
			t.Fatal("valid condition rejected")
		}
		if got := commandMatch(c, tc.Command, "", "deny"); got != tc.Want {
			t.Errorf("%q: got %s want %s", tc.Command, got, tc.Want)
		}
	}
}

func TestCommandNetworksValidationAndPolicy(t *testing.T) {
	for _, subnets := range [][]string{nil, {""}, {"10.0.0.0"}, {"10.0.0.0/33"}, {"::/129"}, {"host/24"}, {"10.0.0.0/024"}, {"::/032"}, {" 10.0.0.0/8"}, {"::1%eth0/128"}, {"010.0.0.0/8"}, {"10.0.0.0/255.0.0.0"}, make([]string, 17)} {
		if (&CommandCondition{Networks: &NetworkCondition{Subnets: subnets}}).valid() {
			t.Fatalf("invalid subnets accepted: %v", subnets)
		}
	}
	c := &CommandCondition{Networks: &NetworkCondition{Subnets: []string{"10.10.71.0/24", "2001:db8::/32"}}}
	if commandMatch(c, strings.Repeat("x", 32769), "", "deny") != "unresolved" {
		t.Fatal("unbounded command accepted")
	}
	for _, decision := range []string{"deny", "ask", "allow"} {
		p := ToolPolicy{Revision: "1", Default: "deny", Rules: []ToolRule{{ID: "network", Agent: "*", Tool: "*", Decision: decision, Command: c}}}
		for _, command := range []string{"curl http://10.10.71.23", "curl http://[2001:db8::23]:443"} {
			raw, _ := json.Marshal(map[string]any{"hook_event_name": "PreToolUse", "session_id": "test", "tool_use_id": "call", "tool_name": "Bash", "tool_input": map[string]string{"command": command}})
			e := Event{Agent: "qoder-hooks", Hook: "PreToolUse", Kind: "tool.pre", Tool: "Bash"}
			e.CommandMatch = p.observeCommand(e, raw)
			if got := p.Evaluate(e, time.Now()); got.Decision != decision || got.Rule != "network" {
				t.Fatalf("network policy missing: %+v", got)
			}
		}
	}
	c.Executable = "curl"
	if c.valid() {
		t.Fatal("mixed conditions accepted")
	}
}
