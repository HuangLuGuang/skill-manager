package upload

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/aidr/localstore"
)

func TestReportingPauseIsDistinctFromCredentialRejection(t *testing.T) {
	for _, test := range []struct {
		status     int
		body, code string
		retry      bool
	}{
		{403, `{"error_code":"aidr.reporting_disabled"}`, "aidr_upload_reporting_paused", true},
		{403, `{"error_code":"credential.scope_missing"}`, "aidr_upload_auth_rejected", false},
		{403, `{"detail":"aidr.reporting_disabled"}`, "aidr_upload_access_rejected", false},
		{401, `{"error_code":"aidr.reporting_disabled"}`, "aidr_upload_access_rejected", false},
		{403, `not JSON`, "aidr_upload_access_rejected", false},
	} {
		t.Run(test.code+test.body, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(test.status); io.WriteString(w, test.body) }))
			defer server.Close()
			_, result := newClient(t, server.URL).post(context.Background(), "events:batch", []byte(`{}`), nil)
			if result.Code != test.code || result.Retryable != test.retry {
				t.Fatal(result)
			}
		})
	}
}

func TestHookReportingPauseRetainsFrozenBatchAndContinuesCollection(t *testing.T) {
	for _, code := range []string{"aidr.reporting_disabled", "license.missing"} {
		t.Run(code, func(t *testing.T) { testHookReportingPauseRetainsFrozenBatchAndContinuesCollection(t, code) })
	}
}

func testHookReportingPauseRetainsFrozenBatchAndContinuesCollection(t *testing.T, serverCode string) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	var attempts atomic.Int32
	var first []byte
	var times []time.Time
	var accepted []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		if r.URL.Path == "/api/v1/clients/device/aidr/audit-policy" {
			w.WriteHeader(503)
			return
		}
		if r.URL.Path == "/api/v1/clients/device/aidr/hook-runtime" {
			var report map[string]any
			json.Unmarshal(raw, &report)
			json.NewEncoder(w).Encode(map[string]any{"code": "aidr_hook_runtime_received", "receiver_instance": report["receiver_instance"], "report_sequence": report["report_sequence"]})
			return
		}
		if r.URL.Path != "/api/v1/clients/device/aidr/hooks:batch" {
			t.Error("unexpected request")
			w.WriteHeader(404)
			return
		}
		n := attempts.Add(1)
		times = append(times, time.Now())
		if n == 1 {
			first = bytes.Clone(raw)
		}
		if n <= 4 && !bytes.Equal(first, raw) {
			t.Error("frozen batch changed across pause or new intake")
		}
		if n <= 3 {
			w.WriteHeader(403)
			json.NewEncoder(w).Encode(map[string]string{"error_code": serverCode})
			return
		}
		var batch struct {
			Stream  string         `json:"stream_id"`
			Records []hooks.Record `json:"records"`
		}
		json.Unmarshal(raw, &batch)
		for _, record := range batch.Records {
			accepted = append(accepted, record.EventID)
		}
		digest := sha256.Sum256(raw)
		json.NewEncoder(w).Encode(map[string]any{"schema_version": 1, "client_id": "device", "stream_id": batch.Stream, "digest": hex.EncodeToString(digest[:]), "accepted": len(batch.Records), "durable": true})
	}))
	defer server.Close()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := hooks.OpenStore(filepath.Join(root, "state"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	c, err := New(Options{Server: server.URL, ClientID: "device", Token: "synthetic-credential"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	ids := []string{}
	intake := func() {
		id, e := hooks.NewEventID()
		if e != nil {
			t.Fatal(e)
		}
		if _, e = s.Receive(ctx, id, "501", "codex", "SessionStart", []byte(`{"hook_event_name":"SessionStart","session_id":"isolated"}`)); e != nil {
			t.Fatal(e)
		}
		ids = append(ids, id)
	}
	intake()
	observedPause := false
	err = c.RunHooks(ctx, s, func(policy, upload, control string) {
		if upload == accessFailure(403, serverCode).Code {
			observedPause = true
			if len(ids) == 1 {
				intake()
			}
		}
		state, e := s.Status(ctx)
		if e != nil {
			t.Error(e)
			cancel()
			return
		}
		if attempts.Load() >= 4 && state.Queued == 0 {
			cancel()
		}
	})
	if err != nil || !observedPause || len(accepted) != 2 || len(ids) != 2 || accepted[0] != ids[0] || accepted[1] != ids[1] {
		t.Fatal(err, observedPause, accepted, ids)
	}
	if len(times) != 5 || times[3].Sub(times[2]) < 3500*time.Millisecond {
		t.Fatal("failure backoff was not enforced", times)
	}
	// Shutdown releases the queue lock; pending bytes and receipt identity survive reopen.
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := hooks.OpenStore(filepath.Join(root, "state"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	state, err := reopened.Status(context.Background())
	if err != nil || state.Queued != 0 || state.LastSequence != "2" || state.LastAcknowledgedAt == "" {
		t.Fatal(state, err)
	}
}

func TestLogReportingPausePreservesBatchWhileReadingAppend(t *testing.T) {
	for _, code := range []string{"aidr.reporting_disabled", "license.missing"} {
		t.Run(code, func(t *testing.T) { testLogReportingPausePreservesBatchWhileReadingAppend(t, code) })
	}
}

func testLogReportingPausePreservesBatchWhileReadingAppend(t *testing.T, serverCode string) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "session.jsonl")
	line := []byte(`{"type":"assistant","timestamp":"2026-09-23T10:00:00Z","sessionId":"isolated","version":"2.1.220","message":{"content":[{"type":"tool_use","id":"first","name":"Bash","input":{"command":"/bin/sleep 0"}}]}}` + "\n")
	if err = os.WriteFile(path, line, 0600); err != nil {
		t.Fatal(err)
	}
	var attempts atomic.Int32
	var first []byte
	var accepted atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		switch r.URL.Path {
		case "/api/v1/clients/device-one/aidr/audit-policy":
			w.WriteHeader(404) // Legacy server: the conservative cached policy remains active.
		case "/api/v1/clients/device-one/aidr/heartbeat":
			var body map[string]any
			json.Unmarshal(raw, &body)
			json.NewEncoder(w).Encode(map[string]any{"schema_version": 2, "client_id": "device-one", "stream_id": body["stream_id"], "server_received_at": "2026-09-23T00:00:00Z"})
		case "/api/v1/clients/device-one/aidr/events:batch":
			n := attempts.Add(1)
			if n == 1 {
				first = bytes.Clone(raw)
			}
			if n <= 4 && !bytes.Equal(raw, first) {
				t.Error("source append changed the frozen log batch")
			}
			if n <= 3 {
				w.WriteHeader(403)
				json.NewEncoder(w).Encode(map[string]string{"error_code": serverCode})
				return
			}
			ack := receipt(r, raw)
			accepted.Add(int32(ack["accepted"].(int)))
			json.NewEncoder(w).Encode(ack)
		default:
			t.Error("unexpected route")
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	store, err := localstore.Open(filepath.Join(root, "state"), localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	c := newClient(t, server.URL)
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	appended, collectedDuringPause := false, false
	err = Run(ctx, store, c, WorkerOptions{Roots: []Root{{Agent: "claude", Path: root, File: path}}, Since: time.Unix(0, 0), Interval: time.Second, HeartbeatInterval: time.Second, DiscoveryInterval: time.Minute, Observer: func(state localstore.Status) {
		if state.UploadCode == accessFailure(403, serverCode).Code && !appended {
			file, e := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0600)
			if e != nil {
				t.Error(e)
				cancel()
				return
			}
			_, e = file.Write(bytes.ReplaceAll(line, []byte(`"first"`), []byte(`"second"`)))
			file.Close()
			if e != nil {
				t.Error(e)
				cancel()
				return
			}
			appended = true
		}
		if attempts.Load() <= 3 && state.LogicalEvents == 2 && state.Queued > 0 {
			collectedDuringPause = true
		}
		if state.LogicalEvents == 2 && state.Queued == 0 {
			cancel()
		}
	}})
	if err != context.Canceled || !appended || !collectedDuringPause || accepted.Load() < 2 {
		t.Fatal(err, appended, collectedDuringPause, accepted.Load())
	}
	state, err := store.Status(context.Background())
	if err != nil || state.LogicalEvents != 2 || state.EvictedPayloads != 2 || state.Queued != 0 {
		t.Fatal("confirmed identities lost or payloads not released", state, err)
	}
}

func TestHookInvalidCredentialStopsUploadWithoutAcknowledging(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(403)
		io.WriteString(w, `{"error_code":"credential.scope_missing"}`)
	}))
	defer server.Close()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := hooks.OpenStore(filepath.Join(root, "state"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	id, _ := hooks.NewEventID()
	_, err = s.Receive(context.Background(), id, "501", "codex", "SessionStart", []byte(`{"hook_event_name":"SessionStart","session_id":"isolated"}`))
	if err != nil {
		t.Fatal(err)
	}
	c, err := New(Options{Server: server.URL, ClientID: "device", Token: "synthetic-credential"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	err = c.RunHooks(ctx, s, nil)
	if err == nil || err.Error() != "aidr_upload_auth_rejected" {
		t.Fatal(err)
	}
	state, _ := s.Status(context.Background())
	frozen, e := s.Prepare(context.Background())
	if e != nil || state.Queued != 1 || frozen == nil || state.LastAcknowledgedAt != "" {
		t.Fatal("credential failure discarded pending data", state, e)
	}
}
