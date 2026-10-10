// Package enforcement implements the device-side contract for signed macOS
// policies. Policy verification and compilation run outside ES callbacks.
package enforcement

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"path"
	"strconv"
	"strings"
	"time"
)

const MaxPolicyBytes = 65536

type Rule struct {
	ID       string `json:"id"`
	Path     string `json:"path"`
	Actor    string `json:"actor"`
	Decision string `json:"decision"`
}

// Decimal strings preserve exact identities and revisions through web clients.
type Policy struct {
	Schema             int      `json:"schema"`
	Device             string   `json:"device"`
	Revision           string   `json:"revision"`
	IssuedAt           string   `json:"issued_at"`
	ExpiresAt          string   `json:"expires_at"`
	UnknownActorAction string   `json:"unknown_actor_action"`
	ExpiredAction      string   `json:"expired_action"`
	AgentExecutables   []string `json:"agent_executables"`
	Rules              []Rule   `json:"rules"`
}

// Payload is the exact signed UTF-8 JSON, base64 encoded. Signatures use P-256
// ECDSA SHA-256 in ASN.1 DER format, supported by macOS Security.framework.
type Envelope struct {
	Payload   string `json:"payload"`
	Signature string `json:"signature"`
}

func strict(data []byte, value any) error {
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(value); err != nil {
		return err
	}
	if d.Decode(new(any)) != io.EOF {
		return errors.New("aidr_enforcement_json_invalid")
	}
	return nil
}

func decimal(s string) (uint64, bool) {
	v, err := strconv.ParseUint(s, 10, 64)
	return v, err == nil && strconv.FormatUint(v, 10) == s
}

func absolute(p string) bool {
	return len(p) > 1 && len(p) < 1024 && strings.HasPrefix(p, "/") && path.Clean(p) == p && !strings.ContainsAny(p, "\x00\r\n")
}

func (p Policy) Validate(device string, now time.Time) error {
	rev, r := decimal(p.Revision)
	issued, i := decimal(p.IssuedAt)
	expires, e := decimal(p.ExpiresAt)
	if p.Schema != 1 || p.Device != device || device == "" || len(device) > 128 || !r || rev == 0 || !i || !e || expires <= issued || expires-issued > 30*86400 || issued > uint64(now.Unix()+60) || expires <= uint64(now.Unix()) || len(p.AgentExecutables) > 32 || p.AgentExecutables == nil || len(p.Rules) > 128 || p.Rules == nil {
		return errors.New("aidr_enforcement_policy_invalid")
	}
	decision := func(s string) bool { return s == "allow" || s == "deny" }
	if !decision(p.UnknownActorAction) || !decision(p.ExpiredAction) {
		return errors.New("aidr_enforcement_policy_invalid")
	}
	roots := map[string]bool{}
	for _, executable := range p.AgentExecutables {
		if !absolute(executable) || roots[executable] {
			return errors.New("aidr_enforcement_root_invalid")
		}
		roots[executable] = true
	}
	ids := map[string]bool{}
	for _, rule := range p.Rules {
		if rule.ID == "" || len(rule.ID) > 64 || ids[rule.ID] || !absolute(rule.Path) || (rule.Actor != "agent" && rule.Actor != "all") || !decision(rule.Decision) {
			return errors.New("aidr_enforcement_rule_invalid")
		}
		for _, ch := range rule.ID {
			if !(ch >= 'a' && ch <= 'z' || ch >= 'A' && ch <= 'Z' || ch >= '0' && ch <= '9' || ch == '-' || ch == '_') {
				return errors.New("aidr_enforcement_rule_invalid")
			}
		}
		ids[rule.ID] = true
	}
	return nil
}

func Verify(data, publicKey []byte, device string, now time.Time) (Policy, error) {
	var p Policy
	payload, err := VerifyPayload(data, publicKey)
	if err != nil {
		return p, err
	}
	if strict(payload, &p) != nil {
		return Policy{}, errors.New("aidr_enforcement_policy_invalid")
	}
	return p, p.Validate(device, now)
}

// VerifyPayload authenticates the exact signed bytes. The caller must validate
// its own domain, device and scope before using the payload as an authority.
func VerifyPayload(data, publicKey []byte) ([]byte, error) {
	var envelope Envelope
	if len(data) > MaxPolicyBytes || strict(data, &envelope) != nil {
		return nil, errors.New("aidr_enforcement_envelope_invalid")
	}
	payload, err := base64.StdEncoding.DecodeString(envelope.Payload)
	if err != nil {
		return nil, errors.New("aidr_enforcement_envelope_invalid")
	}
	sig, err := base64.StdEncoding.DecodeString(envelope.Signature)
	if err != nil {
		return nil, errors.New("aidr_enforcement_signature_invalid")
	}
	x, y := elliptic.Unmarshal(elliptic.P256(), publicKey)
	if x == nil {
		return nil, errors.New("aidr_enforcement_key_invalid")
	}
	digest := sha256.Sum256(payload)
	if !ecdsa.VerifyASN1(&ecdsa.PublicKey{Curve: elliptic.P256(), X: x, Y: y}, digest[:], sig) {
		return nil, errors.New("aidr_enforcement_signature_invalid")
	}
	return payload, nil
}

// CanReplace accepts equal revisions only with the same payload and signature.
// JSON whitespace, field order and string escaping are transport details.
// Rollback is a new revision containing earlier rule content.
func CanReplace(current, next Policy, currentEnvelope, nextEnvelope []byte) error {
	a, okA := decimal(current.Revision)
	b, okB := decimal(next.Revision)
	if !okB || (okA && b < a) {
		return errors.New("aidr_enforcement_revision_stale")
	}
	if okA && a == b {
		var prior, incoming Envelope
		if strict(currentEnvelope, &prior) != nil || strict(nextEnvelope, &incoming) != nil || prior != incoming {
			return errors.New("aidr_enforcement_revision_conflict")
		}
	}
	return nil
}
