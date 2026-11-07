package main

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func TestAIDRManagedActionsBindingAndSecretProjection(t *testing.T) {
	home := shortDesktopTestHome(t)
	cfg := managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional-secret-not-for-projection"}
	if e := managedclient.SaveConfig(home, cfg); e != nil {
		t.Fatal(e)
	}
	makeTask := func(id int64, action string) managedclient.Task {
		return managedclient.Task{ID: id, TaskType: "aidr_plugin_action", Payload: map[string]any{"action": action, "agent": "", "plugin_version": hooks.BundledPluginVersion, "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339)}}
	}
	applied, e := executeAIDRTask(context.Background(), home, makeTask(7, "enable"))
	if e != nil || applied["enabled"] != true || applied["managed_task"] != "7" {
		t.Fatal(applied, e)
	}
	var out bytes.Buffer
	if e := aidrDesktop([]string{"--home", home, "--action", "disable"}, &out); e == nil || e.Error() != "aidr_desktop_platform_managed" {
		t.Fatal("local mutation replaced platform requirement", e)
	}
	if _, e := executeAIDRTask(context.Background(), home, makeTask(6, "disable")); e == nil || e.Error() != "aidr_desktop_task_superseded" {
		t.Fatal(e)
	}
	disabled, e := executeAIDRTask(context.Background(), home, makeTask(8, "disable"))
	if e != nil || disabled["enabled"] != false {
		t.Fatal(disabled, e)
	}
	raw, _ := json.Marshal(disabled)
	if strings.Contains(string(raw), cfg.Token) {
		t.Fatal("credential entered projection")
	}
	cfg.Token = "fictional-rotated"
	if e := managedclient.SaveConfig(home, cfg); e != nil {
		t.Fatal(e)
	}
	out.Reset()
	if e := aidrDesktop([]string{"--home", home, "--action", "status"}, &out); e != nil {
		t.Fatal(e)
	}
	cfg.Server = "http://127.0.0.1:10"
	if e := managedclient.SaveConfig(home, cfg); e != nil {
		t.Fatal(e)
	}
	out.Reset()
	if e := aidrDesktop([]string{"--home", home, "--action", "status"}, &out); e == nil || e.Error() != "aidr_desktop_managed_binding_changed" {
		t.Fatal(e)
	}
	if aidrRuntimeSnapshot(home)["receiver_code"] != "aidr_desktop_managed_binding_changed" {
		t.Fatal("old authority shown for new platform")
	}
}

func TestAIDRExpiredTaskAndStoppedTelemetry(t *testing.T) {
	home := shortDesktopTestHome(t)
	if e := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional"}); e != nil {
		t.Fatal(e)
	}
	task := managedclient.Task{ID: 4, Payload: map[string]any{"action": "enable", "plugin_version": hooks.BundledPluginVersion, "expires_at": time.Now().Add(-time.Second).UTC().Format(time.RFC3339)}}
	if _, e := executeAIDRTask(context.Background(), home, task); e == nil || e.Error() != "aidr_desktop_task_expired" {
		t.Fatal(e)
	}
	_, paths, e := desktopBinding(home)
	if e != nil {
		t.Fatal(e)
	}
	if e := writeDesktopJSON(filepath.Join(paths.State, "receiver-status.json"), map[string]any{"updated_at": time.Now().UTC().Format(time.RFC3339Nano), "state": map[string]any{"queued_records": 0}}); e != nil {
		t.Fatal(e)
	}
	if aidrRuntimeSnapshot(home)["receiver_code"] != "aidr_desktop_stopped" {
		t.Fatal("fresh historical file falsely proves running receiver")
	}
}

func TestManagedAuthorizationOutcomeIsDurableAndRevisionBound(t *testing.T) {
	home := shortDesktopTestHome(t)
	cfg := managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional-outcome-secret"}
	managedclient.SaveConfig(home, cfg)
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{ManagedServer: cfg.Server, ManagedDevice: paths.Device, RuntimePolicy: &desktopRuntimePolicy{Version: "4", AppliedAt: "historical"}}
	for _, code := range []string{"aidr_managed_authorization_cancelled", "aidr_managed_authorization_interrupted", "aidr_managed_authorization_failed"} {
		var out bytes.Buffer
		if err := recordManagedAuthorization(prefs, cfg, paths, "4", code, &out); err != nil {
			t.Fatal(err)
		}
		loaded, err := loadDesktopPreferences(home)
		if err != nil || loaded.RuntimePolicy.Code != code || loaded.RuntimePolicy.AppliedAt != "historical" {
			t.Fatal("lost evidence", loaded, err)
		}
	}
	var out bytes.Buffer
	if err := recordManagedAuthorization(prefs, cfg, paths, "3", "aidr_managed_authorization_cancelled", &out); err == nil {
		t.Fatal("old revision replaced new target")
	}
	if err := recordManagedAuthorization(prefs, cfg, paths, "4", "raw outcome includes a secret", &out); err == nil {
		t.Fatal("unbounded result")
	}
}

func TestManagedRemovalRefreshesReportWithoutChangingAuditState(t *testing.T) {
	home := shortDesktopTestHome(t)
	managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional"})
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{Enabled: true, AccessMode: "managed", RuntimePolicy: &desktopRuntimePolicy{
		Version: "7", AppliedAt: "historical-application", Target: managedclient.RuntimeGovernancePolicy{AccessMode: "managed"},
	}}
	installed := true
	oldStamp := "2026-09-01T00:00:00Z"
	old := hooks.PluginStatus{Agent: "claude", HostVersion: "2.1.220", VersionStatus: "adapter_target", Installed: &installed, Enabled: &installed, ReportedAt: oldStamp, ConfigurationDigest: "old-digest", SourceCode: "aidr_managed_configuration_present"}
	writeDesktopJSON(filepath.Join(paths.Root, "observed-claude.json"), map[string]any{"plugin": old, "access_mode": "managed", "hook_trust": "managed", "managed_installed": true})
	other := filepath.Join(paths.Root, "observed-codex.json")
	writeDesktopJSON(other, map[string]any{"plugin": old, "access_mode": "ordinary"})
	otherBefore, _ := os.ReadFile(other)
	queue := filepath.Join(paths.State, "pending-evidence")
	writeDesktopJSON(queue, map[string]string{"digest": "frozen-body-must-remain"})
	queueBefore, _ := os.ReadFile(queue)
	var out bytes.Buffer
	if err := recordManagedRemoval(prefs, paths, "claude", &out); err != nil {
		t.Fatal(err)
	}
	report := aidrRuntimeSnapshot(home)
	if report["enabled"] != false || report["receiver_code"] != "aidr_desktop_stopped" {
		t.Fatal("removal retained an active receiver report", report)
	}
	claude := report["hosts"].([]any)[0].(map[string]any)
	if *claude["installed"].(*bool) || *claude["enabled"].(*bool) || claude["source_code"] != "aidr_managed_configuration_missing" || claude["hook_trust"] != "unknown" || claude["reported_at"] == oldStamp {
		t.Fatal("removal reused installed/trusted host evidence", claude)
	}
	loaded, err := loadDesktopPreferences(home)
	if err != nil || loaded.RuntimePolicy.AppliedAt != "historical-application" || loaded.RuntimePolicy.Version != "7" {
		t.Fatal("removal rewrote historical application evidence", loaded, err)
	}
	if data, _ := os.ReadFile(other); !bytes.Equal(data, otherBefore) {
		t.Fatal("removal changed the other host")
	}
	if data, _ := os.ReadFile(queue); !bytes.Equal(data, queueBefore) {
		t.Fatal("removal changed audit state")
	}
	for i := 0; i < 2; i++ {
		if err := recordManagedRemoval(loaded, paths, "claude", &out); err != nil {
			t.Fatal("repeated removal failed", err)
		}
	}
}

func TestManagedRemovalKeepsOrdinaryPluginAndRejectsUnreadableObservation(t *testing.T) {
	home := shortDesktopTestHome(t)
	managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional"})
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{Enabled: true, AccessMode: "ordinary", RuntimePolicy: &desktopRuntimePolicy{Target: managedclient.RuntimeGovernancePolicy{AccessMode: "ordinary"}}}
	installed := true
	path := filepath.Join(paths.Root, "observed-claude.json")
	writeDesktopJSON(path, map[string]any{"plugin": hooks.PluginStatus{Agent: "claude", Installed: &installed, Enabled: &installed, ReportedAt: "ordinary-check"}, "access_mode": "ordinary"})
	if err := recordManagedRemoval(prefs, paths, "claude", &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	report := aidrRuntimeSnapshot(home)
	claude := report["hosts"].([]any)[0].(map[string]any)
	if report["enabled"] != true || !*claude["installed"].(*bool) || !*claude["enabled"].(*bool) || claude["reported_at"] != "ordinary-check" {
		t.Fatal("system hook removal disabled an ordinary plugin", report)
	}
	os.WriteFile(path, []byte("invalid-observation"), 0600)
	if err := recordManagedRemoval(prefs, paths, "claude", &bytes.Buffer{}); err == nil {
		t.Fatal("invalid observation treated as empty")
	}
	if data, _ := os.ReadFile(path); string(data) != "invalid-observation" {
		t.Fatal("invalid observation overwritten")
	}
	os.Remove(path)
	if err := recordManagedRemoval(prefs, paths, "claude", &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("created an unobserved ordinary plugin report")
	}
}

func TestAIDRSupervisionReportIsBoundedAndNotReceiverHealth(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional-supervisor-token"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(paths.Root, "receiver-supervisor.json")
	fingerprint := "aabbccdd00112233"
	state := map[string]any{"version": 1, "queue": paths.State, "device": paths.Device, "configuration": fingerprint,
		"attempts": 3, "suspended": true, "active": false, "code": "aidr_desktop_receiver_failed",
		"next_retry_at_ms": time.Now().Add(time.Minute).UnixMilli(), "last_failure": "aidr_store_busy", "last_failure_at_ms": time.Now().UnixMilli()}
	if err = writeDesktopJSON(path, state); err != nil {
		t.Fatal(err)
	}
	result := aidrRuntimeSnapshot(home)
	observed, ok := result["receiver_supervision"].(map[string]any)
	if !ok || observed["retry_count"] != uint32(2) || observed["suspended"] != false || observed["next_retry_at"] == nil || result["receiver_code"] != "aidr_desktop_stopped" {
		t.Fatal(result)
	}
	bytes, _ := json.Marshal(result)
	if strings.Contains(string(bytes), fingerprint) || strings.Contains(string(bytes), "fictional-supervisor-token") {
		t.Fatal("private data entered status")
	}
	state["device"] = "wrong-device"
	if err = writeDesktopJSON(path, state); err != nil {
		t.Fatal(err)
	}
	if aidrRuntimeSnapshot(home)["receiver_supervision"] != nil {
		t.Fatal("wrong binding accepted")
	}
	state["device"], state["active"], state["suspended"] = paths.Device, true, false
	state["code"] = "aidr_desktop_running"
	if err = writeDesktopJSON(path, state); err != nil {
		t.Fatal(err)
	}
	result = aidrRuntimeSnapshot(home)
	if result["receiver_code"] != "aidr_desktop_stopped" || result["receiver_supervision"].(map[string]any)["suspended"] != false {
		t.Fatal("historical running record treated as healthy", result)
	}
	state["code"] = "aidr_desktop_health_rechecking"
	if err = writeDesktopJSON(path, state); err != nil {
		t.Fatal(err)
	}
	result = aidrRuntimeSnapshot(home)
	if result["receiver_code"] != "aidr_desktop_health_rechecking" || result["queued_records"] != nil {
		t.Fatal("rechecking must stay distinct from fresh receiver telemetry", result)
	}
	old := time.Now().Add(-time.Minute)
	if err = os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
	if aidrRuntimeSnapshot(home)["receiver_code"] != "aidr_desktop_stopped" {
		t.Fatal("old rechecking state was presented as current")
	}
}

func TestAIDRReconcilePersistsPolicyAndPreservesBinding(t *testing.T) {
	home := shortDesktopTestHome(t)
	cfg := managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional-policy-device"}
	if err := managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	policy := managedclient.RuntimeGovernancePolicy{Enabled: false, Hosts: []string{}, Installation: "automatic", AccessMode: "ordinary", Updates: "automatic", Retry: managedclient.ReceiverRetryPolicy{Mode: "continuous", Retries: 2, MaxIntervalSeconds: 60}}
	task := managedclient.Task{ID: 10, Payload: map[string]any{"action": "reconcile", "plugin_version": hooks.BundledPluginVersion, "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339), "policy_version": "8", "target": policy}}
	result, err := executeAIDRTask(context.Background(), home, task)
	if err != nil || result["policy_version"] != "8" || result["policy_applied_at"] == nil || result["enabled"] != false {
		t.Fatal(result, err)
	}
	prefs, err := loadDesktopPreferences(home)
	if err != nil || prefs.RuntimePolicy.Target.Retry.Mode != "continuous" {
		t.Fatal(prefs, err)
	}
	cfg.Token = "fictional-rotated-policy-device"
	if err = managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	var status bytes.Buffer
	if err = aidrDesktop([]string{"--home", home, "--action", "status"}, &status); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(status.String(), cfg.Token) {
		t.Fatal("credential entered policy projection")
	}
	task.ID = 9
	if _, err = executeAIDRTask(context.Background(), home, task); err == nil || err.Error() != "aidr_desktop_task_superseded" {
		t.Fatal(err)
	}
}

func TestAIDRManagedPolicyDoesNotClaimAuthorizationOrLoop(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional"}); err != nil {
		t.Fatal(err)
	}
	policy := managedclient.RuntimeGovernancePolicy{Enabled: true, Hosts: []string{"codex"}, Installation: "automatic", AccessMode: "managed", Updates: "manual", Retry: managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 300}}
	task := managedclient.Task{ID: 12, Payload: map[string]any{"action": "reconcile", "plugin_version": hooks.BundledPluginVersion, "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339), "policy_version": "9", "target": policy}}
	result, err := executeAIDRTask(context.Background(), home, task)
	if err == nil || err.Error() != "aidr_desktop_managed_authorization_required" || result["policy_applied_at"] != nil {
		t.Fatal(result, err)
	}
	prefs, _ := loadDesktopPreferences(home)
	if prefs.RuntimePolicy.Code != "aidr_desktop_managed_authorization_required" || prefs.RuntimePolicy.AppliedAt != "" {
		t.Fatal(prefs)
	}
}

func TestReconcileMissingHostDoesNotSkipOtherAgent(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(home, "claude-fixture")
	if err = os.WriteFile(binary, []byte("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then printf 'fixture\\n'; else printf '[]\\n'; fi\n"), 0700); err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{Hosts: map[string]desktopHost{"codex": {Home: filepath.Join(home, ".codex")}, "claude": {Binary: binary, Home: filepath.Join(home, ".claude")}}}
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	target := managedclient.RuntimeGovernancePolicy{Enabled: true, Hosts: []string{"codex", "claude"}, Installation: "manual", AccessMode: "ordinary", Updates: "manual", Retry: managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 300}}
	result, err := reconcileAIDRPolicy(context.Background(), home, managedclient.Task{ID: 1, Payload: map[string]any{"policy_version": "1", "target": target}})
	if err != nil || result["enabled"] != true {
		t.Fatal(result, err)
	}
	for _, agent := range []string{"codex", "claude"} {
		var observed struct {
			Plugin hooks.PluginStatus `json:"plugin"`
		}
		if err = readDesktopJSON(filepath.Join(paths.Root, "observed-"+agent+".json"), &observed); err != nil {
			t.Fatal(err)
		}
		if agent == "codex" && observed.Plugin.SourceCode != "aidr_desktop_host_missing" {
			t.Fatal(observed)
		}
		if agent == "claude" && (observed.Plugin.Installed == nil || *observed.Plugin.Installed) {
			t.Fatal("second Agent was not inspected", observed)
		}
	}
}
