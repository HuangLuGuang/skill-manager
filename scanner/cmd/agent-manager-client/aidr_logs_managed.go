package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"sync/atomic"
	"time"

	"skill-manager/scanner/internal/aidr/localstore"
	"skill-manager/scanner/internal/aidr/upload"
	"skill-manager/scanner/internal/managedclient"
)

type logRunPlan struct {
	server, device, token, state, version string
	roots                                 []upload.Root
	currentVersion                        func() string
	enabled                               bool
	retry                                 managedclient.ReceiverRetryPolicy
}

func automaticLogPlan(home string, policy managedclient.Policy) (logRunPlan, error) {
	var p logRunPlan
	classification := policy.Classification
	if classification == nil || !classification.RuntimeGovernanceConfigured || classification.RuntimeGovernance == nil {
		return p, nil
	}
	target := classification.RuntimeGovernance
	if !target.Valid() || !validRuntimePolicyVersion(classification.RuntimeGovernanceVersion) {
		return p, errors.New("aidr_log_policy_invalid")
	}
	// Explicit channels distinguish upgraded policy from an old Hook-only target.
	if target.Channels == nil {
		return p, nil
	}
	cfg, paths, err := desktopBinding(home)
	if err != nil {
		return p, err
	}
	p = logRunPlan{server: cfg.Server, device: paths.Device, token: cfg.Token, version: classification.RuntimeGovernanceVersion, enabled: target.CollectLogs(), retry: target.Retry}
	p.state = filepath.Join(paths.Root, "log-queues", filepath.Base(paths.State))
	prefs, err := loadDesktopPreferences(home)
	if err != nil {
		return logRunPlan{}, err
	}
	for _, agent := range []string{"claude", "codex"} {
		base := filepath.Join(home, "."+agent)
		if configured := prefs.Hosts[agent].Home; configured != "" {
			base = configured
		}
		if !filepath.IsAbs(base) {
			return logRunPlan{}, errors.New("aidr_log_source_invalid")
		}
		sub := "sessions"
		if agent == "claude" {
			sub = "projects"
		}
		p.roots = append(p.roots, upload.Root{Agent: agent, Path: filepath.Join(base, sub)})
	}
	return p, nil
}

func (p logRunPlan) identity() string {
	// Private local comparison only. Never transmitted or logged.
	text := p.server + "\x00" + p.device + "\x00" + p.token
	for _, root := range p.roots {
		text += "\x00" + root.Agent + "\x00" + root.Path
	}
	s := sha256.Sum256([]byte(text))
	return hex.EncodeToString(s[:])
}

type logSupervision struct {
	Version       int    `json:"version"`
	Configuration string `json:"configuration"`
	PolicyVersion string `json:"policy_version"`
	Attempts      int    `json:"attempts"`
	Code          string `json:"code"`
	Suspended     bool   `json:"suspended"`
	NextRetryAt   string `json:"next_retry_at,omitempty"`
	UpdatedAt     string `json:"updated_at"`
	RetryRequest  string `json:"retry_request,omitempty"`
}

func (s logSupervision) valid() bool {
	_, err := hex.DecodeString(s.Configuration)
	return err == nil && s.Version == 1 && len(s.Configuration) == 64 && s.Attempts >= 0 && s.Attempts <= 21 && validRuntimeCode(s.Code) && validRuntimePolicyVersion(s.PolicyVersion)
}

func logRetryLimit(p managedclient.ReceiverRetryPolicy) int {
	if p.Mode == "none" {
		return 1
	}
	if p.Mode == "continuous" {
		return 21
	}
	return p.Retries + 1
}

// The existing daemon owns this goroutine. A writer conflict is never taken over,
// and cancellation is joined before switching identity or exiting the daemon.
func runAutomaticLogs(ctx context.Context, home string, policy func() managedclient.Policy) {
	manageAutomaticLogs(ctx, home, policy, 2*time.Second, runManagedLogWorker)
}

type managedLogWorker func(context.Context, string, logRunPlan, *atomic.Bool) error

func manageAutomaticLogs(ctx context.Context, home string, policy func() managedclient.Policy, interval time.Duration, worker managedLogWorker) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	var current logRunPlan
	var state logSupervision
	var enabled atomic.Bool
	var reportedVersion atomic.Value
	reportedVersion.Store("")
	var cancel context.CancelFunc
	var done chan error
	var next time.Time
	stop := func() {
		if cancel != nil {
			cancel()
			<-done
			cancel = nil
			done = nil
		}
	}
	persist := func() {
		if current.state == "" {
			return
		}
		state.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
		if err := writeDesktopJSON(filepath.Join(current.state, "log-supervisor.json"), state); err != nil {
			stop()
			state.Code = "aidr_log_status_unwritable"
			state.Suspended = true
		}
	}
	defer func() {
		active := done != nil
		stop()
		if current.state != "" {
			if active && !state.Suspended {
				state.Attempts = max(0, state.Attempts-1)
				state.Code = "aidr_log_stopped"
			}
			persist()
		}
	}()
	for ctx.Err() == nil {
		plan, err := automaticLogPlan(home, policy())
		if err != nil {
			stop()
			enabled.Store(false)
			if current.state != "" {
				state.Code = stableAIDRCode(err)
				state.Suspended = true
				persist()
			}
		} else if plan.state == "" {
			stop()
			enabled.Store(false)
		} else {
			changed := plan.identity() != current.identity()
			if changed {
				stop()
				current = plan
				state = logSupervision{Version: 1, Configuration: plan.identity(), PolicyVersion: plan.version, Code: "aidr_log_starting"}
				next = time.Time{}
				var saved logSupervision
				path := filepath.Join(plan.state, "log-supervisor.json")
				if _, e := os.Lstat(path); e == nil {
					if readDesktopJSON(path, &saved) != nil || !saved.valid() {
						state.Code = "aidr_log_supervision_invalid"
						state.Suspended = true
					} else if saved.Configuration == state.Configuration && saved.PolicyVersion == state.PolicyVersion {
						state = saved
						if saved.NextRetryAt != "" {
							var parseErr error
							next, parseErr = time.Parse(time.RFC3339Nano, saved.NextRetryAt)
							if parseErr != nil {
								state.Code = "aidr_log_supervision_invalid"
								state.Suspended = true
							}
						}
					}
				} else if !os.IsNotExist(e) {
					state.Code = "aidr_log_supervision_invalid"
					state.Suspended = true
				}
			}
			if !changed && (plan.version != current.version || plan.retry != current.retry) {
				// Revisions with identical running inputs update status in place.
				if state.Suspended && state.Code != "aidr_store_busy" && state.Code != "aidr_log_supervision_invalid" {
					state.Attempts = 0
					state.Suspended = false
					next = time.Time{}
				}
				state.PolicyVersion = plan.version
				current.version, current.retry = plan.version, plan.retry
				persist()
			}
			if done == nil && state.Suspended && state.Code != "aidr_log_supervision_invalid" {
				var request logRetryRequest
				if readDesktopJSON(filepath.Join(plan.state, "log-retry-request.json"), &request) == nil && request.valid(state, time.Now()) && request.Nonce != state.RetryRequest {
					state.RetryRequest = request.Nonce
					state.Attempts = 0
					state.Suspended = false
					state.Code = "aidr_log_starting"
					state.NextRetryAt = ""
					next = time.Time{}
					persist()
				}
			}
			reportedVersion.Store(plan.version)
			current.enabled = plan.enabled
			enabled.Store(plan.enabled)
			if done != nil {
				select {
				case runErr := <-done:
					cancel()
					cancel = nil
					done = nil
					if ctx.Err() != nil {
						state.Attempts = max(0, state.Attempts-1)
						state.Code = "aidr_log_stopped"
						return
					}
					state.Code = "aidr_log_worker_failed"
					if runErr != nil {
						state.Code = stableAIDRCode(runErr)
					}
					state.Suspended = logPermanentFailure(state.Code) || state.Attempts >= logRetryLimit(plan.retry)
					next = time.Now().Add(min(time.Duration(1<<min(state.Attempts, 10))*time.Second, time.Duration(plan.retry.MaxIntervalSeconds)*time.Second))
					state.NextRetryAt = next.UTC().Format(time.RFC3339Nano)
					persist()
				default:
				}
			}
			// Disabled channels drain only an existing queue, never create a reader
			// or a new state directory merely because an OFF policy was received.
			_, existing := os.Lstat(filepath.Join(plan.state, "state.db"))
			if done == nil && !state.Suspended && !time.Now().Before(next) && (plan.enabled || existing == nil) {
				if state.Attempts >= logRetryLimit(plan.retry) {
					state.Suspended = true
					persist()
				} else {
					state.Attempts++
					state.Code = "aidr_log_starting"
					state.NextRetryAt = ""
					persist()
					if !state.Suspended {
						var runCtx context.Context
						runCtx, cancel = context.WithCancel(ctx)
						done = make(chan error, 1)
						finished := done
						captured := plan
						captured.currentVersion = func() string { return reportedVersion.Load().(string) }
						go func() { finished <- worker(runCtx, home, captured, &enabled) }()
					}
				}
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func logPermanentFailure(code string) bool {
	return code == "aidr_store_busy" || code == "aidr_upload_auth_rejected" || code == "aidr_upload_destination_changed" || code == "aidr_store_path_invalid" || code == "aidr_store_invalid"
}

func runManagedLogWorker(ctx context.Context, home string, plan logRunPlan, enabled *atomic.Bool) (resultErr error) {
	s, err := localstore.Open(plan.state, localstore.DefaultLimits())
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, s.Close()) }()
	c, err := upload.New(upload.Options{Server: plan.server, ClientID: plan.device, Token: plan.token})
	if err != nil {
		return err
	}
	defer c.Close()
	var lastWrite time.Time
	return upload.Run(ctx, s, c, upload.WorkerOptions{
		Roots: plan.roots,
		Since: time.Now().Add(-24 * time.Hour), Interval: 2 * time.Second, HeartbeatInterval: 30 * time.Second, DiscoveryInterval: 30 * time.Second,
		IntakeEnabled: enabled.Load,
		IntakeVersion: plan.currentVersion,
		StatusObserver: func(status localstore.Status) error {
			if time.Since(lastWrite) < 5*time.Second {
				return nil
			}
			code := "aidr_log_running"
			if status.RuntimeCollectionEnabled != nil && !*status.RuntimeCollectionEnabled {
				code = "aidr_log_draining"
			}
			if status.IntakeCode != "" || status.CapacityCode != "" {
				code = "aidr_log_intake_degraded"
			}
			if err := writeDesktopJSON(filepath.Join(plan.state, "log-status.json"), map[string]any{"version": 1, "client_id": plan.device, "policy_version": status.RuntimePolicyVersion, "enabled": status.RuntimeCollectionEnabled, "code": code, "reported_at": time.Now().UTC().Format(time.RFC3339Nano), "state": status}); err != nil {
				return errors.New("aidr_log_status_unwritable")
			}
			lastWrite = time.Now()
			return nil
		},
	})
}

// A local retry requests one new bounded supervision cycle. It cannot change
// the destination, rewrite queue data or seize a store owned by another process.
type logRetryRequest struct {
	Configuration string `json:"configuration"`
	PolicyVersion string `json:"policy_version"`
	Nonce         string `json:"nonce"`
	RequestedAt   string `json:"requested_at"`
}

func (r logRetryRequest) valid(s logSupervision, now time.Time) bool {
	b, err := hex.DecodeString(r.Nonce)
	stamp, timeErr := time.Parse(time.RFC3339Nano, r.RequestedAt)
	age := now.Sub(stamp)
	return err == nil && len(b) == 16 && timeErr == nil && age >= -5*time.Second && age < 5*time.Minute && r.Configuration == s.Configuration && r.PolicyVersion == s.PolicyVersion
}
func requestLogRetry(paths desktopPaths) error {
	root := filepath.Join(paths.Root, "log-queues", filepath.Base(paths.State))
	var state logSupervision
	if readDesktopJSON(filepath.Join(root, "log-supervisor.json"), &state) != nil || !state.valid() {
		return errors.New("aidr_log_supervision_invalid")
	}
	if !state.Suspended {
		return errors.New("aidr_log_retry_not_needed")
	}
	if state.Code == "aidr_log_supervision_invalid" {
		return errors.New(state.Code)
	}
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		return errors.New("aidr_log_retry_failed")
	}
	request := logRetryRequest{Configuration: state.Configuration, PolicyVersion: state.PolicyVersion, Nonce: hex.EncodeToString(nonce), RequestedAt: time.Now().UTC().Format(time.RFC3339Nano)}
	if writeDesktopJSON(filepath.Join(root, "log-retry-request.json"), request) != nil {
		return errors.New("aidr_log_retry_failed")
	}
	return nil
}
