package upload

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

func TestWorkerCapacityHeartbeatAndCancellation(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../agentlog/testdata/claude-2.1.220.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "calls.jsonl")
	if err = os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	limits := localstore.DefaultLimits()
	limits.LogicalEvents = 1
	store, err := localstore.Open(filepath.Join(root, "state"), limits)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var beats atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		if r.URL.Path == "/api/v1/clients/device-one/aidr/heartbeat" {
			var body map[string]any
			if err := json.Unmarshal(raw, &body); err != nil {
				t.Error(err)
			}
			if body["intake_code"] != "aidr_store_capacity" {
				t.Errorf("capacity not visible: %v", body["intake_code"])
			}
			beats.Add(1)
			json.NewEncoder(w).Encode(map[string]any{"schema_version": 2, "client_id": "device-one", "stream_id": body["stream_id"], "server_received_at": "2026-09-23T00:00:00Z"})
		} else {
			json.NewEncoder(w).Encode(receipt(r, raw))
		}
	}))
	defer server.Close()
	err = Run(ctx, store, newClient(t, server.URL), WorkerOptions{Roots: []Root{{Agent: "claude", Path: root, File: path}}, Since: time.Unix(0, 0), Interval: time.Second, HeartbeatInterval: time.Second, DiscoveryInterval: time.Minute, Observer: func(s localstore.Status) {
		if s.LogicalEvents != 0 {
			t.Errorf("partial capacity commit: %v", s)
		}
		if beats.Load() >= 2 {
			cancel()
		}
	}})
	if !errors.Is(err, context.Canceled) || beats.Load() < 2 {
		t.Fatal(err, beats.Load())
	}
	if err = store.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := localstore.Open(filepath.Join(root, "state"), limits)
	if err != nil {
		t.Fatal("writer not released", err)
	}
	reopened.Close()
}

func TestCapabilitySummaryKeepsDegradation(t *testing.T) {
	actual := summarizeCapabilities(map[string]Capability{"a": {Agent: "claude", Version: "2.1.220", Status: "available"}, "b": {Agent: "claude", Version: "2.1.220", Status: "unavailable"}, "c": {Agent: "codex", Version: "future", Status: "unverified"}})
	if len(actual) != 2 || actual[0].Status != "unavailable" || actual[1].Status != "unverified" {
		t.Fatal(actual)
	}
}

func TestAutomaticDiscoveryBacklogOfflineAndRestart(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../agentlog/testdata/codex-0.155.0-alpha.9.2.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	// Two calls and their two results per source, after session/turn headers.
	raw = append(bytes.Join(bytes.Split(raw, []byte("\n"))[:6], []byte("\n")), '\n')
	for i := 0; i < 200; i++ {
		if err = os.WriteFile(filepath.Join(root, fmt.Sprintf("%03d.jsonl", i)), raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	state := filepath.Join(root, "state")
	var attempts atomic.Int32
	var accepted atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		if r.URL.Path == "/api/v1/clients/device-one/aidr/heartbeat" {
			var body map[string]any
			json.Unmarshal(raw, &body)
			json.NewEncoder(w).Encode(map[string]any{"schema_version": 2, "client_id": "device-one", "stream_id": body["stream_id"], "server_received_at": "2026-09-24T00:00:00Z"})
		} else if attempts.Add(1) <= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
		} else {
			accepted.Add(1)
			json.NewEncoder(w).Encode(receipt(r, raw))
		}
	}))
	defer server.Close()
	var logical int
	for run := 0; run < 2; run++ {
		s, e := localstore.Open(state, localstore.DefaultLimits())
		if e != nil {
			t.Fatal(e)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		err = Run(ctx, s, newClient(t, server.URL), WorkerOptions{Roots: []Root{{Agent: "codex", Path: root}}, Since: time.Unix(0, 0), Interval: time.Second, HeartbeatInterval: time.Second, DiscoveryInterval: time.Minute, Observer: func(v localstore.Status) {
			if run == 0 && attempts.Load() >= 1 {
				cancel()
			}
			if run == 1 && v.Sources == 200 && v.Queued == 0 {
				logical = v.LogicalEvents
				cancel()
			}
		}})
		cancel()
		s.Close()
		if !errors.Is(err, context.Canceled) {
			t.Fatal(run, err)
		}
	}
	if logical != 800 || accepted.Load() == 0 {
		t.Fatal("source/event loss", logical, accepted.Load())
	}
}

func TestParserSupportIndependentOfRetainedGap(t *testing.T) {
	if agentlog.VersionSupport("codex", "0.158.0-alpha.2.1") != "available" {
		t.Fatal("current tested parser missing")
	}
	if agentlog.VersionSupport("codex", "future") != "unverified" {
		t.Fatal("unknown version must remain unverified")
	}
	caps := summarizeCapabilities(map[string]Capability{"old": {Agent: "codex", Version: "0.158.0-alpha.2.1", Status: "unavailable", ParserStatus: "available", ParserVersion: agentlog.ParserVersion}})
	if len(caps) != 1 || caps[0].Status != "unavailable" || caps[0].ParserStatus != "available" {
		t.Fatal("history must not overwrite parser support")
	}
}
