package upload

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
)

// HookControlSync processes one bounded page per cycle, independently of the
// event outbox. Each completed sweep restarts at the beginning so that revocations
// and new revisions of already-seen grants are fetched too.
type HookControlSync struct {
	after string
}

func (c *Client) HookControlKey(ctx context.Context) ([]byte, error) {
	data, result := c.post(ctx, "hook-control/bootstrap", []byte(`{}`), nil)
	if result.Code != "" {
		return nil, errors.New(result.Code)
	}
	var value struct {
		Key string `json:"public_key"`
	}
	if decode(data, &value) != nil {
		return nil, errors.New("aidr_hook_control_key_invalid")
	}
	key, err := base64.StdEncoding.DecodeString(value.Key)
	if err != nil || len(key) != 65 {
		return nil, errors.New("aidr_hook_control_key_invalid")
	}
	return key, nil
}

func (c *Client) SendAttemptReport(ctx context.Context, s *hooks.Store) (string, error) {
	if err := c.bindHooks(s); err != nil {
		return "", err
	}
	f, err := s.PrepareAttemptReport(ctx)
	if err != nil || f == nil {
		return "", err
	}
	data, result := c.post(ctx, "hook-attempt-reports", f.Payload, nil)
	if result.Code != "" {
		return "aidr_hook_attempt_report_retry", nil
	}
	var ack struct {
		Schema  int    `json:"schema_version"`
		Device  string `json:"client_id"`
		Stream  string `json:"stream_id"`
		Event   string `json:"event_id"`
		Digest  string `json:"digest"`
		Durable bool   `json:"durable"`
	}
	if decode(data, &ack) != nil || ack.Schema != 1 || ack.Event != f.Event || ack.Digest != f.Digest {
		return "aidr_hook_attempt_ack_invalid", nil
	}
	if err = s.AcknowledgeAttemptReport(ctx, ack.Device, ack.Stream, ack.Event, ack.Digest, ack.Durable); err != nil {
		return "aidr_hook_attempt_ack_invalid", nil
	}
	return "aidr_hook_attempt_reported", nil
}

func (c *Client) SendHookApproval(ctx context.Context, s *hooks.Store) (string, error) {
	if err := c.bindHooks(s); err != nil {
		return "", err
	}
	request, err := s.PendingApproval(ctx, time.Now())
	if err != nil || request == nil {
		return "", err
	}
	raw, _ := json.Marshal(request)
	data, result := c.post(ctx, "hook-approvals", raw, nil)
	if result.Code != "" {
		return "aidr_hook_approval_retry", nil
	}
	var reply struct {
		ID             string          `json:"id"`
		Revision       string          `json:"revision"`
		State          string          `json:"state"`
		RecordedState  string          `json:"recorded_state"`
		Scope          hooks.ToolScope `json:"scope"`
		Created        string          `json:"created_at"`
		Expires        string          `json:"expires_at"`
		DecidedBy      *string         `json:"decided_by"`
		Evidence       string          `json:"evidence_type"`
		ExecutionPoint string          `json:"execution_point"`
	}
	if decode(data, &reply) != nil || reply.Evidence != "agent_hook" || reply.ExecutionPoint != "plugin_pre_tool" {
		return "aidr_hook_approval_response_invalid", nil
	}
	if err = s.BindApproval(ctx, request.Event, reply.ID, reply.Scope); err != nil {
		return "aidr_hook_approval_response_invalid", nil
	}
	return "aidr_hook_approval_submitted", nil
}

func (p *HookControlSync) Refresh(ctx context.Context, c *Client, s *hooks.Store) (string, error) {
	if err := c.bindHooks(s); err != nil {
		return "", err
	}
	key := s.ControlKey()
	if len(key) == 0 {
		return "aidr_hook_audit_only", nil
	}
	state, err := s.Status(ctx)
	if err != nil {
		return "", err
	}
	raw, _ := json.Marshal(map[string]string{"stream_id": state.Stream, "receiver_instance": state.ReceiverInstance, "after": p.after})
	data, result := c.post(ctx, "hook-control/snapshot", raw, nil)
	if result.Code != "" {
		return "aidr_hook_control_cached", nil
	}
	var page struct {
		Policy json.RawMessage   `json:"policy"`
		Grants []json.RawMessage `json:"grants"`
		More   bool              `json:"more_grants"`
		After  string            `json:"next_after"`
	}
	if decode(data, &page) != nil || page.Grants == nil || len(page.Grants) > 100 {
		return "aidr_hook_control_response_invalid", nil
	}
	if len(page.Grants) > 0 {
		id, err := hex.DecodeString(page.After)
		if err != nil || len(id) != 16 || page.After <= p.after {
			return "aidr_hook_control_cursor_invalid", nil
		}
	} else if page.More || page.After != p.after {
		return "aidr_hook_control_cursor_invalid", nil
	}
	if len(page.Policy) == 0 || string(page.Policy) == "null" {
		return "aidr_hook_policy_missing", nil
	}
	if err := s.ApplyToolPolicy(ctx, page.Policy, time.Now()); err != nil {
		return "aidr_hook_control_policy_rejected", nil
	}
	for _, envelope := range page.Grants {
		if err := s.ApplyGrant(ctx, envelope, key, time.Now()); err != nil {
			// Do not advance across a rejected page. Valid earlier entries are
			// idempotent on retry; no unverified authority reaches the store.
			return "aidr_hook_control_grant_rejected", nil
		}
	}
	p.after = ""
	if page.More {
		p.after = page.After
		return "aidr_hook_control_scanning", nil
	}
	return "aidr_hook_control_synced", nil
}
