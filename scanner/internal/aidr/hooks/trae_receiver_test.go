//go:build darwin || linux

package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestTraeReceiverSignedCommandPolicy(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 20)
	defer s.Close()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err := s.ConfigureControl(ctx, elliptic.Marshal(elliptic.P256(), key.X, key.Y)); err != nil {
		t.Fatal(err)
	}
	p := ToolPolicy{Schema: 3, Domain: "aidr.tool-policy/3", Device: "device-a", Revision: "1", Issued: fmt.Sprint(time.Now().Unix()), Default: "allow", Rules: []ToolRule{{ID: "trae-deny", Agent: "trae", Tool: "RunCommand", Decision: "deny", Command: &CommandCondition{Executable: "printf", ArgsAll: []string{"denied"}}}}}
	p.Rules = append(p.Rules,
		ToolRule{ID: "skill-deny", Agent: "trae", Tool: "Skill", Decision: "deny"},
		ToolRule{ID: "mcp-deny", Agent: "trae", Tool: "mcp__probe__echo", Decision: "deny"},
		ToolRule{ID: "cn-terminal-deny", Agent: "trae-cn", Tool: "RunCommand", Decision: "deny"})
	if err := s.ApplyToolPolicy(ctx, signGrant(t, key, p), time.Now()); err != nil {
		t.Fatal(err)
	}
	root, err := os.MkdirTemp("", "tr-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	root, _ = filepath.EvalSymlinks(root)
	socket := filepath.Join(root, "r.sock")
	r, err := Listen(socket, s)
	if err != nil {
		t.Fatal(err)
	}
	serve, cancel := context.WithCancel(ctx)
	done := make(chan error, 1)
	go func() { done <- r.Serve(serve) }()
	defer func() { cancel(); <-done }()
	for i, tc := range []struct{ agent, tool, input, want string }{
		{"trae", "RunCommand", `{"command":"printf allowed"}`, "allow"},
		{"trae", "RunCommand", `{"command":"printf denied"}`, "deny"},
		{"trae", "RunCommand", `{"command":"printf denied > marker"}`, "allow"},
		{"trae", "Skill", `{"name":"aidr-probe"}`, "deny"},
		{"trae", "mcp__probe__echo", `{"text":"test"}`, "deny"},
		{"trae-cn", "RunCommand", `{"command":"printf denied > marker"}`, "deny"},
	} {
		raw := json.RawMessage(fmt.Sprintf(`{"hook_event_name":"PreToolUse","session_id":"s","tool_use_id":"c%d","tool_name":%q,"cwd":"/test","tool_input":%s}`, i, tc.tool, tc.input))
		response, err := Exchange(ctx, socket, IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(i + 1), Agent: tc.agent, Hook: "PreToolUse", Raw: raw})
		if err != nil {
			t.Fatal(err)
		}
		if response.Decision == nil || response.Decision.Decision != tc.want {
			t.Fatalf("%+v", response)
		}
	}
	b, err := s.Prepare(ctx)
	if err != nil || b == nil || !strings.Contains(string(b.Payload), `"decision":"deny"`) {
		t.Fatal("decision not persisted", err)
	}
}
