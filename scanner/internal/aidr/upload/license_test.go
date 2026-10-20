package upload

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/localstore"
)

func TestLicenseAndCredentialClassification(t *testing.T) {
	for _, code := range []string{"license.missing", "license.future", "license.feature_denied", "license.invalid", "license.untrusted_key", "license.deployment_mismatch", "license.customer_mismatch", "license.clock_rollback", "license.unavailable", "license.expired", "credential.scope_missing", "credential.invalid_or_disabled", "aidr.device_binding_mismatch", "license.unknown"} {
		t.Run(code, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(403)
				json.NewEncoder(w).Encode(map[string]string{"error_code": code})
			}))
			defer server.Close()
			c := newClient(t, server.URL)
			var diagnostic HTTPDiagnostic
			c.observeHTTP = func(d HTTPDiagnostic) { diagnostic = d }
			_, post := c.post(context.Background(), "audit-policy", []byte(`{}`), nil)
			_, get := c.RuntimeGet(context.Background(), "snapshot")
			wantRetry := code[:8] == "license." && code != "license.unknown"
			if post != get || post.Retryable != wantRetry || diagnostic.ServerCode != code {
				t.Fatalf("post=%+v get=%+v diagnostic=%+v", post, get, diagnostic)
			}
		})
	}
}

func TestEmptyQueueSurvivesLicenseHeartbeatRejection(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := localstore.Open(filepath.Join(root, "state"), localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	heartbeats := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/clients/device-one/aidr/heartbeat" {
			heartbeats++
			if heartbeats == 2 {
				cancel()
			}
		}
		w.WriteHeader(403)
		json.NewEncoder(w).Encode(map[string]string{"error_code": "license.missing"})
	}))
	defer server.Close()
	err = Run(ctx, s, newClient(t, server.URL), WorkerOptions{Roots: []Root{{Agent: "codex", Path: root}}, Interval: time.Second, HeartbeatInterval: time.Second, DiscoveryInterval: time.Minute})
	if !errors.Is(err, context.Canceled) || heartbeats != 2 {
		t.Fatalf("err=%v heartbeats=%d", err, heartbeats)
	}
}
