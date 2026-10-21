package main

import (
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/localstore"
)

func validRuntimePolicyVersion(version string) bool {
	if len(version) > 40 {
		return false
	}
	parts := strings.Split(version, ":")
	if len(parts) < 1 || len(parts) > 2 {
		return false
	}
	for _, part := range parts {
		if part == "" {
			return false
		}
		for _, c := range part {
			if c < '0' || c > '9' {
				return false
			}
		}
		if _, err := strconv.ParseUint(part, 10, 64); err != nil {
			return false
		}
	}
	return true
}

// A heartbeat forwards observation timestamps. Reading old files never makes
// their historical observation current, and no payload or credential is read.
func runtimeChannelSnapshot(paths desktopPaths, prefs desktopPreferences, hook map[string]any) map[string]any {
	channels := map[string]any{}
	state := "unknown"
	code, _ := hook["receiver_code"].(string)
	switch code {
	case "aidr_desktop_running":
		state = "running"
	case "aidr_desktop_stopped":
		state = "stopped"
	case "aidr_desktop_starting", "aidr_desktop_health_rechecking":
		state = "starting"
	default:
		state = "failed"
	}
	var telemetry struct {
		Updated string `json:"updated_at"`
		State   struct {
			Mode    string `json:"control_mode"`
			LastACK string `json:"last_event_ack_at"`
			Enabled *bool  `json:"runtime_collection_enabled"`
			Version string `json:"runtime_policy_version"`
		} `json:"state"`
	}
	if readDesktopJSON(paths.Status, &telemetry) == nil {
		if _, err := time.Parse(time.RFC3339Nano, telemetry.Updated); err == nil {
			if telemetry.State.Enabled != nil && !*telemetry.State.Enabled && state == "running" {
				state = "draining"
				code = "aidr_hook_collection_disabled"
			}
			value := map[string]any{"state": state, "code": code, "reported_at": telemetry.Updated}
			if telemetry.State.Mode == "audit" {
				value["mode"] = "audit"
			}
			if telemetry.State.Mode == "plugin_pre_tool" {
				value["mode"] = "intercept"
			}
			if telemetry.State.Enabled != nil {
				value["enabled"] = telemetry.State.Enabled
			}
			if telemetry.State.Version != "" && validRuntimePolicyVersion(telemetry.State.Version) {
				value["policy_version"] = telemetry.State.Version
			}
			for _, key := range []string{"queued_records", "transport_code"} {
				if v, ok := hook[key]; ok {
					value[key] = v
				}
			}
			if _, err := time.Parse(time.RFC3339Nano, telemetry.State.LastACK); err == nil {
				value["last_ack_at"] = telemetry.State.LastACK
			}
			channels["hooks"] = value
		}
	}
	var stopped struct {
		Version       int    `json:"version"`
		Device        string `json:"client_id"`
		Queue         string `json:"queue"`
		PolicyVersion string `json:"policy_version"`
		Stamp         string `json:"observed_at_ms"`
		Enabled       *bool  `json:"enabled"`
		Code          string `json:"code"`
	}
	if !prefs.Enabled && prefs.RuntimePolicy != nil && readDesktopJSON(filepath.Join(paths.Root, "hook-collection-status.json"), &stopped) == nil && stopped.Version == 1 && stopped.Device == paths.Device && stopped.Queue == paths.State && stopped.PolicyVersion == prefs.RuntimePolicy.Version && stopped.Enabled != nil && !*stopped.Enabled && stopped.Code == "aidr_desktop_disabled" {
		if ms, err := strconv.ParseInt(stopped.Stamp, 10, 64); err == nil && ms > 0 && time.UnixMilli(ms).Before(time.Now().Add(5*time.Second)) {
			observed := time.UnixMilli(ms)
			previous, _ := time.Parse(time.RFC3339Nano, telemetry.Updated)
			if observed.After(previous) {
				value := map[string]any{"state": "disabled", "code": stopped.Code, "enabled": false, "policy_version": stopped.PolicyVersion, "reported_at": observed.UTC().Format(time.RFC3339Nano), "queued_records": 0}
				if _, err := time.Parse(time.RFC3339Nano, telemetry.State.LastACK); err == nil {
					value["last_ack_at"] = telemetry.State.LastACK
				}
				channels["hooks"] = value
			}
		}
	}
	statePath := filepath.Join(paths.Root, "log-queues", filepath.Base(paths.State))
	var logs struct {
		Version       int               `json:"version"`
		Device        string            `json:"client_id"`
		PolicyVersion string            `json:"policy_version"`
		Enabled       *bool             `json:"enabled"`
		Code          string            `json:"code"`
		ReportedAt    string            `json:"reported_at"`
		State         localstore.Status `json:"state"`
	}
	var supervisor logSupervision
	if readDesktopJSON(filepath.Join(statePath, "log-supervisor.json"), &supervisor) == nil && supervisor.valid() {
		if _, err := time.Parse(time.RFC3339Nano, supervisor.UpdatedAt); err == nil && validRuntimePolicyVersion(supervisor.PolicyVersion) {
			status := "starting"
			if supervisor.Suspended {
				status = "failed"
			} else if supervisor.Code == "aidr_log_stopped" {
				status = "stopped"
			}
			channels["logs"] = map[string]any{"state": status, "code": supervisor.Code, "reported_at": supervisor.UpdatedAt, "policy_version": supervisor.PolicyVersion}
		}
	}
	if readDesktopJSON(filepath.Join(statePath, "log-status.json"), &logs) == nil && logs.Version == 1 && logs.Device == paths.Device && validRuntimeCode(logs.Code) && validRuntimePolicyVersion(logs.PolicyVersion) {
		stamp, err := time.Parse(time.RFC3339Nano, logs.ReportedAt)
		lastSupervisor, _ := time.Parse(time.RFC3339Nano, supervisor.UpdatedAt)
		if err == nil && (!supervisor.Suspended && supervisor.Code != "aidr_log_stopped" || stamp.After(lastSupervisor)) {
			status := "running"
			if logs.Enabled != nil && !*logs.Enabled {
				status = "draining"
			}
			value := map[string]any{"state": status, "code": logs.Code, "enabled": logs.Enabled, "policy_version": logs.PolicyVersion, "reported_at": logs.ReportedAt, "queued_records": logs.State.Queued}
			if _, err := time.Parse(time.RFC3339Nano, logs.State.LastAcknowledgedAt); err == nil {
				value["last_ack_at"] = logs.State.LastAcknowledgedAt
			}
			if validRuntimeCode(logs.State.UploadCode) {
				value["transport_code"] = logs.State.UploadCode
			}
			if _, err := time.Parse(time.RFC3339Nano, logs.State.NextRetryAt); err == nil {
				value["next_retry_at"] = logs.State.NextRetryAt
			}
			coverage := []string{}
			for _, code := range []string{logs.State.IntakeCode, logs.State.CapacityCode, logs.State.RecoveryCode} {
				if validRuntimeCode(code) {
					coverage = append(coverage, code)
				}
			}
			value["coverage_codes"] = coverage
			channels["logs"] = value
		}
	}
	if system := systemRuntimeChannel(paths); system != nil {
		channels["system"] = system
	}
	return channels
}
