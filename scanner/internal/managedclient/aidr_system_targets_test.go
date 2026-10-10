package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestReconcileSystemTargets(t *testing.T) {
	prior := AIDRTaskHandler
	defer func() { AIDRTaskHandler = prior }()
	for _, tc := range []struct {
		name   string
		change string
		want   string
	}{
		{"client_selection", "", ""},
		{"platform_selection", "platform", ""},
		{"empty_selection", "empty", ""},
		{"legacy_null", "null", ""},
		{"legacy_absent", "absent", ""},
		{"different_products", "products", "aidr_desktop_policy_content_mismatch"},
		{"different_selection_mode", "mode", "aidr_desktop_policy_content_mismatch"},
		{"newer_version", "version", "aidr_desktop_task_superseded"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// Serve the wire payload, so API decoding cannot hide a missing Go field.
			var target map[string]any
			if err := json.Unmarshal([]byte(`{"enabled":true,"hosts":["codex","claude","workbuddy","qoder-hooks"],"allow_user_enrollment":true,"channels":{"hooks":true,"logs":true,"system":true},"log_sources":["claude","codex","workbuddy","qoder-cli"],"modes":{"hooks":"intercept","system":null},"system_targets":{"selection_mode":"client","products":["codex","claude","workbuddy"]},"installation":"manual","access_mode":"ordinary","updates":"manual","retry":{"mode":"fixed","retries":2,"max_interval_seconds":300}}`), &target); err != nil {
				t.Fatal(err)
			}
			switch tc.change {
			case "platform":
				target["system_targets"].(map[string]any)["selection_mode"] = "platform"
			case "empty":
				target["system_targets"].(map[string]any)["products"] = []string{}
			case "null":
				target["system_targets"] = nil
			case "absent":
				delete(target, "system_targets")
			}
			wire, _ := json.Marshal(target)
			var fresh map[string]any
			_ = json.Unmarshal(wire, &fresh)
			version := "10:41"
			switch tc.change {
			case "products":
				fresh["system_targets"].(map[string]any)["products"] = []string{"codex"}
			case "mode":
				fresh["system_targets"].(map[string]any)["selection_mode"] = "platform"
			case "version":
				version = "10:42"
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = json.NewEncoder(w).Encode(map[string]any{"classification": map[string]any{"runtime_governance_configured": true, "runtime_governance_version": version, "runtime_governance": fresh}})
			}))
			defer server.Close()
			called := false
			AIDRTaskHandler = func(_ context.Context, _ string, task Task) (map[string]any, error) {
				called = true
				b, _ := json.Marshal(task.Payload["target"])
				var p RuntimeGovernancePolicy
				if err := json.Unmarshal(b, &p); err != nil || !p.Valid() {
					t.Fatalf("invalid decoded target: %v", err)
				}
				if tc.change != "null" && tc.change != "absent" && p.SystemTargets == nil {
					t.Fatal("system targets lost")
				}
				return nil, nil
			}
			err := executeTask(context.Background(), t.TempDir(), Inventory{ClientID: "fixture"}, Policy{}, API{server: server.URL, http: server.Client()}, nil, Task{ID: 185, TaskType: "aidr_plugin_action", Payload: map[string]any{"action": "reconcile", "policy_version": "10:41", "target": target}})
			if tc.want == "" {
				if err != nil || !called {
					t.Fatalf("equivalent target rejected: %v", err)
				}
			} else if err == nil || err.Error() != tc.want || called {
				t.Fatalf("want %s without application, got %v called=%v", tc.want, err, called)
			}
		})
	}
}

func TestSystemTargetsValidation(t *testing.T) {
	p := RuntimeGovernancePolicy{Installation: "manual", AccessMode: "ordinary", Updates: "manual", Retry: ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 60}}
	for _, tc := range []struct {
		targets *SystemCollectionTargets
		valid   bool
	}{
		{nil, true},
		{&SystemCollectionTargets{SelectionMode: "client", Products: []string{}}, true},
		{&SystemCollectionTargets{SelectionMode: "platform", Products: []string{"codex", "claude", "workbuddy", "custom"}}, true},
		{&SystemCollectionTargets{SelectionMode: "unknown"}, false},
		{&SystemCollectionTargets{SelectionMode: "client", Products: []string{"codex", "codex"}}, false},
		{&SystemCollectionTargets{SelectionMode: "client", Products: []string{"unknown"}}, false},
	} {
		p.SystemTargets = tc.targets
		if p.Valid() != tc.valid {
			t.Fatalf("targets=%+v want valid=%v", tc.targets, tc.valid)
		}
	}
}
