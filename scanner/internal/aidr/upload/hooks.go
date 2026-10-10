package upload

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/hooks"
)

func (c *Client) bindHooks(s *hooks.Store) error {
	platform, device := s.Destination()
	if platform != c.base || device != c.clientID {
		return errors.New("aidr_hook_destination_mismatch")
	}
	return nil
}

func (c *Client) RefreshHookPolicy(ctx context.Context, s *hooks.Store) (string, error) {
	if err := c.bindHooks(s); err != nil {
		return "", err
	}
	state, err := s.Status(ctx)
	if err != nil {
		return "", err
	}
	raw, _ := json.Marshal(map[string]string{"stream_id": state.Stream, "last_sequence": state.LastSequence, "applied_receipt": state.Policy.Receipt, "applied_after": state.AppliedAfter})
	data, result := c.post(ctx, "audit-policy", raw, map[string]string{"X-AIDR-Policy-Schema": "2", "X-AIDR-Audit-Lifecycle": "1", "X-AIDR-Message-Capture": "1", "X-AIDR-Content-Options": "1"})
	if result.Code != "" {
		return "aidr_policy_cached", nil
	}
	var policy agentlog.AuditPolicy
	if decode(data, &policy) != nil || !policy.Valid() || policy.Version == "0" {
		return "aidr_policy_response_invalid", nil
	}
	if err = s.SetPolicy(ctx, policy); err != nil {
		return "", err
	}
	return "aidr_policy_applied", nil
}

func (c *Client) SendHooks(ctx context.Context, s *hooks.Store) (Result, error) {
	if err := c.bindHooks(s); err != nil {
		return Result{}, err
	}
	b, err := s.Prepare(ctx)
	if err != nil || b == nil {
		return Result{}, err
	}
	data, result := c.post(ctx, "hooks:batch", b.Payload, nil)
	if result.Code != "" {
		return result, nil
	}
	var ack struct {
		Schema  int    `json:"schema_version"`
		Device  string `json:"client_id"`
		Stream  string `json:"stream_id"`
		Digest  string `json:"digest"`
		Count   int    `json:"accepted"`
		Durable bool   `json:"durable"`
	}
	state, err := s.Status(ctx)
	if err != nil {
		return result, err
	}
	if decode(data, &ack) != nil || ack.Schema != 1 || ack.Device != state.Device || ack.Stream != state.Stream || ack.Digest != b.Digest || ack.Count != b.Count || !ack.Durable {
		return Result{Code: "aidr_hook_ack_invalid", Retryable: true}, nil
	}
	err = s.Acknowledge(ctx, ack.Device, ack.Stream, ack.Digest, ack.Count, ack.Durable)
	return Result{Uploaded: err == nil}, err
}

// ReportHookRuntime sends only bounded current telemetry; it does not consume
// audit records or modify a frozen batch.
func (c *Client) ReportHookRuntime(ctx context.Context, s *hooks.Store, sequence uint64) (string, error) {
	if err := c.bindHooks(s); err != nil {
		return "", err
	}
	state, err := s.Status(ctx)
	if err != nil {
		return "", err
	}
	seq := strconv.FormatUint(sequence, 10)
	payload := map[string]any{"schema_version": 1, "stream_id": state.Stream,
		"command_rules_schema": 1,
		"receiver_instance":    state.ReceiverInstance, "report_sequence": seq,
		"control_mode": state.ControlMode, "control_revision": state.ControlRevision,
		"control_code": state.ControlCode, "queued_records": state.Queued,
		"upload_code": c.hookUploadCode, "next_upload_at": utcTime(c.hookNextUpload), "last_event_ack_at": state.LastAcknowledgedAt}
	if state.Policy.Capture != nil {
		payload["audit_policy"] = state.Policy
		payload["content_schema"] = 2
	}
	if state.Policy.Lifecycle != nil {
		payload["lifecycle_schema"] = 1
		payload["audit_suppressed_recent"] = state.Suppressed
	}
	raw, _ := json.Marshal(payload)
	data, result := c.post(ctx, "hook-runtime", raw, nil)
	if result.Code != "" {
		return "aidr_hook_runtime_report_failed", nil
	}
	var ack struct {
		Code     string `json:"code"`
		Receiver string `json:"receiver_instance"`
		Sequence string `json:"report_sequence"`
	}
	if decode(data, &ack) != nil || ack.Code != "aidr_hook_runtime_received" || ack.Receiver != state.ReceiverInstance || ack.Sequence != seq {
		return "aidr_hook_runtime_ack_invalid", nil
	}
	return "aidr_hook_runtime_received", nil
}

// RunHooks refreshes policy and telemetry about every 30 seconds. IPC collection
// runs independently of network latency; reports never imply tool execution.
func (c *Client) RunHooks(ctx context.Context, s *hooks.Store, observe func(string, string, string), runtimeObservers ...func(string)) error {
	if err := c.bindHooks(s); err != nil {
		return err
	}
	var nextPolicy time.Time
	var nextRuntime time.Time
	var nextUpload time.Time
	failures := 0
	uploadCode := ""
	var runtimeSequence uint64
	policyCode := "aidr_policy_cached"
	control := HookControlSync{}
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		if ctx.Err() != nil {
			return nil
		}
		if !time.Now().Before(nextPolicy) {
			var err error
			policyCode, err = c.RefreshHookPolicy(ctx, s)
			if err != nil {
				return err
			}
			nextPolicy = time.Now().Add(30 * time.Second)
		}
		if !time.Now().Before(nextUpload) {
			result, err := c.SendHooks(ctx, s)
			if err != nil {
				return err
			}
			uploadCode = result.Code
			if result.Code != "" {
				if !result.Retryable {
					return errors.New(result.Code)
				}
				nextUpload = time.Now().Add(RetryDelay(failures))
				failures = min(failures+1, 6)
			} else {
				nextUpload = time.Time{}
				failures = 0
			}
			c.hookUploadCode, c.hookNextUpload = uploadCode, nextUpload
		}
		approvalCode, err := c.SendHookApproval(ctx, s)
		if err != nil {
			return err
		}
		controlCode, err := control.Refresh(ctx, c, s)
		if err != nil {
			return err
		}
		reportCode, err := c.SendAttemptReport(ctx, s)
		if err != nil {
			return err
		}
		if !time.Now().Before(nextRuntime) {
			runtimeSequence++
			runtimeCode, runtimeErr := c.ReportHookRuntime(ctx, s, runtimeSequence)
			if runtimeErr != nil {
				return runtimeErr
			}
			for _, observer := range runtimeObservers {
				observer(runtimeCode)
			}
			if runtimeCode != "aidr_hook_runtime_received" && (reportCode == "" || reportCode == "aidr_hook_attempt_reported") {
				reportCode = runtimeCode
			}
			nextRuntime = time.Now().Add(30 * time.Second)
		}
		if observe != nil {
			if reportCode != "" && reportCode != "aidr_hook_attempt_reported" {
				controlCode = reportCode
			}
			if approvalCode != "" && approvalCode != "aidr_hook_approval_submitted" {
				controlCode = approvalCode
			}
			observe(policyCode, uploadCode, controlCode)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func utcTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.UTC().Format(time.RFC3339Nano)
}
