package upload

import (
	"context"
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

// Started by tests/test_aidr_skill_policy.py with an isolated FastAPI database.
func TestSkillPolicyHTTPIntegration(t *testing.T) {
	server := os.Getenv("SKILL_POLICY_TEST_SERVER")
	if server == "" {
		t.Skip("requires isolated Python integration server")
	}
	u, err := url.Parse(server)
	if err != nil || u.Hostname() != "127.0.0.1" {
		t.Fatal("integration server must be loopback")
	}
	root := os.Getenv("SKILL_POLICY_TEST_ROOT")
	if root == "" {
		t.Fatal("missing fixture")
	}
	ctx := context.Background()
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := localstore.Open(filepath.Join(dir, "state"), localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	c, err := New(Options{Server: server, ClientID: "one", Token: "test-one"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if err = c.Bind(ctx, s); err != nil {
		t.Fatal(err)
	}
	if err = s.LoadPolicy(ctx); err != nil {
		t.Fatal(err)
	}
	if err = c.RefreshPolicy(ctx, s); err != nil {
		t.Fatal(err)
	}
	if s.Policy().SkillAudit == nil || s.Policy().SkillAudit.DigestCacheSeconds != 120 {
		t.Fatalf("policy not delivered: %+v", s.Policy())
	}
	path := filepath.Join(dir, "source.jsonl")
	if err = os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	src, err := agentlog.NewSource("claude", dir, path)
	if err != nil {
		t.Fatal(err)
	}
	for _, call := range []string{"first", "reused", "changed"} {
		if call == "changed" {
			if err = os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("changed content"), 0600); err != nil {
				t.Fatal(err)
			}
		}
		line := map[string]any{"type": "assistant", "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "sessionId": "skill-policy-e2e", "version": "2.1.220",
			"message": map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": call, "name": "Read", "input": map[string]any{"file_path": filepath.Join(root, "SKILL.md")}}}}}
		raw, err := json.Marshal(line)
		if err != nil {
			t.Fatal(err)
		}
		f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		_, err = f.Write(append(raw, '\n'))
		f.Close()
		if err != nil {
			t.Fatal(err)
		}
		if _, err = s.Collect(ctx, src, agentlog.DefaultBudget(), time.Unix(0, 0)); err != nil {
			t.Fatal(err)
		}
	}
	page, err := s.Events(ctx, "", 100)
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Events) != 3 {
		t.Fatalf("missing events: %d", len(page.Events))
	}
	seen := map[string]string{}
	for _, raw := range page.Events {
		var event agentlog.Event
		if err = json.Unmarshal(raw, &event); err != nil {
			t.Fatal(err)
		}
		if event.SkillUse == nil {
			t.Fatal("missing Skill evidence")
		}
		seen[event.CallID] = event.SkillUse.ContentStatus
	}
	if seen["first"] != "computed" || seen["reused"] != "reused" || seen["changed"] != "computed" {
		t.Fatalf("%+v", seen)
	}
	for i := 0; i < 10; i++ {
		result, err := c.SendOne(ctx, s)
		if err != nil {
			t.Fatal(err)
		}
		if !result.Uploaded {
			break
		}
	}
	status, err := s.Status(ctx)
	if err != nil || status.Queued != 0 || status.AcknowledgedSequence == "0" {
		t.Fatalf("ACK missing: %+v %v", status, err)
	}
	if _, err = c.Heartbeat(ctx, s, nil, nil); err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = localstore.Open(filepath.Join(dir, "state"), localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if err = s.LoadPolicy(ctx); err != nil || s.Policy().SkillAudit == nil || s.Policy().SkillAudit.DigestCacheSeconds != 120 {
		t.Fatal("restart lost policy", err)
	}
}
