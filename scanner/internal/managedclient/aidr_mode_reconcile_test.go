package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestReconcileLegacyNullModeAndChangedMode(t *testing.T) {
	prior := AIDRTaskHandler
	defer func() { AIDRTaskHandler = prior }()
	for _, explicit := range []bool{false, true} {
		t.Run(map[bool]string{false: "restore_legacy", true: "different_mode"}[explicit], func(t *testing.T) {
			policy := RuntimeGovernancePolicy{Enabled: true, Installation: "manual", AccessMode: "ordinary", Updates: "manual", Hosts: []string{}, Retry: ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 60}}
			raw, _ := json.Marshal(policy)
			var target map[string]any
			_ = json.Unmarshal(raw, &target)
			target["modes"] = nil
			target["channels"] = nil
			target["log_sources"] = nil
			if explicit {
				target["modes"] = map[string]string{"hooks": "intercept", "system": "audit"}
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = json.NewEncoder(w).Encode(map[string]any{"classification": map[string]any{"runtime_governance_configured": true, "runtime_governance_version": "8:11", "runtime_governance": policy}})
			}))
			defer server.Close()
			called := false
			AIDRTaskHandler = func(context.Context, string, Task) (map[string]any, error) { called = true; return nil, nil }
			err := executeTask(context.Background(), t.TempDir(), Inventory{ClientID: "fixture"}, Policy{}, API{server: server.URL, http: server.Client()}, nil, Task{ID: 141, TaskType: "aidr_plugin_action", Payload: map[string]any{"action": "reconcile", "policy_version": "8:11", "target": target}})
			if explicit {
				if err == nil || called {
					t.Fatal("different mode was applied", err)
				}
			} else if err != nil || !called {
				t.Fatal("restored legacy policy was rejected", err)
			}
		})
	}
}

func TestReconcilePartialModePolicy(t *testing.T) {
	prior := AIDRTaskHandler
	defer func() { AIDRTaskHandler = prior }()
	for _, tc := range []struct {
		name     string
		modes    map[string]any
		current  RuntimeProtectionModes
		accepted bool
	}{
		{"hook_only", map[string]any{"hooks": "intercept", "system": nil}, RuntimeProtectionModes{Hooks: "intercept"}, true},
		{"system_only", map[string]any{"hooks": nil, "system": "intercept"}, RuntimeProtectionModes{System: "intercept"}, true},
		{"preserve_both", map[string]any{"hooks": nil, "system": nil}, RuntimeProtectionModes{}, true},
		{"changed_hook", map[string]any{"hooks": "audit", "system": nil}, RuntimeProtectionModes{Hooks: "intercept"}, false},
		{"changed_system", map[string]any{"hooks": "intercept", "system": "audit"}, RuntimeProtectionModes{Hooks: "intercept"}, false},
		{"unknown_mode_field", map[string]any{"hooks": "intercept", "system": nil, "other": nil}, RuntimeProtectionModes{Hooks: "intercept"}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			policy := RuntimeGovernancePolicy{Modes: &tc.current, Enabled: true, Installation: "manual", AccessMode: "ordinary", Updates: "manual", Hosts: []string{}, Retry: ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 60}}
			raw, _ := json.Marshal(policy)
			var target map[string]any
			_ = json.Unmarshal(raw, &target)
			target["modes"] = tc.modes
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = json.NewEncoder(w).Encode(map[string]any{"classification": map[string]any{"runtime_governance_configured": true, "runtime_governance_version": "10:32", "runtime_governance": policy}})
			}))
			defer server.Close()
			called := false
			AIDRTaskHandler = func(context.Context, string, Task) (map[string]any, error) { called = true; return nil, nil }
			err := executeTask(context.Background(), t.TempDir(), Inventory{ClientID: "fixture"}, Policy{}, API{server: server.URL, http: server.Client()}, nil, Task{ID: 175, TaskType: "aidr_plugin_action", Payload: map[string]any{"action": "reconcile", "policy_version": "10:32", "target": target}})
			if tc.accepted {
				if err != nil || !called {
					t.Fatalf("equivalent policy rejected: %v", err)
				}
			} else if err == nil || err.Error() != "aidr_desktop_policy_content_mismatch" || called {
				t.Fatalf("different policy accepted: %v, called=%v", err, called)
			}
		})
	}
}
