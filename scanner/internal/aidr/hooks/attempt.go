package hooks

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"
)

type ApprovalSubmission struct {
	Stream   string `json:"stream_id"`
	Event    string `json:"event_id"`
	Receiver string `json:"receiver_instance"`
	Revision string `json:"policy_revision"`
	Rule     string `json:"rule_id"`
}

// BeginApproval stores only the exact scope derived from persisted evidence.
// Waiting happens in the plugin process, never while holding a socket or lock.
func (s *Store) BeginApproval(ctx context.Context, record Record, now time.Time) (ToolDecision, error) {
	if err := s.lockContext(ctx); err != nil {
		return ToolDecision{}, err
	}
	defer s.mu.Unlock()
	deny := ToolDecision{Decision: "deny", Code: "aidr_hook_scope_unverified", Matched: []string{}}
	if s.controlPolicy == nil || len(s.controlKey) == 0 {
		return deny, nil
	}
	d := s.controlPolicy.Evaluate(record.Event, now)
	if d.Decision != "ask" {
		return d, nil
	}
	scope, err := s.ScopeFor(record, d.Rule, d.Revision)
	if err != nil {
		return deny, nil
	}
	raw, _ := json.Marshal(scope)
	var oldScope, state, reason string
	err = s.db.QueryRowContext(ctx, `SELECT scope,state,code FROM hook_attempts WHERE event_id=?`, record.EventID).Scan(&oldScope, &state, &reason)
	if err == nil {
		if oldScope != string(raw) {
			return deny, nil
		}
		if state != "pending" {
			d.Decision = "deny"
			d.Code = reason
			return d, nil
		}
		d.Code = "aidr_hook_approval_pending"
		return d, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return deny, err
	}
	if _, err = s.db.ExecContext(ctx, `DELETE FROM hook_attempts WHERE expires_at<? AND state!='pending' AND event_id IN (SELECT event_id FROM hook_attempt_reports WHERE acked=1)`, now.Add(-48*time.Hour).Unix()); err != nil {
		return deny, err
	}
	if _, err = s.db.ExecContext(ctx, `DELETE FROM hook_attempt_reports WHERE acked=1 AND event_id NOT IN (SELECT event_id FROM hook_attempts)`); err != nil {
		return deny, err
	}
	var count int
	if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM hook_attempts`).Scan(&count); err != nil {
		return deny, err
	}
	if count >= 10000 {
		return deny, code("aidr_hook_attempt_capacity")
	}
	expires := now.Add(45 * time.Second).Unix()
	_, err = s.db.ExecContext(ctx, `INSERT INTO hook_attempts(event_id,receiver,user_scope,scope,expires_at) VALUES(?,?,?,?,?)`, record.EventID, s.instance, record.User, string(raw), expires)
	d.Code = "aidr_hook_approval_pending"
	return d, err
}

// PollApproval atomically consumes a grant and records the local delivery.
// A lost allow response cannot be replayed into a second execution permission.
func (s *Store) PollApproval(ctx context.Context, id, user string, cancel bool, now time.Time) (ToolDecision, error) {
	if err := s.lockContext(ctx); err != nil {
		return ToolDecision{}, err
	}
	defer s.mu.Unlock()
	d := ToolDecision{Decision: "deny", Code: "aidr_hook_attempt_missing", Matched: []string{}}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return d, err
	}
	defer tx.Rollback()
	var raw, receiver, state, reason, grantID string
	var expires int64
	err = tx.QueryRowContext(ctx, `SELECT scope,receiver,state,code,approval_id,expires_at FROM hook_attempts WHERE event_id=? AND user_scope=?`, id, user).Scan(&raw, &receiver, &state, &reason, &grantID, &expires)
	if errors.Is(err, sql.ErrNoRows) {
		return d, nil
	}
	if err != nil {
		return d, err
	}
	if receiver != s.instance {
		d.Code = "aidr_hook_receiver_restarted"
		return d, nil
	}
	if state != "pending" {
		d.Code = reason
		return d, nil
	}
	var scope ToolScope
	if decodeStrict([]byte(raw), &scope) != nil {
		return d, code("aidr_hook_scope_unverified")
	}
	d.Revision = scope.PolicyRevision
	d.Rule = scope.Rule
	finish := func(reason string, allow bool) (ToolDecision, error) {
		d.Code = reason
		next := "denied"
		if allow {
			d.Decision = "allow"
			next = "consumed"
		}
		_, e := tx.ExecContext(ctx, `UPDATE hook_attempts SET state=?,code=? WHERE event_id=?`, next, reason, id)
		if e == nil {
			e = tx.Commit()
		}
		return d, e
	}
	if cancel {
		return finish("aidr_hook_approval_cancelled", false)
	}
	if expires <= now.Unix() {
		return finish("aidr_hook_approval_timeout", false)
	}
	if s.controlPolicy == nil || s.controlPolicy.Revision != scope.PolicyRevision {
		return finish("aidr_hook_policy_changed", false)
	}
	// BeginApproval persisted the evaluated rule and exact input digest. The
	// signed policy is immutable within a revision; grants bind that same scope.
	if grantID != "" {
		err = consumeGrantTx(ctx, tx, grantID, scope, now)
		if err == nil {
			return finish("aidr_hook_approval_consumed", true)
		}
		if err.Error() != "aidr_hook_grant_missing" {
			switch err.Error() {
			case "aidr_hook_grant_deny", "aidr_hook_grant_revoke", "aidr_hook_grant_expired", "aidr_hook_grant_consumed", "aidr_hook_grant_scope_mismatch":
				return finish(err.Error(), false)
			default:
				return d, err
			}
		}
	}
	d.Decision = "ask"
	d.Code = "aidr_hook_approval_pending"
	return d, nil
}

// PendingApprovals rotates retries by last_try so unavailable evidence for one
// attempt cannot starve later attempts. At most one network request per cycle.
func (s *Store) PendingApproval(ctx context.Context, now time.Time) (*ApprovalSubmission, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, err := s.db.ExecContext(ctx, `UPDATE hook_attempts SET state='denied',code='aidr_hook_approval_timeout' WHERE state='pending' AND expires_at<=?`, now.Unix()); err != nil {
		return nil, err
	}
	var raw string
	err := s.db.QueryRowContext(ctx, `SELECT scope FROM hook_attempts WHERE receiver=? AND state='pending' AND approval_id='' ORDER BY last_try,event_id LIMIT 1`, s.instance).Scan(&raw)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var scope ToolScope
	if decodeStrict([]byte(raw), &scope) != nil {
		return nil, code("aidr_hook_scope_unverified")
	}
	if _, err = s.db.ExecContext(ctx, `UPDATE hook_attempts SET last_try=? WHERE event_id=?`, now.UnixNano(), scope.Attempt); err != nil {
		return nil, err
	}
	return &ApprovalSubmission{scope.Stream, scope.Attempt, scope.Receiver, scope.PolicyRevision, scope.Rule}, nil
}

func (s *Store) BindApproval(ctx context.Context, event, id string, scope ToolScope) error {
	if !eventID.MatchString(id) {
		return code("aidr_hook_approval_response_invalid")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	var raw, old string
	if err := s.db.QueryRowContext(ctx, `SELECT scope,approval_id FROM hook_attempts WHERE event_id=? AND receiver=?`, event, s.instance).Scan(&raw, &old); err != nil {
		return err
	}
	var expected ToolScope
	if decodeStrict([]byte(raw), &expected) != nil || expected != scope || (old != "" && old != id) {
		return code("aidr_hook_approval_response_invalid")
	}
	_, err := s.db.ExecContext(ctx, `UPDATE hook_attempts SET approval_id=? WHERE event_id=?`, id, event)
	return err
}
