package hooks

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"strconv"
	"time"

	products "skill-manager/scanner/internal/aidr/catalog"
	"skill-manager/scanner/internal/aidr/enforcement"
)

// ToolScope binds a single attempt at the plugin execution point. It cannot be
// used as an OS exemption; bridge identity never asserts a tool process identity.
type ToolScope struct {
	Device         string `json:"device"`
	Stream         string `json:"stream"`
	Receiver       string `json:"receiver_instance"`
	User           string `json:"user_scope"`
	Agent          string `json:"agent"`
	Session        string `json:"session_id"`
	Turn           string `json:"turn_id"`
	Call           string `json:"native_call_id"`
	Subagent       string `json:"native_agent_id"`
	Tool           string `json:"tool"`
	InputDigest    string `json:"input_digest"`
	Attempt        string `json:"attempt_nonce"`
	Rule           string `json:"rule_id"`
	PolicyRevision string `json:"policy_revision"`
	ExecutionPoint string `json:"execution_point"`
}

type ToolGrant struct {
	Schema   int       `json:"schema"`
	Domain   string    `json:"domain"`
	ID       string    `json:"grant_id"`
	Nonce    string    `json:"nonce"`
	Revision string    `json:"revision"`
	Decision string    `json:"decision"`
	Issued   string    `json:"issued_at"`
	Expires  string    `json:"expires_at"`
	Scope    ToolScope `json:"scope"`
}

var hexDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)

func positiveDecimal(s string) (int64, bool) {
	v, e := strconv.ParseInt(s, 10, 64)
	return v, e == nil && v > 0 && strconv.FormatInt(v, 10) == s
}
func (s ToolScope) valid() bool {
	_, rev := positiveDecimal(s.PolicyRevision)
	product, _ := products.Get(s.Agent)
	if !validID(s.Device, true) || !eventID.MatchString(s.Stream) || !eventID.MatchString(s.Receiver) || !validID(s.User, true) || !product.Approval || !validID(s.Session, true) || !validID(s.Turn, false) || !validID(s.Call, s.Agent != "codebuddy") || !validID(s.Subagent, false) || !validID(s.Tool, true) || !hexDigest.MatchString(s.InputDigest) || !eventID.MatchString(s.Attempt) || !validID(s.Rule, true) || !rev || s.ExecutionPoint != "plugin_pre_tool" {
		return false
	}
	// Codex call identity requires its native turn namespace. Claude's tool-use
	// IDs are scoped by session and may have no separate prompt ID.
	// CodeBuddy has no native call ID; its receiver attempt and input digest bind the grant.
	return (s.Agent != "codex" && s.Agent != "codebuddy") || s.Turn != ""
}

func (s *Store) ScopeFor(record Record, rule, revision string) (ToolScope, error) {
	scope := ToolScope{Device: s.device, Stream: s.stream, Receiver: record.ReceiverInstance, User: record.User, Agent: record.Event.Agent, Session: record.Event.Session, Turn: record.Event.Turn, Call: record.Event.Call, Subagent: record.Event.Subagent, Tool: record.Event.Tool, InputDigest: record.Event.InputDigest, Attempt: record.EventID, Rule: rule, PolicyRevision: revision, ExecutionPoint: "plugin_pre_tool"}
	if record.Event.Kind != "tool.pre" || scope.Receiver != s.instance || !scope.valid() {
		return ToolScope{}, code("aidr_hook_scope_unverified")
	}
	return scope, nil
}

func decodeStrict(raw []byte, out any) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if err := d.Decode(out); err != nil {
		return err
	}
	if d.Decode(new(any)) != io.EOF {
		return code("aidr_hook_grant_invalid")
	}
	return nil
}

// ApplyGrant accepts only signed control data for this running receiver. Even
// a newer signed allow cannot reset the consumed bit of an existing authority.
func (s *Store) ApplyGrant(ctx context.Context, envelope, publicKey []byte, now time.Time) error {
	raw, err := enforcement.VerifyPayload(envelope, publicKey)
	if err != nil {
		return code("aidr_hook_grant_signature_invalid")
	}
	var grant ToolGrant
	if decodeStrict(raw, &grant) != nil {
		return code("aidr_hook_grant_invalid")
	}
	rev, r := positiveDecimal(grant.Revision)
	issued, i := positiveDecimal(grant.Issued)
	expires, e := positiveDecimal(grant.Expires)
	if grant.Schema != 1 || grant.Domain != "aidr.tool-grant/1" || !eventID.MatchString(grant.ID) || !eventID.MatchString(grant.Nonce) || !r || !i || !e || expires <= issued || expires-issued > 300 || issued > now.Unix()+30 || expires <= now.Unix() || !grant.Scope.valid() || grant.Scope.Device != s.device || grant.Scope.Stream != s.stream || grant.Scope.Receiver != s.instance || (grant.Decision != "allow" && grant.Decision != "deny" && grant.Decision != "revoke") {
		return code("aidr_hook_grant_invalid")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var priorRevision int64
	var priorScope, priorNonce, priorDigest, priorDecision string
	err = tx.QueryRowContext(ctx, `SELECT revision,scope,nonce,digest,decision FROM hook_grants WHERE id=?`, grant.ID).Scan(&priorRevision, &priorScope, &priorNonce, &priorDigest, &priorDecision)
	scopeRaw, _ := json.Marshal(grant.Scope)
	hash := sha256.Sum256(raw)
	digest := hex.EncodeToString(hash[:])
	if err == nil {
		if priorScope != string(scopeRaw) || priorNonce != grant.Nonce {
			return code("aidr_hook_grant_scope_conflict")
		}
		if rev < priorRevision {
			return code("aidr_hook_grant_revision_stale")
		}
		if rev == priorRevision {
			if priorDigest != digest {
				return code("aidr_hook_grant_revision_conflict")
			}
			return nil
		}
		if (priorDecision == "deny" || priorDecision == "revoke") && grant.Decision == "allow" {
			return code("aidr_hook_grant_terminal")
		}
		_, err = tx.ExecContext(ctx, `UPDATE hook_grants SET revision=?,decision=?,payload=?,digest=? WHERE id=?`, rev, grant.Decision, raw, digest, grant.ID)
	} else if errors.Is(err, sql.ErrNoRows) {
		var count int
		if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM hook_grants`).Scan(&count); err != nil {
			return err
		}
		if count >= 10000 {
			return code("aidr_hook_grant_capacity")
		}
		var existing string
		if err = tx.QueryRowContext(ctx, `SELECT id FROM hook_grants WHERE nonce=?`, grant.Nonce).Scan(&existing); err == nil {
			return code("aidr_hook_grant_nonce_conflict")
		} else if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		_, err = tx.ExecContext(ctx, `INSERT INTO hook_grants(id,nonce,scope,revision,decision,payload,digest) VALUES(?,?,?,?,?,?,?)`, grant.ID, grant.Nonce, string(scopeRaw), rev, grant.Decision, raw, digest)
	}
	if err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Store) ConsumeGrant(ctx context.Context, id string, scope ToolScope, currentPolicyRevision string, now time.Time) error {
	if !scope.valid() || scope.Device != s.device || scope.Stream != s.stream || scope.Receiver != s.instance || scope.PolicyRevision != currentPolicyRevision {
		return code("aidr_hook_grant_scope_mismatch")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if err = consumeGrantTx(ctx, tx, id, scope, now); err != nil {
		return err
	}
	return tx.Commit()
}

func consumeGrantTx(ctx context.Context, tx *sql.Tx, id string, scope ToolScope, now time.Time) error {
	var raw []byte
	var consumed int
	var decision string
	if err := tx.QueryRowContext(ctx, `SELECT payload,consumed,decision FROM hook_grants WHERE id=?`, id).Scan(&raw, &consumed, &decision); errors.Is(err, sql.ErrNoRows) {
		return code("aidr_hook_grant_missing")
	} else if err != nil {
		return err
	}
	var grant ToolGrant
	if decodeStrict(raw, &grant) != nil {
		return code("aidr_hook_grant_invalid")
	}
	if grant.Scope != scope {
		return code("aidr_hook_grant_scope_mismatch")
	}
	if decision != "allow" {
		return code("aidr_hook_grant_" + decision)
	}
	expires, _ := positiveDecimal(grant.Expires)
	issued, _ := positiveDecimal(grant.Issued)
	if expires <= now.Unix() || issued > now.Unix()+30 {
		return code("aidr_hook_grant_expired")
	}
	if consumed != 0 {
		return code("aidr_hook_grant_consumed")
	}
	var used int
	if err := tx.QueryRowContext(ctx, `SELECT count(*) FROM hook_grants WHERE consumed=1 AND json_extract(scope,'$.attempt_nonce')=?`, scope.Attempt).Scan(&used); err != nil {
		return err
	}
	if used != 0 {
		return code("aidr_hook_grant_consumed")
	}
	result, err := tx.ExecContext(ctx, `UPDATE hook_grants SET consumed=1 WHERE id=? AND consumed=0 AND decision='allow'`, id)
	if err != nil {
		return err
	}
	n, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if n != 1 {
		return code("aidr_hook_grant_consumed")
	}
	return nil
}
