package upload

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/enforcement"
)

func runtimeDrainStore(t *testing.T, count int) (*enforcement.Store, string) {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(root, "runtime")
	s, err := enforcement.OpenStore(dir, 1000)
	if err != nil {
		t.Fatal(err)
	}
	for n := 1; n <= count; n++ {
		r, e := enforcement.ParseRecord([]byte(`{"schema_version":1,"boot_id":"11111111-1111-1111-1111-111111111111","monitor_id":"22222222-2222-2222-2222-222222222222","sequence":"` + strconv.Itoa(n) + `","time_ns":"1800000000000000000","kind":"health","process":{"pid":"123","pidversion":"42","start_us":"9007199254740993"},"relation":"unknown","reason_code":"aidr_enforcement_collection_only"}`))
		if e != nil {
			t.Fatal(e)
		}
		if e = s.Append(context.Background(), r); e != nil {
			t.Fatal(e)
		}
	}
	return s, dir
}

func runtimeDrainACK(t *testing.T, w http.ResponseWriter, req *http.Request, raw []byte) {
	t.Helper()
	if req.Method != "POST" || req.URL.Path != "/api/v1/clients/device-one/aidr/enforcement/records" {
		t.Error("drain requested something other than event upload")
	}
	var batch struct {
		Records []json.RawMessage `json:"records"`
	}
	if err := json.Unmarshal(raw, &batch); err != nil {
		t.Error(err)
	}
	sum := sha256.Sum256(raw)
	json.NewEncoder(w).Encode(map[string]any{"schema_version": 1, "client_id": "device-one", "durable": true, "accepted": len(batch.Records), "digest": hex.EncodeToString(sum[:])})
}

func TestRuntimeDrainBatchBudgetAndRestart(t *testing.T) {
	s, dir := runtimeDrainStore(t, 300)
	var mu sync.Mutex
	var bodies [][]byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		raw, _ := io.ReadAll(req.Body)
		mu.Lock()
		bodies = append(bodies, raw)
		mu.Unlock()
		runtimeDrainACK(t, w, req, raw)
	}))
	defer server.Close()
	c := newClient(t, server.URL)
	report, err := c.DrainRuntime(context.Background(), s, 1)
	if err != nil || report.Drained || !report.BudgetExhausted || report.Pending == nil || *report.Pending != 172 || report.Batches != 1 {
		t.Fatal(report, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = enforcement.OpenStore(dir, 1000)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	report, err = c.DrainRuntime(context.Background(), s, 8)
	if err != nil || !report.Drained || report.Pending == nil || *report.Pending != 0 || report.Batches != 2 || report.Attempts != 2 {
		t.Fatal(report, err)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(bodies) != 3 {
		t.Fatal("unexpected request count", len(bodies))
	}
	seen := map[string]bool{}
	for _, body := range bodies {
		var batch struct {
			Records []struct {
				Sequence string `json:"sequence"`
			} `json:"records"`
		}
		if err = json.Unmarshal(body, &batch); err != nil {
			t.Fatal(err)
		}
		for _, r := range batch.Records {
			if seen[r.Sequence] {
				t.Fatal("logical record uploaded twice", r.Sequence)
			}
			seen[r.Sequence] = true
		}
	}
	if len(seen) != 300 {
		t.Fatal("missing records", len(seen))
	}
}

func TestRuntimeDrainOfflineFrozenRecovery(t *testing.T) {
	for _, failure := range []string{"offline", "pause", "invalid_ack", "auth"} {
		t.Run(failure, func(t *testing.T) {
			s, dir := runtimeDrainStore(t, 1)
			frozen, err := s.Prepare(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			var mu sync.Mutex
			var bodies [][]byte
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				raw, _ := io.ReadAll(req.Body)
				mu.Lock()
				bodies = append(bodies, raw)
				n := len(bodies)
				mu.Unlock()
				if n == 1 {
					switch failure {
					case "offline":
						w.WriteHeader(503)
					case "pause":
						w.WriteHeader(403)
						io.WriteString(w, `{"error_code":"aidr.reporting_disabled"}`)
					case "invalid_ack":
						io.WriteString(w, `{"schema_version":1,"client_id":"device-two","durable":true,"accepted":1,"digest":"wrong"}`)
					case "auth":
						w.WriteHeader(401)
					}
					return
				}
				runtimeDrainACK(t, w, req, raw)
			}))
			defer server.Close()
			c := newClient(t, server.URL)
			report, err := c.DrainRuntime(context.Background(), s, 1)
			if err != nil || report.Drained || report.Code == "" || report.Pending == nil || *report.Pending != 1 || report.Attempts != 1 {
				t.Fatal(report, err)
			}
			if report.BudgetExhausted != (failure != "auth") {
				t.Fatal("authentication failure retried as a transient outage")
			}
			status, statusErr := s.Guard.Status(context.Background())
			wantCode := report.Code
			if failure == "invalid_ack" {
				wantCode = "aidr_upload_ack_invalid"
			}
			if statusErr != nil || status.UploadCode != wantCode {
				t.Fatal("upload diagnosis not persisted", status.UploadCode, statusErr)
			}
			s.Close()
			s, err = enforcement.OpenStore(dir, 1000)
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			restored, err := s.Prepare(context.Background())
			if err != nil || restored.Digest != frozen.Digest || string(restored.Payload) != string(frozen.Payload) {
				t.Fatal("frozen bytes changed", err)
			}
			report, err = c.DrainRuntime(context.Background(), s, 8)
			if err != nil || !report.Drained || report.Batches != 1 {
				t.Fatal(report, err)
			}
			mu.Lock()
			defer mu.Unlock()
			if len(bodies) != 2 || string(bodies[0]) != string(bodies[1]) {
				t.Fatal("retry changed body")
			}
		})
	}
}

func TestRuntimeDrainRetryWithinBudget(t *testing.T) {
	s, _ := runtimeDrainStore(t, 1)
	defer s.Close()
	var mu sync.Mutex
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		raw, _ := io.ReadAll(req.Body)
		mu.Lock()
		requests++
		n := requests
		mu.Unlock()
		if n == 1 {
			w.WriteHeader(503)
			return
		}
		runtimeDrainACK(t, w, req, raw)
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	report, err := newClient(t, server.URL).DrainRuntime(ctx, s, 8)
	if err != nil || !report.Drained || report.Attempts != 2 || report.Batches != 1 || report.Code != "" {
		t.Fatal(report, err)
	}
}

func TestRuntimeDrainCancelledWaitDoesNotClearQueue(t *testing.T) {
	s, _ := runtimeDrainStore(t, 1)
	defer s.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) { w.WriteHeader(503) }))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	start := time.Now()
	report, err := newClient(t, server.URL).DrainRuntime(ctx, s, 8)
	if err != nil || report.Drained || !report.BudgetExhausted || report.Pending != nil || report.Attempts != 1 || time.Since(start) > time.Second {
		t.Fatal(report, err)
	}
	if count, e := s.Pending(context.Background()); e != nil || count != 1 {
		t.Fatal("cancellation removed data", count, e)
	}
}

func TestRuntimeDrainDestinationRejectedBeforeUpload(t *testing.T) {
	s, _ := runtimeDrainStore(t, 1)
	defer s.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) { t.Error("cross-device request sent") }))
	defer server.Close()
	if err := s.Guard.BindDestination(context.Background(), server.URL+"\ndevice-two"); err != nil {
		t.Fatal(err)
	}
	report, err := newClient(t, server.URL).DrainRuntime(context.Background(), s, 8)
	if err == nil || report.Drained {
		t.Fatal("wrong binding accepted", report)
	}
	if count, e := s.Pending(context.Background()); e != nil || count != 1 {
		t.Fatal(count, e)
	}
}

func TestRuntimeDrainEmptyAndCancelled(t *testing.T) {
	s, _ := runtimeDrainStore(t, 0)
	defer s.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		t.Error("empty or cancelled drain sent a request")
	}))
	defer server.Close()
	c := newClient(t, server.URL)
	report, err := c.DrainRuntime(context.Background(), s, 8)
	if err != nil || !report.Drained || report.Attempts != 0 || report.Pending == nil || *report.Pending != 0 {
		t.Fatal(report, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	report, err = c.DrainRuntime(ctx, s, 8)
	if err != nil || report.Drained || report.Attempts != 0 || report.Pending != nil || !report.BudgetExhausted {
		t.Fatal("cancelled drain presented a fresh state", report, err)
	}
	for _, bound := range []int{0, 1025} {
		if _, err = c.DrainRuntime(context.Background(), s, bound); err == nil {
			t.Fatal("unbounded drain accepted", bound)
		}
	}
}
