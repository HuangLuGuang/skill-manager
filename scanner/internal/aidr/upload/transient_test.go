package upload

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/aidr/localstore"
)

func TestHTTPFailureClassificationAndDiagnostics(t *testing.T) {
	for _, status := range []int{302, 400, 401, 403, 404, 408, 409, 413, 422, 429, 500, 502, 503, 504} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(status)
				io.WriteString(w, `{"error_code":"aidr.invalid_batch","detail":"private event body"}`)
			}))
			defer server.Close()
			c := newClient(t, server.URL)
			var diagnostic HTTPDiagnostic
			c.observeHTTP = func(d HTTPDiagnostic) { diagnostic = d }
			wantRetry := status == 404 || status == 408 || status == 429 || status >= 500
			for _, method := range []string{"POST", "GET"} {
				var result Result
				if method == "POST" {
					_, result = c.post(context.Background(), "hooks:batch", []byte(`{}`), nil)
				} else {
					_, result = c.RuntimeGet(context.Background(), "snapshot")
				}
				if result.Code == "" || result.Retryable != wantRetry || diagnostic.StatusCode != status || diagnostic.ServerCode != "aidr.invalid_batch" || diagnostic.Code != result.Code || diagnostic.Retryable != wantRetry || diagnostic.Method != method {
					t.Fatalf("result=%+v diagnostic=%+v", result, diagnostic)
				}
				if (status == 401 || status == 403) && result.Code != "aidr_upload_access_rejected" {
					t.Fatal("authentication classification changed")
				}
				encoded, _ := json.Marshal(diagnostic)
				if bytes.Contains(encoded, []byte("private event body")) {
					t.Fatal("response content entered diagnostics")
				}
			}
		})
	}
	for _, raw := range []string{`{"error_code":"Bearer secret"}`, `{"detail":"private"}`, `not json`} {
		if responseErrorCode([]byte(raw)) != "" {
			t.Fatal("unstructured response entered diagnostic code")
		}
	}
}

func TestHTTPDiagnosticUnderlyingErrorAndDeadline(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Request-ID") == "" {
			t.Error("request ID missing")
		}
		select {
		case <-r.Context().Done():
		case <-time.After(100 * time.Millisecond):
		}
	}))
	defer server.Close()
	for _, method := range []string{"POST", "GET"} {
		c := newClient(t, server.URL)
		var observed []HTTPDiagnostic
		c.observeHTTP = func(d HTTPDiagnostic) { observed = append(observed, d) }
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
		if method == "POST" {
			c.post(ctx, "hooks:batch", []byte(`{}`), nil)
		} else {
			c.RuntimeGet(ctx, "snapshot")
		}
		cancel()
		if len(observed) != 1 {
			t.Fatalf("missing deadline diagnostic: %+v", observed)
		}
		d := observed[0]
		if !strings.Contains(d.Error, "context deadline exceeded") || d.ContextError != context.DeadlineExceeded.Error() || d.RequestID == "" || !d.HasDeadline || d.DurationMS == 0 {
			t.Fatalf("lost transport cause: %+v", d)
		}
		ctx, cancel = context.WithCancel(context.Background())
		cancel()
		c.RuntimeGet(ctx, "snapshot")
		if len(observed) != 1 {
			t.Fatal("shutdown cancellation logged as failure")
		}
	}
}

func TestHookLoopSurvivesMissingEndpointAndDrainsExactBatches(t *testing.T) {
	t.Parallel()
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	var attempts atomic.Int32
	var frozen []byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "hooks:batch") {
			w.WriteHeader(404)
			return
		}
		raw, _ := io.ReadAll(r.Body)
		n := attempts.Add(1)
		if n == 1 {
			frozen = append([]byte{}, raw...)
		} else if n <= 4 && !bytes.Equal(raw, frozen) {
			t.Error("recovery changed frozen batch")
		}
		if n <= 3 {
			w.WriteHeader(404)
			return
		}
		var batch struct {
			Stream  string         `json:"stream_id"`
			Records []hooks.Record `json:"records"`
		}
		_ = json.Unmarshal(raw, &batch)
		sum := sha256.Sum256(raw)
		_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": 1, "client_id": "device-one", "stream_id": batch.Stream, "digest": hex.EncodeToString(sum[:]), "accepted": len(batch.Records), "durable": true})
	}))
	defer server.Close()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := hooks.OpenStore(filepath.Join(root, "hooks"), server.URL, "device-one", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	receive := func() {
		id, err := hooks.NewEventID()
		if err != nil {
			t.Fatal(err)
		}
		if _, err = s.Receive(ctx, id, "501", "codex", "SessionStart", []byte(`{"hook_event_name":"SessionStart","session_id":"synthetic"}`)); err != nil {
			t.Fatal(err)
		}
	}
	receive()
	added := false
	err = newClient(t, server.URL).RunHooks(ctx, s, func(_, uploadCode, _ string) {
		if uploadCode != "" && !added {
			receive() // Intake still works while the original batch waits for recovery.
			added = true
		}
		state, e := s.Status(ctx)
		if e != nil {
			t.Fatal(e)
		}
		if added && state.Queued == 0 && state.LastAcknowledgedAt != "" {
			cancel()
		}
	})
	if err != nil || !errors.Is(ctx.Err(), context.Canceled) || attempts.Load() != 5 {
		t.Fatalf("loop stopped or failed to drain: %v, %v, attempts=%d", err, ctx.Err(), attempts.Load())
	}
}

func TestLogLoopSurvivesMissingEndpointAndDrainsFrozenBatch(t *testing.T) {
	t.Parallel()
	s, _ := populated(t)
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	var attempts atomic.Int32
	var frozen []byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		if strings.HasSuffix(r.URL.Path, "events:batch") {
			n := attempts.Add(1)
			if frozen == nil {
				frozen = append([]byte{}, raw...)
			} else if !bytes.Equal(frozen, raw) {
				t.Error("frozen bytes changed")
			}
			if n <= 3 {
				w.WriteHeader(404)
				return
			}
			_ = json.NewEncoder(w).Encode(receipt(r, raw))
			return
		}
		// Both the heartbeat and policy endpoint can disappear during restart.
		w.WriteHeader(404)
	}))
	defer server.Close()
	err := Run(ctx, s, newClient(t, server.URL), WorkerOptions{
		Roots: []Root{{Agent: "claude", Path: t.TempDir()}}, Interval: time.Second,
		HeartbeatInterval: time.Second, DiscoveryInterval: time.Minute,
		IntakeEnabled: func() bool { return false }, IntakeVersion: func() string { return "1:1" },
		Observer: func(state localstore.Status) {
			if state.Queued == 0 && state.AcknowledgedSequence != "0" {
				cancel()
			}
		},
	})
	if !errors.Is(err, context.Canceled) || attempts.Load() != 4 {
		t.Fatalf("loop stopped or failed to drain: %v, attempts=%d", err, attempts.Load())
	}
}
