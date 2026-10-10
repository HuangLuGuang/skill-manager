package upload

import (
	"context"
	"errors"
	"time"

	"skill-manager/scanner/internal/aidr/enforcement"
)

type RuntimeDrainResult struct {
	Drained         bool   `json:"uploads_drained"`
	Pending         *int   `json:"pending_uploads"`
	Attempts        int    `json:"upload_attempts"`
	Batches         int    `json:"uploaded_batches"`
	BudgetExhausted bool   `json:"upload_budget_exhausted"`
	Code            string `json:"upload_code,omitempty"`
}

// DrainRuntime uploads existing records after the caller has stopped intake.
// It neither starts a monitor nor reads a control policy. The store retains its
// single-writer lock, destination binding, frozen bytes and strict ACK contract.
// A caller may resume another bounded drain after an offline interval/restart.
func (c *Client) DrainRuntime(ctx context.Context, s *enforcement.Store, maxAttempts int) (report RuntimeDrainResult, err error) {
	if maxAttempts < 1 || maxAttempts > 1024 {
		return report, errors.New("aidr_enforcement_config_invalid")
	}
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			report.Pending = nil // No fresh count is available within this budget.
			report.BudgetExhausted = true
			return report, nil
		}
		pending, e := s.Pending(ctx)
		if e != nil {
			if ctx.Err() != nil {
				report.Pending = nil
				report.BudgetExhausted = true
				return report, nil
			}
			return report, e
		}
		report.Pending = &pending
		if pending == 0 {
			report.Drained = true
			return report, nil
		}
		if report.Attempts >= maxAttempts {
			report.BudgetExhausted = true
			return report, nil
		}
		report.Attempts++
		result, e := c.SendRuntime(ctx, s)
		if e != nil {
			if ctx.Err() != nil {
				report.Pending = nil
				report.BudgetExhausted = true
				return report, nil
			}
			return report, e
		}
		report.Code = result.Code
		if result.Uploaded {
			report.Batches++
		}
		// Status persistence cannot authorize an ACK or modify a frozen batch.
		statusCode := result.Code
		if statusCode == "aidr_enforcement_ack_invalid" {
			// The shared store's upload status uses the transport vocabulary.
			// Preserve the runtime-specific failure in the returned report.
			statusCode = "aidr_upload_ack_invalid"
		}
		if e = s.Guard.SetUploadCode(ctx, statusCode); e != nil {
			if ctx.Err() != nil {
				report.Pending = nil
				report.BudgetExhausted = true
				return report, nil
			}
			return report, e
		}
		if result.Uploaded {
			backoff = time.Second
			continue
		}
		if !result.Retryable {
			return report, nil
		}
		if report.Attempts >= maxAttempts {
			report.BudgetExhausted = true
			return report, nil
		}
		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			timer.Stop()
			report.Pending = nil
			report.BudgetExhausted = true
			return report, nil
		case <-timer.C:
		}
		backoff = min(backoff*2, 30*time.Second)
	}
}
