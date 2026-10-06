package hooks

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
)

func TestPluginReportSequenceSurvivesRestartWithoutAuditMutation(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "state")
	s, err := OpenStore(path, "http://127.0.0.1:1", "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	status := PluginStatus{Agent: "codex", ScopeDigest: strings.Repeat("a", 64)}
	first, err := s.PreparePluginReport(context.Background(), status)
	if err != nil {
		t.Fatal(err)
	}
	if first.Sequence != "1" || first.Status.ScopeDigest == status.ScopeDigest {
		t.Fatal("sequence or scope binding")
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = OpenStore(path, "http://127.0.0.1:1", "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	second, err := s.PreparePluginReport(context.Background(), status)
	if err != nil {
		t.Fatal(err)
	}
	if second.Sequence != "2" || second.Receiver == first.Receiver || second.Stream != first.Stream || second.Status.ScopeDigest != first.Status.ScopeDigest {
		t.Fatal("restart ordering or scope lost")
	}
	state, err := s.Status(context.Background())
	if err != nil || state.LastSequence != "0" || state.Queued != 0 {
		t.Fatal("audit state changed")
	}
}
