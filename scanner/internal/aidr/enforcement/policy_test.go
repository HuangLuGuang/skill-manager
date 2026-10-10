package enforcement

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

func TestSignedPolicyBoundaries(t *testing.T) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	pub := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	now := time.Unix(1800000000, 0)
	p := Policy{Schema: 1, Device: "test-device", Revision: "1", IssuedAt: "1800000000", ExpiresAt: "1800003600", UnknownActorAction: "allow", ExpiredAction: "deny", AgentExecutables: []string{"/private/tmp/agent"}, Rules: []Rule{{ID: "protected", Path: "/private/tmp/secret", Actor: "agent", Decision: "deny"}}}
	sign := func(p Policy) []byte {
		raw, _ := json.Marshal(p)
		h := sha256.Sum256(raw)
		sig, e := ecdsa.SignASN1(rand.Reader, key, h[:])
		if e != nil {
			t.Fatal(e)
		}
		data, _ := json.Marshal(Envelope{base64.StdEncoding.EncodeToString(raw), base64.StdEncoding.EncodeToString(sig)})
		return data
	}
	first := sign(p)
	got, err := Verify(first, pub, "test-device", now)
	if err != nil || got.Revision != "1" {
		t.Fatal(err)
	}
	if _, err = Verify(first, pub, "other-device", now); err == nil {
		t.Fatal("cross-device accepted")
	}
	if _, err = Verify(first, pub, "test-device", now.Add(time.Hour)); err == nil {
		t.Fatal("expired policy accepted")
	}
	var envelope Envelope
	json.Unmarshal(first, &envelope)
	envelope.Payload = base64.StdEncoding.EncodeToString([]byte(`{}`))
	tampered, _ := json.Marshal(envelope)
	if _, err = Verify(tampered, pub, "test-device", now); err == nil {
		t.Fatal("tampered payload accepted")
	}
	for name, change := range map[string]func(*Policy){
		"relative":             func(p *Policy) { p.Rules = []Rule{{"r", "relative", "agent", "deny"}} },
		"traversal":            func(p *Policy) { p.AgentExecutables = []string{"/tmp/../bin/sh"} },
		"duplicate":            func(p *Policy) { p.Rules = append(p.Rules, p.Rules[0]) },
		"unknown actor":        func(p *Policy) { p.UnknownActorAction = "unknown" },
		"unsupported decision": func(p *Policy) { p.Rules = []Rule{{"r", "/tmp/a", "agent", "ask"}} },
		"future":               func(p *Policy) { p.IssuedAt = "1800000300" },
		"overflow revision":    func(p *Policy) { p.Revision = "18446744073709551616" },
		"leading zero":         func(p *Policy) { p.Revision = "01" },
	} {
		t.Run(name, func(t *testing.T) {
			bad := p
			change(&bad)
			if _, e := Verify(sign(bad), pub, "test-device", now); e == nil {
				t.Fatal("invalid signed policy accepted")
			}
		})
	}
	if err = CanReplace(p, p, first, first); err != nil {
		t.Fatal(err)
	}
	var formatted bytes.Buffer
	if err = json.Indent(&formatted, first, "", "  "); err != nil {
		t.Fatal(err)
	}
	escaped := bytes.ReplaceAll(formatted.Bytes(), []byte("/"), []byte(`\/`))
	if _, err = Verify(escaped, pub, "test-device", now); err != nil {
		t.Fatal(err)
	}
	if err = CanReplace(p, p, first, escaped); err != nil {
		t.Fatal("JSON formatting changed policy identity", err)
	}
	if err = CanReplace(p, p, first, sign(p)); err == nil {
		t.Fatal("same revision different envelope accepted")
	}
	older := p
	older.Revision = "0"
	if err = CanReplace(p, older, first, sign(older)); err == nil {
		t.Fatal("rollback replay accepted")
	}
	rollback := p
	rollback.Revision = "2"
	if err = CanReplace(p, rollback, first, sign(rollback)); err != nil {
		t.Fatal(err)
	}
}
