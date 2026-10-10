package upload

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"skill-manager/scanner/internal/aidr/localstore"
	"strings"
	"sync/atomic"
	"testing"
)

func TestPolicyRefreshOfflineRestartAndInvalidResponse(t *testing.T) {
	s, dir := populated(t)
	ctx := context.Background()
	if err := s.LoadPolicy(ctx); err != nil {
		t.Fatal(err)
	}
	var mode atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if mode.Load() == 0 {
			w.WriteHeader(503)
			return
		}
		if mode.Load() == 2 {
			w.Write([]byte(`{"version":"0","enabled":false,"receipt":""}`))
			return
		}
		var body map[string]string
		if json.NewDecoder(r.Body).Decode(&body) != nil || body["last_sequence"] == "" || body["stream_id"] == "" {
			t.Error("missing checkpoint")
		}
		json.NewEncoder(w).Encode(map[string]any{"version": "2", "enabled": false, "receipt": strings.Repeat("b", 32)})
	}))
	defer server.Close()
	c := newClient(t, server.URL)
	if err := c.Bind(ctx, s); err != nil {
		t.Fatal(err)
	}
	if err := c.RefreshPolicy(ctx, s); err != nil || !s.Policy().Enabled {
		t.Fatal("first failure must stay ON", err)
	}
	mode.Store(1)
	if err := c.RefreshPolicy(ctx, s); err != nil || s.Policy().Enabled {
		t.Fatal("OFF not applied", err)
	}
	before, _ := s.PolicyAppliedAfter(ctx)
	if err := c.RefreshPolicy(ctx, s); err != nil {
		t.Fatal(err)
	}
	after, _ := s.PolicyAppliedAfter(ctx)
	if before != after {
		t.Fatal("same receipt moved application boundary")
	}
	mode.Store(2)
	if err := c.RefreshPolicy(ctx, s); err != nil || s.Policy().Enabled || c.policyCode != "aidr_policy_response_invalid" {
		t.Fatal("invalid response changed cache")
	}
	s.Close()
	s, err := localstore.Open(dir, localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if err = s.LoadPolicy(ctx); err != nil || s.Policy().Enabled {
		t.Fatal("restart lost policy")
	}
	mode.Store(0)
	if err = c.RefreshPolicy(ctx, s); err != nil || s.Policy().Enabled || c.policyCode != "aidr_policy_cached" {
		t.Fatal("offline lost cache")
	}
}
