package localstore

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestTraeNativeRestartAndAcknowledgement(t *testing.T) {
	data, err := os.ReadFile("../agentlog/testdata/trae-3.6.4/agent-hooks.txt")
	if err != nil {
		t.Fatal(err)
	}
	root := tempDir(t)
	path := filepath.Join(root, "agent-hooks.log")
	if err = os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	sources := agentlog.Discover(testContext, "trae", root, 10, 100, time.Second).Sources
	if len(sources) != 1 {
		t.Fatal(sources)
	}
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	p := &agentlog.AuditPolicy{Version: "2", Enabled: true, Receipt: strings.Repeat("a", 32), MessageSchema: 1, Capture: &agentlog.CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
	s.policy = p
	collect(t, s, sources[0])
	first := status(t, s)
	if first.LogicalEvents != 10 {
		t.Fatal("native events missing", first)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	s.policy = p
	defer s.Close()
	collect(t, s, sources[0])
	if next := status(t, s); next.LogicalEvents != first.LogicalEvents || next.Evidence != first.Evidence {
		t.Fatal("restart duplicated events", next)
	}
	for {
		batch, err := s.Prepare(testContext, 500, 1<<20)
		if err != nil {
			t.Fatal(err)
		}
		if batch == nil {
			break
		}
		if strings.Contains(string(batch.Payload), "trae_hooks") || strings.Contains(string(batch.Payload), "trae_input") {
			t.Fatal("local state leaked")
		}
		if err = s.Acknowledge(testContext, batch.ID, batch.Digest); err != nil {
			t.Fatal(err)
		}
	}
	collect(t, s, sources[0])
	if next := status(t, s); next.LogicalEvents != first.LogicalEvents || next.RetainedPayloads != 0 {
		t.Fatal("ACK did not retire payload", next)
	}
}
