package main

import (
	"bytes"
	"context"
	"encoding/json"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func TestStoppedHookProjectionRequiresMatchingOwnerEvidence(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-stopped-token"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{RuntimePolicy: &desktopRuntimePolicy{Version: "1:4"}}
	observed := map[string]any{"version": 1, "client_id": paths.Device, "queue": paths.State, "policy_version": "1:4", "observed_at_ms": strconv.FormatInt(time.Now().UnixMilli(), 10), "enabled": false, "code": "aidr_desktop_disabled"}
	path := filepath.Join(paths.Root, "hook-collection-status.json")
	if err := writeDesktopJSON(path, observed); err != nil {
		t.Fatal(err)
	}
	report := runtimeChannelSnapshot(paths, prefs, map[string]any{"receiver_code": "aidr_desktop_stopped"})
	hook := report["hooks"].(map[string]any)
	if hook["state"] != "disabled" || hook["enabled"] != false || hook["policy_version"] != "1:4" {
		t.Fatal(hook)
	}
	observed["policy_version"] = "1:3"
	if err := writeDesktopJSON(path, observed); err != nil {
		t.Fatal(err)
	}
	if _, exists := runtimeChannelSnapshot(paths, prefs, map[string]any{})["hooks"]; exists {
		t.Fatal("old target treated as current")
	}
	observed["policy_version"], observed["client_id"] = "1:4", "other-device"
	if err := writeDesktopJSON(path, observed); err != nil {
		t.Fatal(err)
	}
	if _, exists := runtimeChannelSnapshot(paths, prefs, map[string]any{})["hooks"]; exists {
		t.Fatal("cross-device stopped proof accepted")
	}
}

func TestChannelTargetStopsHookWithoutClaimingLogOrSystem(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-channel-secret"}); err != nil {
		t.Fatal(err)
	}
	target := logTestPolicy().Classification.RuntimeGovernance
	target.Channels.Hooks = false
	target.Channels.System = true
	task := managedclient.Task{ID: 42, Payload: map[string]any{"action": "reconcile", "plugin_version": hooks.BundledPluginVersion, "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339), "policy_version": "1:2", "target": target}}
	report, err := executeAIDRTask(context.Background(), home, task)
	if err != nil || report["enabled"] != false || report["protocol"] != 5 || report["policy_version"] != "1:2" {
		t.Fatal(report, err)
	}
	channels := report["channels"].(map[string]any)
	if _, ok := channels["logs"]; ok {
		t.Fatal("task receipt invented a log observation")
	}
	if _, ok := channels["system"]; ok {
		t.Fatal("task receipt invented an ES observation")
	}
	for _, invalid := range []string{"", "1:2:3", "1:-1", "1:secret", "18446744073709551616"} {
		if validRuntimePolicyVersion(invalid) {
			t.Fatal("invalid version accepted", invalid)
		}
	}
}

func TestLogChannelProjectionPreservesObservationAndBinding(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-projection-secret"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	statePath := filepath.Join(paths.Root, "log-queues", filepath.Base(paths.State))
	stamp := time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
	status := map[string]any{"version": 1, "client_id": paths.Device, "policy_version": "1:2", "enabled": true, "reported_at": stamp, "code": "aidr_log_running", "state": map[string]any{"queued_records": 3, "last_ack_at": stamp, "intake_code": "aidr_log_version_unverified"}, "token": "synthetic-projection-secret"}
	path := filepath.Join(statePath, "log-status.json")
	if err := writeDesktopJSON(path, status); err != nil {
		t.Fatal(err)
	}
	report := aidrRuntimeSnapshot(home)
	logs := report["channels"].(map[string]any)["logs"].(map[string]any)
	if logs["reported_at"] != stamp || logs["last_ack_at"] != stamp || logs["queued_records"] != 3 {
		t.Fatal("timestamp or counts changed", logs)
	}
	raw, _ := json.Marshal(report)
	if strings.Contains(string(raw), "synthetic-projection-secret") {
		t.Fatal("secret entered heartbeat projection")
	}
	supervisor := logSupervision{Version: 1, Configuration: strings.Repeat("a", 64), PolicyVersion: "1:2", Code: "aidr_log_stopped", UpdatedAt: time.Now().UTC().Format(time.RFC3339Nano)}
	if err := writeDesktopJSON(filepath.Join(statePath, "log-supervisor.json"), supervisor); err != nil {
		t.Fatal(err)
	}
	report = aidrRuntimeSnapshot(home)
	logs = report["channels"].(map[string]any)["logs"].(map[string]any)
	if logs["state"] != "stopped" || logs["reported_at"] != supervisor.UpdatedAt {
		t.Fatal("stopped owner hidden by old running file", logs)
	}
	status["client_id"] = "other-device"
	if err := writeDesktopJSON(path, status); err != nil {
		t.Fatal(err)
	}
	logs = aidrRuntimeSnapshot(home)["channels"].(map[string]any)["logs"].(map[string]any)
	if logs["state"] == "running" {
		t.Fatal("cross-device log report accepted")
	}
}

func TestChannelStatusRejectsChangedManagedBinding(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-channel-token"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{ManagedTask: 1, ManagedServer: "http://127.0.0.1:10", ManagedDevice: paths.Device}
	if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	err = aidrDesktopContext(context.Background(), []string{"--home", home, "--action", "channels-status"}, &out)
	if err == nil || err.Error() != "aidr_desktop_managed_binding_changed" || out.Len() != 0 {
		t.Fatal("old target exposed as current", err, out.Len())
	}
}
