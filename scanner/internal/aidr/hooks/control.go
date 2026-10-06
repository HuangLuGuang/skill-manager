package hooks

import (
	"bytes"
	"context"
	"crypto/elliptic"
	"database/sql"
	"errors"
	"regexp"
	"sort"
	"time"

	"skill-manager/scanner/internal/aidr/enforcement"
)

type ToolRule struct {
	ID       string `json:"id"`
	Agent    string `json:"agent"`
	Tool     string `json:"tool"`
	Decision string `json:"decision"`
}
type ToolPolicy struct {
	Schema   int        `json:"schema"`
	Domain   string     `json:"domain"`
	Device   string     `json:"device"`
	Revision string     `json:"revision"`
	Issued   string     `json:"issued_at"`
	Expires  string     `json:"expires_at"`
	Default  string     `json:"default_action"`
	Rules    []ToolRule `json:"rules"`
}
type ToolDecision struct {
	Decision string   `json:"decision"`
	Rule     string   `json:"rule_id"`
	Matched  []string `json:"matched_rule_ids"`
	Revision string   `json:"policy_revision"`
	Code     string   `json:"code"`
}

func decisionValid(s string) bool { return s == "allow" || s == "deny" || s == "ask" }

var toolRuleID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

func verifyToolPolicy(envelope, key []byte, device string, now time.Time) (ToolPolicy, []byte, error) {
	var p ToolPolicy
	raw, err := enforcement.VerifyPayload(envelope, key)
	if err != nil {
		return p, nil, code("aidr_hook_policy_signature_invalid")
	}
	if decodeStrict(raw, &p) != nil {
		return p, nil, code("aidr_hook_policy_invalid")
	}
	_, r := positiveDecimal(p.Revision)
	issued, i := positiveDecimal(p.Issued)
	expires, e := positiveDecimal(p.Expires)
	if p.Schema != 1 || p.Domain != "aidr.tool-policy/1" || p.Device != device || !r || !i || !e || issued > now.Unix()+30 || expires <= issued || expires-issued > 86400 || !decisionValid(p.Default) || p.Rules == nil || len(p.Rules) > 128 {
		return p, nil, code("aidr_hook_policy_invalid")
	}
	ids := map[string]bool{}
	for _, rule := range p.Rules {
		if !toolRuleID.MatchString(rule.ID) || rule.ID == "default" || ids[rule.ID] || (rule.Agent != "*" && rule.Agent != "codex" && rule.Agent != "claude") || !validID(rule.Tool, true) || !decisionValid(rule.Decision) {
			return p, nil, code("aidr_hook_policy_invalid")
		}
		ids[rule.ID] = true
	}
	return p, raw, nil
}

func (p ToolPolicy) Evaluate(event Event, now time.Time) ToolDecision {
	result := ToolDecision{Decision: "deny", Revision: p.Revision, Matched: []string{}, Code: "aidr_hook_policy_expired"}
	expires, _ := positiveDecimal(p.Expires)
	issued, _ := positiveDecimal(p.Issued)
	if expires <= now.Unix() || issued > now.Unix()+30 {
		return result
	}
	matched := []ToolRule{}
	for _, rule := range p.Rules {
		if (rule.Agent == "*" || rule.Agent == event.Agent) && (rule.Tool == "*" || rule.Tool == event.Tool) {
			matched = append(matched, rule)
		}
	}
	sort.Slice(matched, func(i, j int) bool { return matched[i].ID < matched[j].ID })
	for _, rule := range matched {
		result.Matched = append(result.Matched, rule.ID)
	}
	result.Decision = p.Default
	result.Rule = "default"
	result.Code = "aidr_hook_rule_" + p.Default
	for _, decision := range []string{"deny", "ask", "allow"} {
		for _, rule := range matched {
			if rule.Decision == decision {
				result.Decision = decision
				result.Rule = rule.ID
				result.Code = "aidr_hook_rule_" + decision
				return result
			}
		}
	}
	return result
}

// ConfigureControl pins an operator-provided key. With control configured,
// missing or expired policy yields deny; without it the receiver audits only.
func (s *Store) ConfigureControl(ctx context.Context, key []byte) error {
	x, _ := elliptic.Unmarshal(elliptic.P256(), key)
	if x == nil {
		return code("aidr_hook_control_key_invalid")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	var envelope []byte
	err := s.db.QueryRowContext(ctx, `SELECT value FROM hook_meta WHERE key='tool_policy'`).Scan(&envelope)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if err == nil {
		p, raw, e := verifyToolPolicy(envelope, key, s.device, time.Now())
		if e != nil {
			return e
		}
		s.controlPolicy = &p
		s.controlPayload = raw
	}
	s.controlKey = append([]byte{}, key...)
	s.controlMode = "intercept"
	return nil
}

// The platform mode governs execution; a pinned key only verifies signed rules.
func (s *Store) SetControlMode(mode string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if mode != "audit" && mode != "intercept" {
		return code("aidr_hook_mode_invalid")
	}
	if mode == "intercept" && len(s.controlKey) == 0 {
		return code("aidr_hook_control_key_invalid")
	}
	s.controlMode = mode
	return nil
}

func (s *Store) ControlKey() []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]byte{}, s.controlKey...)
}

func (s *Store) ApplyToolPolicy(ctx context.Context, envelope []byte, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.controlKey) == 0 {
		return code("aidr_hook_control_not_configured")
	}
	p, raw, err := verifyToolPolicy(envelope, s.controlKey, s.device, now)
	if err != nil {
		return err
	}
	if s.controlPolicy != nil {
		old, _ := positiveDecimal(s.controlPolicy.Revision)
		next, _ := positiveDecimal(p.Revision)
		if next < old {
			return code("aidr_hook_policy_stale")
		}
		if next == old {
			if !bytes.Equal(raw, s.controlPayload) {
				return code("aidr_hook_policy_conflict")
			}
			return nil
		}
	}
	if _, err = s.db.ExecContext(ctx, `INSERT INTO hook_meta VALUES('tool_policy',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, envelope); err != nil {
		return err
	}
	s.controlPolicy = &p
	s.controlPayload = raw
	return nil
}

func (s *Store) EvaluateTool(event Event, now time.Time) ToolDecision {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.controlMode != "intercept" {
		return ToolDecision{Decision: "allow", Code: "aidr_hook_audit_only", Matched: []string{}}
	}
	if s.controlPolicy == nil {
		return ToolDecision{Decision: "deny", Code: "aidr_hook_policy_missing", Matched: []string{}}
	}
	return s.controlPolicy.Evaluate(event, now)
}
