package upload

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

func populated(t *testing.T) (*localstore.Store, string) {
	t.Helper()
	root, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	data, e := os.ReadFile("../agentlog/testdata/claude-2.1.220.jsonl")
	if e != nil {
		t.Fatal(e)
	}
	path := filepath.Join(root, "source.jsonl")
	if e = os.WriteFile(path, data, 0600); e != nil {
		t.Fatal(e)
	}
	src, e := agentlog.NewSource("claude", root, path)
	if e != nil {
		t.Fatal(e)
	}
	dir := filepath.Join(root, "state")
	s, e := localstore.Open(dir, localstore.DefaultLimits())
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { s.Close() })
	if _, e = s.Collect(context.Background(), src, agentlog.DefaultBudget(), time.Unix(0, 0)); e != nil {
		t.Fatal(e)
	}
	return s, dir
}
func receipt(r *http.Request, raw []byte) map[string]any {
	var b localstore.Envelope
	json.Unmarshal(raw, &b)
	sum := sha256.Sum256(raw)
	return map[string]any{"schema_version": 2, "client_id": "device-one", "stream_id": r.Header.Get("X-AIDR-Stream-ID"), "batch_id": r.Header.Get("Idempotency-Key"), "digest": hex.EncodeToString(sum[:]), "accepted": len(b.Records), "durable": true}
}
func newClient(t *testing.T, server string) *Client {
	t.Helper()
	c, e := New(Options{Server: server, ClientID: "device-one", Token: "synthetic-device-credential"})
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(c.Close)
	return c
}

func TestDurableACKAndDestinationBinding(t *testing.T) {
	s, _ := populated(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer synthetic-device-credential" {
			t.Error("missing credential")
		}
		raw, _ := io.ReadAll(r.Body)
		json.NewEncoder(w).Encode(receipt(r, raw))
	}))
	defer server.Close()
	c := newClient(t, server.URL)
	result, e := c.SendOne(context.Background(), s)
	if e != nil || !result.Uploaded {
		t.Fatal(result, e)
	}
	v, _ := s.Status(context.Background())
	if v.Queued != 0 || v.AcknowledgedSequence == "0" {
		t.Fatal(v)
	}
	if e = s.BindDestination(context.Background(), "another-device"); e == nil {
		t.Fatal("pending state can change destination")
	}
}

func TestRejectedResponsesKeepOutbox(t *testing.T) {
	for _, mode := range []string{"wrong-device", "wrong-version", "wrong-digest", "not-durable", "partial-count", "wrong-stream", "unauthorized", "unavailable", "oversized", "redirect"} {
		t.Run(mode, func(t *testing.T) {
			s, _ := populated(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				raw, _ := io.ReadAll(r.Body)
				ack := receipt(r, raw)
				switch mode {
				case "wrong-device":
					ack["client_id"] = "other"
				case "wrong-version":
					ack["schema_version"] = 1
				case "wrong-digest":
					ack["digest"] = "bad"
				case "not-durable":
					ack["durable"] = false
				case "partial-count":
					ack["accepted"] = 0
				case "wrong-stream":
					ack["stream_id"] = "bad"
				case "unauthorized":
					w.WriteHeader(403)
					return
				case "unavailable":
					w.WriteHeader(503)
					return
				case "oversized":
					w.Write(make([]byte, 65537))
					return
				case "redirect":
					w.Header().Set("Location", "http://127.0.0.1:1/credential-leak")
					w.WriteHeader(302)
					return
				}
				json.NewEncoder(w).Encode(ack)
			}))
			defer server.Close()
			c := newClient(t, server.URL)
			result, e := c.SendOne(context.Background(), s)
			if e != nil || result.Uploaded || result.Code == "" {
				t.Fatal(result, e)
			}
			v, _ := s.Status(context.Background())
			if v.Queued != 17 || v.AcknowledgedSequence != "0" || v.UploadCode == "" {
				t.Fatal(v)
			}
		})
	}
}

func TestLostReceiptRestartAndReplay(t *testing.T) {
	s, dir := populated(t)
	var mu sync.Mutex
	stored := map[string]string{}
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		id := r.Header.Get("Idempotency-Key")
		mu.Lock()
		attempts++
		attempt := attempts
		if old, ok := stored[id]; ok && old != string(raw) {
			t.Error("replay changed bytes")
		}
		stored[id] = string(raw)
		mu.Unlock()
		if attempt == 1 {
			connection, _, _ := w.(http.Hijacker).Hijack()
			connection.Close()
			return
		}
		json.NewEncoder(w).Encode(receipt(r, raw))
	}))
	defer server.Close()
	c := newClient(t, server.URL)
	result, e := c.SendOne(context.Background(), s)
	if e != nil || result.Uploaded || !result.Retryable {
		t.Fatal(result, e)
	}
	before, _ := s.StreamID(context.Background())
	s.Close()
	s, e = localstore.Open(dir, localstore.DefaultLimits())
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	after, _ := s.StreamID(context.Background())
	if before != after {
		t.Fatal("stream identity changed on restart")
	}
	result, e = c.SendOne(context.Background(), s)
	if e != nil || !result.Uploaded {
		t.Fatal(result, e)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(stored) != 1 || attempts != 2 {
		t.Fatal("receiver duplicated batch", len(stored), attempts)
	}
}

func TestTransportAndRetryBounds(t *testing.T) {
	if _, e := New(Options{Server: "http://example.com", ClientID: "device-one", Token: "secret"}); e == nil {
		t.Fatal("cleartext remote credential allowed")
	}
	for n := 0; n < 100; n++ {
		d := RetryDelay(n)
		if d < time.Second || d > time.Minute {
			t.Fatal(d)
		}
	}
}
