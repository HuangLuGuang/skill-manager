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
	"testing"

	"skill-manager/scanner/internal/aidr/enforcement"
)

func TestRuntimeACKRetryKeepsFrozenBody(t *testing.T) {
	for _, failure := range []string{"device", "digest", "count", "durable", "unauthorized", "offline"} {
		t.Run(failure, func(t *testing.T) {
			ctx := context.Background()
			root, err := filepath.EvalSymlinks(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			s, err := enforcement.OpenStore(filepath.Join(root, "state"), 10)
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			r, err := enforcement.ParseRecord([]byte(`{"schema_version":1,"boot_id":"11111111-1111-1111-1111-111111111111","monitor_id":"22222222-2222-2222-2222-222222222222","sequence":"1","time_ns":"1800000000000000000","kind":"health","process":{"pid":"123","pidversion":"42","start_us":"9007199254740993"},"relation":"unknown","reason_code":"aidr_enforcement_active"}`))
			if err != nil {
				t.Fatal(err)
			}
			if err = s.Append(ctx, r); err != nil {
				t.Fatal(err)
			}
			var bodies [][]byte
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				if req.URL.Path != "/api/v1/clients/device-one/aidr/enforcement/records" || req.Header.Get("Authorization") != "Bearer synthetic-device-credential" {
					t.Error("incorrect device endpoint or credential")
				}
				raw, _ := io.ReadAll(req.Body)
				bodies = append(bodies, raw)
				hash := sha256.Sum256(raw)
				ack := map[string]any{"schema_version": 1, "client_id": "device-one", "durable": true, "accepted": 1, "digest": hex.EncodeToString(hash[:])}
				if len(bodies) == 1 {
					switch failure {
					case "device":
						ack["client_id"] = "device-two"
					case "digest":
						ack["digest"] = "wrong"
					case "count":
						ack["accepted"] = 0
					case "durable":
						ack["durable"] = false
					case "unauthorized":
						w.WriteHeader(403)
						return
					case "offline":
						w.WriteHeader(503)
						return
					}
				}
				json.NewEncoder(w).Encode(ack)
			}))
			defer server.Close()
			c := newClient(t, server.URL)
			result, err := c.SendRuntime(ctx, s)
			if err != nil || result.Uploaded || result.Code == "" {
				t.Fatal(result, err)
			}
			if pending, err := s.Prepare(ctx); err != nil || pending == nil {
				t.Fatal("failed receipt removed frozen batch", err)
			}
			result, err = c.SendRuntime(ctx, s)
			if err != nil || !result.Uploaded {
				t.Fatal(result, err)
			}
			if len(bodies) != 2 || string(bodies[0]) != string(bodies[1]) {
				t.Fatal("retry modified frozen body")
			}
			if pending, err := s.Prepare(ctx); err != nil || pending != nil {
				t.Fatal("durable receipt did not clear batch", err)
			}
		})
	}
}
