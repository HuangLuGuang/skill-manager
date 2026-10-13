package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

type hookRunPlan struct {
	paths    desktopPaths
	cfg      managedclient.Config
	prefs    desktopPreferences
	retry    managedclient.ReceiverRetryPolicy
	required bool
}

func automaticHookPlan(ctx context.Context, home string) (hookRunPlan, error) {
	var p hookRunPlan
	var err error
	p.cfg, p.paths, err = desktopBinding(home)
	if err != nil {
		return p, err
	}
	p.prefs, err = loadDesktopPreferences(home)
	if err != nil {
		return p, err
	}
	if p.prefs.ManagedTask > 0 && (p.prefs.ManagedServer != p.cfg.Server || p.prefs.ManagedDevice != p.paths.Device) {
		return p, errors.New("aidr_desktop_managed_binding_changed")
	}
	p.retry = managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 300}
	if p.prefs.RuntimePolicy != nil {
		p.retry = p.prefs.RuntimePolicy.Target.Retry
	}
	if p.retry.Mode != "none" && p.retry.Mode != "fixed" && p.retry.Mode != "continuous" || p.retry.Retries < 0 || p.retry.Retries > 20 || p.retry.MaxIntervalSeconds < 10 || p.retry.MaxIntervalSeconds > 3600 {
		return p, errors.New("aidr_hook_runtime_target_invalid")
	}
	p.required = p.prefs.Enabled
	if !p.required {
		pending, e := hooks.PendingUploads(ctx, p.paths.State)
		if e != nil {
			return p, e
		}
		p.required = pending > 0
	}
	return p, nil
}

func (p hookRunPlan) identity() string {
	// Credentials participate only in this private fingerprint, never telemetry.
	b, _ := json.Marshal([]any{p.cfg.Server, p.cfg.Token, p.paths.State, p.paths.Device, p.retry})
	digest := sha256.Sum256(b)
	return hex.EncodeToString(digest[:])
}

type hookSupervision struct {
	Version       int    `json:"version"`
	Configuration string `json:"configuration"`
	Queue         string `json:"queue"`
	Device        string `json:"device"`
	Attempts      int    `json:"attempts"`
	Suspended     bool   `json:"suspended"`
	Active        bool   `json:"active"`
	Code          string `json:"code"`
	NextRetryAt   int64  `json:"next_retry_at_ms"`
	LastFailure   string `json:"last_failure,omitempty"`
	LastFailureAt int64  `json:"last_failure_at_ms,omitempty"`
	RetryRequest  string `json:"retry_request,omitempty"`
	PID           int    `json:"pid,omitempty"`
}

func (s hookSupervision) valid() bool {
	_, err := hex.DecodeString(s.Configuration)
	return err == nil && (len(s.Configuration) == 16 || len(s.Configuration) == 64) && s.Version == 1 && s.Attempts >= 0 && s.Attempts <= 21 && validRuntimeCode(s.Code) && (s.LastFailure == "" || validRuntimeCode(s.LastFailure))
}

func hookCorrectionRequired(code string) bool {
	switch code {
	case "aidr_upload_auth_rejected", "aidr_desktop_managed_binding_changed", "aidr_store_binding_mismatch", "aidr_hook_socket_exists", "aidr_store_busy", "aidr_plugin_version_unverified", "aidr_desktop_managed_authorization_required", "aidr_desktop_receiver_conflict", "aidr_desktop_retry_state_invalid", "aidr_desktop_retry_state_unwritable":
		return true
	}
	return false
}

func (s *hookSupervision) failure(code string, retry managedclient.ReceiverRetryPolicy, now time.Time) {
	s.Active, s.Code, s.LastFailure, s.LastFailureAt = false, code, code, now.UnixMilli()
	s.Suspended = hookCorrectionRequired(code) || s.Attempts >= logRetryLimit(retry)
	delay := min(time.Duration(1<<min(s.Attempts, 12))*time.Second, time.Duration(retry.MaxIntervalSeconds)*time.Second)
	s.NextRetryAt = now.Add(delay).UnixMilli()
}

type managedHookContextKey struct{}

func runAutomaticHooks(ctx context.Context, home string) {
	if runtime.GOOS != "darwin" && runtime.GOOS != "linux" {
		return
	}
	manageAutomaticHooks(ctx, home, time.Second, func(ctx context.Context) error {
		if err := aidrDesktopContext(ctx, []string{"--home", home, "--action", "prepare"}, io.Discard); err != nil {
			return err
		}
		return aidrHookServeContext(context.WithValue(ctx, managedHookContextKey{}, true), []string{"--managed-home", home}, io.Discard)
	})
}

// One goroutine in the main daemon owns the receiver and joins it before
// rebinding. The shared lock also serializes migration from older desktops.
func manageAutomaticHooks(ctx context.Context, home string, interval time.Duration, worker func(context.Context) error) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	var current hookRunPlan
	var state hookSupervision
	var release func()
	var cancel context.CancelFunc
	var done chan error
	var savedState []byte
	var healthySince, started, lastCheck, resumeUntil time.Time
	stop := func() {
		if cancel != nil {
			cancel()
			<-done
			cancel, done = nil, nil
		}
		state.Active = false
		healthySince = time.Time{}
	}
	persist := func() bool {
		if release == nil || state.Configuration == "" {
			return true
		}
		encoded, _ := json.Marshal(state)
		if bytes.Equal(encoded, savedState) {
			return true
		}
		if writeDesktopJSON(filepath.Join(current.paths.Root, "receiver-supervisor.json"), state) != nil {
			stop()
			state.Code, state.Suspended = "aidr_desktop_retry_state_unwritable", true
			return false
		}
		savedState = encoded
		return true
	}
	defer func() {
		stop()
		if state.Code == "aidr_desktop_running" || state.Code == "aidr_desktop_draining" {
			state.Attempts, state.Suspended, state.NextRetryAt = 0, false, 0
			state.Code = "aidr_desktop_stopped"
		}
		persist()
		if release != nil {
			release()
		}
	}()
	for {
		if ctx.Err() != nil {
			return
		}
		now := time.Now()
		if !lastCheck.IsZero() && (now.Sub(lastCheck) > 15*time.Second || now.Before(lastCheck)) {
			resumeUntil = now.Add(15 * time.Second)
			healthySince = time.Time{}
		}
		lastCheck = now
		plan, err := automaticHookPlan(ctx, home)
		if err != nil {
			stop()
			state.Code = stableAIDRCode(err)
			persist()
		} else {
			if release == nil {
				if os.MkdirAll(plan.paths.Root, 0700) == nil {
					release, _ = acquireHookSupervisor(plan.paths.Root)
				}
			}
			if release != nil {
				if state.Configuration != plan.identity() {
					stop()
					current = plan
					state = hookSupervision{Version: 1, Configuration: plan.identity(), Queue: plan.paths.State, Device: plan.paths.Device, Code: "aidr_desktop_stopped", PID: os.Getpid()}
					var saved hookSupervision
					path := filepath.Join(plan.paths.Root, "receiver-supervisor.json")
					if _, e := os.Lstat(path); e == nil {
						if readDesktopJSON(path, &saved) != nil || !saved.valid() {
							state.Code, state.Suspended = "aidr_desktop_retry_state_invalid", true
						} else if saved.Queue == state.Queue && saved.Device == state.Device && (saved.Configuration == state.Configuration || len(saved.Configuration) == 16) {
							identity := state.Configuration
							state = saved
							state.Configuration, state.PID = identity, os.Getpid()
							if state.Active {
								state.failure("aidr_desktop_receiver_interrupted", plan.retry, now)
							}
							state.NextRetryAt = min(state.NextRetryAt, now.Add(time.Duration(plan.retry.MaxIntervalSeconds)*time.Second).UnixMilli())
						}
					}
				}
				current = plan
				var request logRetryRequest
				if readDesktopJSON(filepath.Join(plan.paths.Root, "hook-retry-request.json"), &request) == nil && request.valid(logSupervision{Configuration: state.Configuration}, now) && request.Nonce != state.RetryRequest && state.Code != "aidr_desktop_retry_state_invalid" {
					state.RetryRequest = request.Nonce
					if done == nil {
						state.Attempts, state.Suspended, state.NextRetryAt = 0, false, 0
					}
				}
				if done != nil {
					select {
					case failure := <-done:
						cancel()
						cancel, done = nil, nil
						code := "aidr_desktop_receiver_ended"
						if failure != nil {
							code = stableAIDRCode(failure)
						}
						state.failure(code, plan.retry, now)
						healthySince = time.Time{}
					default:
					}
				}
				if !plan.required {
					if done != nil {
						// Policy-directed stopping is not a failed launch. A later
						// enable gets an initial attempt, including retry mode none.
						state.Attempts, state.Suspended, state.NextRetryAt = 0, false, 0
					}
					stop()
					if !state.Suspended {
						state.Code = "aidr_desktop_disabled"
					}
					if policy := plan.prefs.RuntimePolicy; policy != nil {
						_ = writeDesktopJSON(filepath.Join(plan.paths.Root, "hook-collection-status.json"), map[string]any{"version": 1, "client_id": plan.paths.Device, "queue": plan.paths.State, "policy_version": policy.Version, "observed_at_ms": strconv.FormatInt(now.UnixMilli(), 10), "enabled": false, "code": state.Code})
					}
				} else if done == nil && !state.Suspended && state.Attempts < logRetryLimit(plan.retry) && now.UnixMilli() >= state.NextRetryAt {
					state.Attempts++
					state.Active, state.Code, state.NextRetryAt = true, "aidr_desktop_starting", 0
					if persist() {
						childCtx, childCancel := context.WithCancel(ctx)
						cancel, done, started = childCancel, make(chan error, 1), now
						result := done
						go func() { result <- worker(childCtx) }()
					}
				}
				if done != nil {
					var telemetry struct {
						Updated string            `json:"updated_at"`
						State   hooks.StoreStatus `json:"state"`
					}
					readErr := readDesktopJSON(plan.paths.Status, &telemetry)
					stamp, parseErr := time.Parse(time.RFC3339Nano, telemetry.Updated)
					fresh := readErr == nil && parseErr == nil && !stamp.Before(started) && now.Sub(stamp) >= 0 && now.Sub(stamp) < 15*time.Second && telemetry.State.Device == plan.paths.Device && telemetry.State.ReceiverInstance != ""
					if fresh {
						state.Code = "aidr_desktop_running"
						resumeUntil = time.Time{}
						if healthySince.IsZero() {
							healthySince = now
						}
						if now.Sub(healthySince) >= time.Minute {
							state.Attempts = 1
						}
						if !plan.prefs.Enabled {
							state.Code = "aidr_desktop_draining"
						}
					} else if now.Before(resumeUntil) {
						state.Code = "aidr_desktop_health_rechecking"
					} else if now.Sub(started) > 15*time.Second {
						stop()
						state.failure("aidr_desktop_health_stale", plan.retry, now)
					}
				}
				persist()
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func requestHookRetry(paths desktopPaths) error {
	var state hookSupervision
	if readDesktopJSON(filepath.Join(paths.Root, "receiver-supervisor.json"), &state) != nil || !state.valid() || state.Code == "aidr_desktop_retry_state_invalid" {
		return errors.New("aidr_desktop_retry_state_invalid")
	}
	nonce, err := hooks.NewEventID()
	if err != nil {
		return err
	}
	return writeDesktopJSON(filepath.Join(paths.Root, "hook-retry-request.json"), logRetryRequest{Configuration: state.Configuration, Nonce: nonce, RequestedAt: time.Now().UTC().Format(time.RFC3339Nano)})
}

func hookReceiverSnapshot(ctx context.Context, home string) map[string]any {
	result := map[string]any{"code": "aidr_desktop_not_configured", "enabled": false, "attempts": 0, "managed_task": "0", "telemetry": nil, "receiver_diagnostic": nil, "retry_count": 0, "retry_mode": "fixed", "retry_suspended": false, "next_retry_seconds": nil, "policy": nil, "last_failure": nil, "last_failure_at_ms": nil}
	plan, err := automaticHookPlan(ctx, home)
	if err != nil {
		result["code"] = stableAIDRCode(err)
		return result
	}
	result["enabled"], result["managed_task"], result["policy"], result["retry_mode"] = plan.prefs.Enabled, strconv.FormatInt(plan.prefs.ManagedTask, 10), plan.prefs.RuntimePolicy, plan.retry.Mode
	result["code"] = "aidr_desktop_stopped"
	if !plan.required {
		result["code"] = "aidr_desktop_disabled"
	}
	var state hookSupervision
	if readDesktopJSON(filepath.Join(plan.paths.Root, "receiver-supervisor.json"), &state) == nil && state.valid() && state.Queue == plan.paths.State && state.Device == plan.paths.Device {
		result["code"], result["attempts"], result["retry_count"] = state.Code, state.Attempts, max(0, state.Attempts-1)
		result["retry_suspended"] = state.Suspended || (!state.Active && state.Attempts >= logRetryLimit(plan.retry))
		if state.LastFailure != "" {
			result["last_failure"], result["last_failure_at_ms"] = state.LastFailure, state.LastFailureAt
		}
		if state.NextRetryAt > time.Now().UnixMilli() && !state.Suspended {
			result["next_retry_seconds"] = (state.NextRetryAt - time.Now().UnixMilli() + 999) / 1000
		}
		if state.Active {
			result["code"] = "aidr_desktop_health_stale"
		}
	}
	binary, _ := os.Executable()
	diagnostic := hooks.DiagnoseReceiver(ctx, plan.paths.Socket, plan.paths.State, plan.cfg.Server, plan.paths.Device, binary)
	result["receiver_diagnostic"] = diagnostic
	if diagnostic.Ownership == "external_verified" && diagnostic.State != nil {
		result["code"] = "aidr_desktop_shared_receiver"
		result["telemetry"] = map[string]any{"state": diagnostic.State, "shared_observation": true}
		if state.Active && state.PID == diagnostic.PID && state.Configuration == plan.identity() {
			diagnostic.Ownership = "owned"
			result["receiver_diagnostic"], result["code"] = diagnostic, "aidr_desktop_running"
			if !plan.prefs.Enabled {
				result["code"] = "aidr_desktop_draining"
			}
			var telemetry map[string]any
			if readDesktopJSON(plan.paths.Status, &telemetry) == nil {
				stamp, _ := time.Parse(time.RFC3339Nano, fmtString(telemetry["updated_at"]))
				st, _ := telemetry["state"].(map[string]any)
				if time.Since(stamp) >= 0 && time.Since(stamp) < 15*time.Second && st["receiver_instance"] == diagnostic.State.ReceiverInstance {
					result["telemetry"] = telemetry
				}
			}
		}
	}
	return result
}

func fmtString(v any) string { s, _ := v.(string); return s }
