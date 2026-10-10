package upload

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

func TestRuntimeOffStopsReadingAndUploadsExistingFrozenBatch(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../agentlog/testdata/claude-2.1.220.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "source.jsonl")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	s, err := localstore.Open(filepath.Join(root, "state"), localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	src, err := agentlog.NewSource("claude", root, path)
	if err != nil {
		t.Fatal(err)
	}
	checkpoint, err := s.Collect(ctx, src, agentlog.DefaultBudget(), time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	frozen, err := s.Prepare(ctx, 500, 1<<20)
	if err != nil || frozen == nil {
		t.Fatal(err)
	}
	before, err := s.Status(ctx)
	if err != nil {
		t.Fatal(err)
	}
	// A second unread source must not enter the store while runtime is OFF.
	if err := os.WriteFile(filepath.Join(root, "unseen.jsonl"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	var uploaded bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		switch r.URL.Path {
		case "/api/v1/clients/device-one/aidr/audit-policy":
			w.WriteHeader(503)
		case "/api/v1/clients/device-one/aidr/events:batch":
			if !bytes.Equal(body, frozen.Payload) {
				t.Error("runtime OFF changed frozen bytes")
			}
			uploaded = true
			json.NewEncoder(w).Encode(receipt(r, body))
		case "/api/v1/clients/device-one/aidr/heartbeat":
			var v map[string]any
			json.Unmarshal(body, &v)
			json.NewEncoder(w).Encode(map[string]any{"schema_version": 2, "client_id": "device-one", "stream_id": v["stream_id"], "server_received_at": "2026-10-04T00:00:00Z"})
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	err = Run(ctx, s, newClient(t, server.URL), WorkerOptions{Roots: []Root{{Agent: "claude", Path: root}}, Since: time.Unix(0, 0), Interval: time.Second, HeartbeatInterval: time.Second, DiscoveryInterval: time.Second, IntakeEnabled: func() bool { return false }, Observer: func(status localstore.Status) {
		if status.Queued != 0 || status.LogicalEvents != before.LogicalEvents || status.Sources != before.Sources {
			t.Error("OFF either collected or failed to drain")
		}
		cancel()
	}})
	if !errors.Is(err, context.Canceled) || !uploaded {
		t.Fatal(err, "upload absent")
	}
	after, err := s.Checkpoint(context.Background(), src.ID)
	if err != nil || after.Cursor.Offset != checkpoint.Cursor.Offset {
		t.Fatal("OFF changed source cursor", err)
	}
	status, err := s.Status(context.Background())
	if err != nil || status.AcknowledgedSequence == "0" || status.LastAcknowledgedAt == "" {
		t.Fatal("strict ACK did not persist", err)
	}
}
