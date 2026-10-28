package localstore

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestCodeBuddyRestartAndAcknowledgement(t *testing.T) {
	root := tempDir(t)
	if err := os.CopyFS(root, os.DirFS("../agentlog/testdata/codebuddy-4.12.2")); err != nil {
		t.Fatal(err)
	}
	sources := agentlog.Discover(context.Background(), "codebuddy", root, 10, 100, time.Second).Sources
	if len(sources) != 1 {
		t.Fatal("missing recorded session", sources)
	}
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	policy := &agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), MessageSchema: 1, ModelContextSchema: 1, Capture: &agentlog.CaptureScope{}}
	s.policy = policy
	b, err := agentlog.ReadWithPolicy(testContext, sources[0], agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0), policy)
	if err != nil {
		t.Fatal(err)
	}
	if err = agentlog.ValidateCursor(b.Cursor, b.Source); err != nil {
		t.Fatal("cursor", err)
	}
	for _, e := range b.Events {
		if err = agentlog.ValidateEvent(e); err != nil {
			t.Fatalf("event %s %s: %v %+v", e.Kind, e.Tool, err, e)
		}
	}
	collect(t, s, sources[0])
	first := status(t, s)
	if first.LogicalEvents < 8 {
		t.Fatal("native events missing", first)
	}
	collect(t, s, sources[0])
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	s.policy = policy
	defer s.Close()
	collect(t, s, sources[0])
	if next := status(t, s); next.LogicalEvents != first.LogicalEvents || next.Evidence != first.Evidence {
		t.Fatal("restart duplicated events", first, next)
	}
	for {
		batch, err := s.Prepare(testContext, 500, 1<<20)
		if err != nil {
			t.Fatal(err)
		}
		if batch == nil {
			break
		}
		if strings.Contains(string(batch.Payload), "codebuddy_workspace") {
			t.Fatal("local cursor field leaked to wire")
		}
		if err = s.Acknowledge(testContext, batch.ID, batch.Digest); err != nil {
			t.Fatal(err)
		}
	}
	collect(t, s, sources[0])
	if next := status(t, s); next.LogicalEvents != first.LogicalEvents || next.RetainedPayloads != 0 {
		t.Fatal("acknowledged content restored", next)
	}
}

func TestCodeBuddyLocalLogs(t *testing.T) {
	root, output := os.Getenv("CODEBUDDY_TEST_LOG_ROOT"), os.Getenv("CODEBUDDY_TEST_OUTPUT")
	if root == "" || output == "" {
		t.Skip("real IDE log test not requested")
	}
	if !filepath.IsAbs(root) || !filepath.IsAbs(output) {
		t.Fatal("absolute test paths required")
	}
	sources := agentlog.Discover(testContext, "codebuddy", root, 20, 1000, time.Second).Sources
	if len(sources) == 0 {
		t.Fatal("native sessions missing")
	}
	s := openStore(t, tempDir(t), DefaultLimits())
	s.policy = &agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), MessageSchema: 1, ModelContextSchema: 1, Capture: &agentlog.CaptureScope{Prompt: true, ToolOutput: true, FileBody: true, ModelResponse: true}}
	for _, source := range sources {
		collect(t, s, source)
	}
	batch, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil || batch == nil {
		t.Fatal("missing native batch", err)
	}
	if err = os.WriteFile(filepath.Join(output, "log-batch.json"), batch.Payload, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestCodeBuddyMalformedIndexPersistsCoverage(t *testing.T) {
	root := tempDir(t)
	path := filepath.Join(root, "CodeBuddyIDE/test/history/workspace/session/index.json")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"messages":`), 0600); err != nil {
		t.Fatal(err)
	}
	source, err := agentlog.NewSource("codebuddy", root, path)
	if err != nil {
		t.Fatal(err)
	}
	s := openStore(t, tempDir(t), DefaultLimits())
	c := collect(t, s, source)
	if c.Coverage.Status != "unavailable" {
		t.Fatal(c.Coverage)
	}
}
