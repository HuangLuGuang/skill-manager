package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestDesktopMenusSyncAndHeartbeatDoNotRequestScan(t *testing.T) {
	for _, viaHeartbeat := range []bool{false, true} {
		t.Run(map[bool]string{false: "task", true: "heartbeat"}[viaHeartbeat], func(t *testing.T) {
			home, store, inventory, _ := observedFixture(t)
			before := Policy{Mode: "audit", Classification: &ClassificationPolicy{
				Enabled: true, Version: "1:0", ScanVersion: "1:0", RuntimeGovernanceVersion: "1",
				DesktopMenuVisibility: map[string]bool{"discover": true, "models": true, "records": true, "runtime-governance": true},
			}}
			body, _ := json.Marshal(before)
			if err := store.SetState("policy", string(body)); err != nil {
				t.Fatal(err)
			}
			after := before
			classification := *before.Classification
			after.Classification = &classification
			after.Classification.Version = "2:0"
			after.Classification.DesktopMenuVisibility = map[string]bool{"discover": true, "models": false, "records": true, "runtime-governance": true}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if viaHeartbeat {
					var receipt map[string]any
					_ = json.NewDecoder(r.Body).Decode(&receipt)
					if receipt["desktop_menu_protocol"] != float64(1) || receipt["applied_desktop_menu_visibility"].(map[string]any)["models"] != true {
						t.Error("missing cached menu receipt", receipt)
					}
					_ = json.NewEncoder(w).Encode(map[string]any{"policy": after})
				} else {
					_ = json.NewEncoder(w).Encode(after)
				}
			}))
			defer server.Close()
			api := NewAPI(server.URL, "test", time.Second)
			task := Task{ID: 1, TaskType: "sync_policy", Payload: map[string]any{"target_version": "2:0", "reason": "desktop_menu_visibility_changed"}}
			var err error
			if viaHeartbeat {
				err = heartbeatOnce(context.Background(), home, api, store)
			} else {
				err = executeTask(context.Background(), home, inventory, before, api, store, task)
			}
			if err != nil {
				t.Fatal(err)
			}
			if cachedPolicy(store).Classification.DesktopMenuVisibility["models"] {
				t.Fatal("hidden menu was not cached")
			}
			if _, err := os.Stat(filepath.Join(home, ".agent-manager", "run-now")); !os.IsNotExist(err) {
				t.Fatalf("menu change requested scan: %v", err)
			}
			if _, event, err := store.LatestUIEvent(); err != nil || event != "desktop_menu_visibility_changed" {
				t.Fatalf("missing desktop event: %s %v", event, err)
			}
			if !viaHeartbeat && task.Payload["applied_desktop_menu_visibility"].(map[string]bool)["models"] {
				t.Fatal("incorrect task receipt")
			}
			unchanged := after
			unchangedClassification := *after.Classification
			unchanged.Classification = &unchangedClassification
			unchanged.Classification.Version = "3:0"
			if !onlyDesktopMenusChanged(after, unchanged) {
				t.Fatal("global menu revision scheduled scanning for an overridden client")
			}
			after.Classification.Rules = map[string]string{"malicious": "quarantine"}
			if onlyDesktopMenusChanged(before, after) || sameScanningPolicy(before, after) {
				t.Fatal("rule change incorrectly treated as menu-only")
			}
			if err := store.ResetForConnectionChange(); err != nil {
				t.Fatal(err)
			}
			if desktopMenuReceipt(context.Background(), home) != nil {
				t.Fatal("previous platform menus survived connection reset")
			}
		})
	}
}
