package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func init() {
	managedclient.AIDRTaskHandler = executeAIDRTask
	managedclient.AIDRRuntimeSnapshot = aidrRuntimeSnapshot
	managedclient.AIDRRuntimeInspect = inspectAIDRTarget
	managedclient.AIDRLogRunner = runAutomaticLogs
}

func inspectAIDRTarget(ctx context.Context, home string, policy managedclient.Policy) error {
	target := policy.Classification.RuntimeGovernance
	if !policy.Classification.RuntimeGovernanceConfigured || target == nil || !target.Valid() || !target.CollectHooks() {
		return nil
	}
	ctx, release, err := managedclient.AIDRMutationLock(ctx, home)
	if err != nil {
		return errors.New("aidr_desktop_action_busy")
	}
	defer release()
	prefs, err := loadDesktopPreferences(home)
	if err != nil {
		return err
	}
	cfg, paths, err := desktopBinding(home)
	if err != nil {
		return err
	}
	if prefs.ManagedTask > 0 && (prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device) {
		return errors.New("aidr_desktop_managed_binding_changed")
	}
	var first error
	checkedCode := "aidr_desktop_policy_applied"
	for _, agent := range target.Hosts {
		if ctx.Err() != nil {
			return errors.New("aidr_desktop_task_interrupted")
		}
		var output bytes.Buffer
		if err := aidrDesktopContext(ctx, []string{"--home", home, "--action", "inspect", "--agent", agent}, &output); err != nil {
			code := stableAIDRCode(err)
			if first == nil {
				first = errors.New(code)
			}
			unknown := hooks.PluginStatus{Agent: agent, VersionStatus: "unverified", SourceCode: code, ReportedAt: time.Now().UTC().Format(time.RFC3339Nano)}
			if err = writeDesktopJSON(filepath.Join(paths.Root, "observed-"+agent+".json"), map[string]any{"plugin": unknown, "hook_trust": "unknown", "access_mode": target.AccessMode}); err != nil {
				return err
			}
			checkedCode = code
			continue
		}
		var observed struct {
			Plugin hooks.PluginStatus `json:"plugin"`
		}
		if json.Unmarshal(output.Bytes(), &observed) != nil {
			return errors.New("aidr_desktop_status_failed")
		}
		status := observed.Plugin
		if status.VersionStatus != "adapter_target" {
			checkedCode = "aidr_plugin_version_unverified"
		} else if status.Installed == nil {
			checkedCode = "aidr_plugin_source_unreadable"
		} else if !*status.Installed {
			if target.AccessMode == "managed" {
				checkedCode = "aidr_desktop_managed_authorization_required"
			} else {
				checkedCode = "aidr_plugin_not_installed"
			}
		} else if target.Updates == "automatic" && status.PluginVersion != hooks.BundledPluginVersion {
			checkedCode = "aidr_desktop_package_update_required"
		}
	}
	// A last successful application remains historical evidence. A current
	// failed observation must not continue to report that target as applied.
	if prefs.RuntimePolicy != nil && prefs.RuntimePolicy.Version == policy.Classification.RuntimeGovernanceVersion {
		prefs.RuntimePolicy.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
		preserveAuthorization := checkedCode == "aidr_desktop_managed_authorization_required" && (prefs.RuntimePolicy.Code == "aidr_managed_authorization_cancelled" || prefs.RuntimePolicy.Code == "aidr_managed_authorization_failed" || prefs.RuntimePolicy.Code == "aidr_managed_authorization_interrupted")
		if checkedCode != "aidr_desktop_policy_applied" && !preserveAuthorization {
			prefs.RuntimePolicy.Code = checkedCode
		}
		if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
			return err
		}
	}
	return first
}

func executeAIDRTask(ctx context.Context, home string, task managedclient.Task) (map[string]any, error) {
	get := func(k string) string { s, _ := task.Payload[k].(string); return s }
	action, agent := get("action"), get("agent")
	if task.ID <= 0 || get("plugin_version") != hooks.BundledPluginVersion {
		return nil, errors.New("aidr_desktop_task_invalid")
	}
	expires, e := time.Parse(time.RFC3339, get("expires_at"))
	if e != nil || !expires.After(time.Now()) {
		return nil, errors.New("aidr_desktop_task_expired")
	}
	if action == "reconcile" {
		return reconcileAIDRPolicy(ctx, home, task)
	}
	if action != "install" && action != "upgrade" && action != "enable" && action != "disable" && action != "inspect" {
		return nil, errors.New("aidr_desktop_task_invalid")
	}
	if action == "install" || action == "upgrade" || action == "inspect" {
		if agent != "claude" && agent != "codex" {
			return nil, errors.New("aidr_desktop_task_invalid")
		}
	} else if agent != "" {
		return nil, errors.New("aidr_desktop_task_invalid")
	}
	if action == "install" {
		action = "connect"
	}
	var out bytes.Buffer
	e = aidrDesktopContext(ctx, []string{"--home", home, "--action", action, "--agent", agent, "--managed-task-id", strconv.FormatInt(task.ID, 10)}, &out)
	if e != nil {
		if strings.HasPrefix(e.Error(), "aidr_") && len(e.Error()) < 100 {
			return nil, e
		}
		return nil, errors.New("aidr_desktop_receiver_failed")
	}
	return aidrRuntimeSnapshot(home), nil
}

// This reads only bounded, already projected local state. No native version
// probe or raw settings/credential ever enters a heartbeat.
func aidrRuntimeSnapshot(home string) map[string]any {
	result := map[string]any{"protocol": 4, "plugin_version": hooks.BundledPluginVersion, "hosts": []any{}, "receiver_code": "aidr_desktop_stopped"}
	if runtime.GOOS != "darwin" && runtime.GOOS != "linux" {
		result["protocol"] = 0
		result["receiver_code"] = "aidr_desktop_platform_unsupported"
		return result
	}
	prefs, e := loadDesktopPreferences(home)
	if e != nil {
		result["receiver_code"] = "aidr_desktop_config_unreadable"
		return result
	}
	result["enabled"] = prefs.Enabled
	result["managed_task"] = strconv.FormatInt(prefs.ManagedTask, 10)
	if p := prefs.RuntimePolicy; p != nil {
		result["policy_version"], result["policy_received_at"], result["policy_checked_at"], result["policy_code"] = p.Version, p.ReceivedAt, p.CheckedAt, p.Code
		if p.AppliedAt != "" {
			result["policy_applied_at"] = p.AppliedAt
		}
	}
	cfg, paths, e := desktopBinding(home)
	if e != nil {
		result["receiver_code"] = "aidr_desktop_not_configured"
		return result
	}
	if prefs.ManagedTask > 0 && (prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device) {
		result["receiver_code"] = "aidr_desktop_managed_binding_changed"
		return result
	}
	var supervision struct {
		Version       int     `json:"version"`
		Queue         string  `json:"queue"`
		Device        string  `json:"device"`
		Attempts      uint32  `json:"attempts"`
		Active        bool    `json:"active"`
		Suspended     bool    `json:"suspended"`
		Code          string  `json:"code"`
		NextRetryAt   uint64  `json:"next_retry_at_ms"`
		LastFailure   *string `json:"last_failure"`
		LastFailureAt *uint64 `json:"last_failure_at_ms"`
	}
	supervisionPath := filepath.Join(paths.Root, "receiver-supervisor.json")
	if readDesktopJSON(supervisionPath, &supervision) == nil && supervision.Version == 1 && supervision.Queue == paths.State && supervision.Device == paths.Device && validRuntimeCode(supervision.Code) {
		// Report the last supervisor observation separately from the live
		// receiver health file. An old running record is not a healthy process.
		if meta, e := os.Stat(supervisionPath); e == nil {
			retry := managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 300}
			if prefs.RuntimePolicy != nil {
				retry = prefs.RuntimePolicy.Target.Retry
			}
			exhausted := !supervision.Active && supervision.Attempts > 0 && (retry.Mode == "none" || (retry.Mode == "fixed" && supervision.Attempts > uint32(retry.Retries)))
			value := map[string]any{"attempts": supervision.Attempts, "retry_count": uint32(0), "mode": retry.Mode,
				"suspended": supervision.Suspended || exhausted, "code": supervision.Code, "observed_at": meta.ModTime().UTC().Format(time.RFC3339Nano)}
			if supervision.Attempts > 0 {
				value["retry_count"] = supervision.Attempts - 1
			}
			if supervision.NextRetryAt > 0 && supervision.NextRetryAt <= 253402300799999 {
				value["next_retry_at"] = time.UnixMilli(int64(supervision.NextRetryAt)).UTC().Format(time.RFC3339Nano)
			}
			if supervision.LastFailure != nil && validRuntimeCode(*supervision.LastFailure) {
				value["last_failure"] = *supervision.LastFailure
			}
			if supervision.LastFailureAt != nil && *supervision.LastFailureAt <= 253402300799999 {
				value["last_failure_at"] = time.UnixMilli(int64(*supervision.LastFailureAt)).UTC().Format(time.RFC3339Nano)
			}
			result["receiver_supervision"] = value
			age := time.Since(meta.ModTime())
			if supervision.Active && supervision.Code == "aidr_desktop_health_rechecking" && age >= 0 && age < 15*time.Second {
				result["receiver_code"] = supervision.Code
			}
		}
	}
	var telemetry struct {
		State struct {
			Queued          int    `json:"queued_records"`
			ControlMode     string `json:"control_mode"`
			ControlRevision string `json:"control_revision"`
			LastSequence    string `json:"last_sequence"`
			Policy          struct {
				Version string `json:"version"`
				Enabled bool   `json:"enabled"`
			} `json:"policy"`
		} `json:"state"`
		Updated     string `json:"updated_at"`
		LastReport  string `json:"last_report"`
		RuntimeCode string `json:"runtime_code"`
		UploadCode  string `json:"upload_code"`
	}
	if readDesktopJSON(paths.Status, &telemetry) == nil {
		stamp, err := time.Parse(time.RFC3339Nano, telemetry.Updated)
		_, socketErr := os.Lstat(paths.Socket)
		if socketErr == nil && err == nil && time.Since(stamp) >= 0 && time.Since(stamp) < 15*time.Second {
			result["receiver_code"] = "aidr_desktop_running"
			result["queued_records"] = telemetry.State.Queued
			result["last_report"] = telemetry.LastReport
			result["transport_code"] = telemetry.RuntimeCode
			result["upload_code"] = telemetry.UploadCode
			result["control_mode"] = telemetry.State.ControlMode
			result["control_revision"] = telemetry.State.ControlRevision
			result["hook_sequence"] = telemetry.State.LastSequence
			result["audit_policy_version"] = telemetry.State.Policy.Version
			result["audit_redaction_enabled"] = telemetry.State.Policy.Enabled
		}
	}
	hosts := []any{}
	for _, agent := range []string{"claude", "codex"} {
		var observed struct {
			Plugin     hooks.PluginStatus `json:"plugin"`
			Trust      string             `json:"hook_trust"`
			AccessMode string             `json:"access_mode"`
		}
		if readDesktopJSON(filepath.Join(paths.Root, "observed-"+agent+".json"), &observed) == nil {
			mode := observed.AccessMode
			if mode == "" {
				mode = "ordinary"
			}
			hosts = append(hosts, map[string]any{"agent": agent, "host_version": observed.Plugin.HostVersion, "plugin_version": observed.Plugin.PluginVersion, "version_status": observed.Plugin.VersionStatus, "installed": observed.Plugin.Installed, "enabled": observed.Plugin.Enabled, "hook_trust": observed.Trust, "reported_at": observed.Plugin.ReportedAt, "source_code": observed.Plugin.SourceCode, "access_mode": mode})
		}
	}
	result["hosts"] = hosts
	result["channels"] = runtimeChannelSnapshot(paths, prefs, result)
	return result
}

func validRuntimeCode(code string) bool {
	if !strings.HasPrefix(code, "aidr_") || len(code) >= 100 {
		return false
	}
	for _, char := range code {
		if char != '_' && (char < 'a' || char > 'z') && (char < '0' || char > '9') {
			return false
		}
	}
	return true
}

func reconcileAIDRPolicy(ctx context.Context, home string, task managedclient.Task) (map[string]any, error) {
	ctx, release, err := managedclient.AIDRMutationLock(ctx, home)
	if err != nil {
		return nil, errors.New("aidr_desktop_action_busy")
	}
	defer release()
	version, _ := task.Payload["policy_version"].(string)
	if !validRuntimePolicyVersion(version) {
		return nil, errors.New("aidr_desktop_task_invalid")
	}
	body, err := json.Marshal(task.Payload["target"])
	var target managedclient.RuntimeGovernancePolicy
	if err != nil || json.Unmarshal(body, &target) != nil || !target.Valid() {
		return nil, errors.New("aidr_desktop_task_invalid")
	}
	prefs, err := loadDesktopPreferences(home)
	if err != nil {
		return nil, err
	}
	cfg, paths, err := desktopBinding(home)
	if err != nil {
		return nil, err
	}
	if prefs.ManagedTask > task.ID && prefs.ManagedServer == cfg.Server && prefs.ManagedDevice == paths.Device {
		return nil, errors.New("aidr_desktop_task_superseded")
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	if target.Modes != nil && target.Modes.Hooks != "" {
		if target.Modes.Hooks == "intercept" {
			keyPath, e := prepareHookControlKey(ctx, cfg, paths, prefs.PublicKey)
			if e != nil {
				return nil, e
			}
			prefs.PublicKey = keyPath
		}
		prefs.HookMode = target.Modes.Hooks
	}
	prefs.ManagedTask, prefs.ManagedServer, prefs.ManagedDevice = task.ID, cfg.Server, paths.Device
	prefs.RuntimePolicy = &desktopRuntimePolicy{Target: target, Version: version, ReceivedAt: now, CheckedAt: now, Code: "aidr_desktop_policy_applying"}
	prefs.AuthorizationTask = 0
	prefs.AuthorizationAgent, prefs.AuthorizationAction = "", ""
	prefs.Enabled = target.CollectHooks()
	if target.AccessMode == "ordinary" {
		prefs.AccessMode = "ordinary"
	}
	if target.CollectHooks() && target.AccessMode == "managed" && len(target.Hosts) > 0 {
		ready := true
		for _, agent := range target.Hosts {
			configured, e := hooks.SystemManagedConfigured(agent)
			if e != nil || !configured {
				ready = false
			}
			if configured {
				installedVersion, e := hooks.SystemManagedVersion(agent)
				if e != nil || (target.Updates == "automatic" && installedVersion != hooks.BundledPluginVersion) {
					ready = false
				}
			}
		}
		if ready {
			prefs.AccessMode = "managed"
		} else {
			prefs.Enabled = false
		}
	}
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		return nil, err
	}
	if err = writeDesktopConnection(paths, prefs); err != nil {
		return nil, err
	}
	finish := func(code string, applied bool) (map[string]any, error) {
		latest, e := loadDesktopPreferences(home)
		if e != nil {
			return nil, e
		}
		if latest.ManagedTask != task.ID || latest.RuntimePolicy == nil || latest.RuntimePolicy.Version != version {
			return nil, errors.New("aidr_desktop_task_superseded")
		}
		latest.RuntimePolicy.Code = code
		latest.RuntimePolicy.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
		if applied {
			latest.RuntimePolicy.AppliedAt = latest.RuntimePolicy.CheckedAt
		}
		if e = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), latest); e != nil {
			return nil, e
		}
		if !applied {
			return aidrRuntimeSnapshot(home), errors.New(code)
		}
		return aidrRuntimeSnapshot(home), nil
	}
	if target.CollectHooks() && target.AccessMode == "managed" && len(target.Hosts) > 0 && !prefs.Enabled {
		return finish("aidr_desktop_managed_authorization_required", false)
	}
	if target.CollectHooks() {
		for _, agent := range target.Hosts {
			if ctx.Err() != nil {
				return finish("aidr_desktop_task_interrupted", false)
			}
			var observed bytes.Buffer
			args := []string{"--home", home, "--action", "inspect", "--agent", agent, "--managed-task-id", strconv.FormatInt(task.ID, 10)}
			if e := aidrDesktopContext(ctx, args, &observed); e != nil {
				return finish(stableAIDRCode(e), false)
			}
			var state struct {
				Plugin hooks.PluginStatus `json:"plugin"`
			}
			if json.Unmarshal(observed.Bytes(), &state) != nil {
				return finish("aidr_desktop_status_invalid", false)
			}
			if state.Plugin.VersionStatus != "adapter_target" {
				return finish("aidr_plugin_version_unverified", false)
			}
			if target.AccessMode == "managed" {
				continue
			}
			if state.Plugin.Installed == nil {
				return finish("aidr_plugin_source_unreadable", false)
			}
			action := ""
			if !*state.Plugin.Installed && target.Installation == "automatic" {
				action = "connect"
			}
			if *state.Plugin.Installed && state.Plugin.PluginVersion != hooks.BundledPluginVersion && target.Updates == "automatic" {
				action = "upgrade"
			}
			if action != "" {
				args[3] = action
				if e := aidrDesktopContext(ctx, args, io.Discard); e != nil {
					return finish(stableAIDRCode(e), false)
				}
				args[3] = "inspect"
				if e := aidrDesktopContext(ctx, args, io.Discard); e != nil {
					return finish(stableAIDRCode(e), false)
				}
			}
		}
	}
	return finish("aidr_desktop_policy_applied", true)
}
func stableAIDRCode(err error) string {
	code := err.Error()
	if strings.HasPrefix(code, "aidr_") && len(code) < 100 && !strings.ContainsAny(code, " \n\t") {
		return code
	}
	return "aidr_desktop_receiver_failed"
}
