package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func signGrant(t *testing.T, key *ecdsa.PrivateKey, g any) []byte {
	t.Helper()
	raw, err := json.Marshal(g)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(raw)
	sig, err := ecdsa.SignASN1(rand.Reader, key, sum[:])
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(map[string]string{"payload": base64.StdEncoding.EncodeToString(raw), "signature": base64.StdEncoding.EncodeToString(sig)})
	return data
}

func TestTwentyConcurrentScopesCannotExchangeGrants(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 100)
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	public := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	now := time.Now()
	grants := make([]ToolGrant, 20)
	for i := range grants {
		// One session and call ID, different native turns and input parameters.
		// All events arrive at the same receiver; receiver identity is not a call.
		raw := fmt.Sprintf(`{"hook_event_name":"PreToolUse","session_id":"shared-session","turn_id":"turn-%d","tool_use_id":"shared-call","tool_name":"Bash","tool_input":{"command":"printf audit-%d"}}`, i, i)
		record, e := s.Receive(ctx, testID(i+1), "501", "codex", "PreToolUse", []byte(raw))
		if e != nil {
			t.Fatal(e)
		}
		scope, e := s.ScopeFor(record, "review", "1")
		if e != nil {
			t.Fatal(e)
		}
		grants[i] = ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: fmt.Sprintf("%032x", i+1), Nonce: fmt.Sprintf("%032x", i+100), Revision: "1", Decision: "allow", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Minute).Unix()), Scope: scope}
		if e = s.ApplyGrant(ctx, signGrant(t, key, grants[i]), public, now); e != nil {
			t.Fatal(e)
		}
	}
	start := make(chan struct{})
	var wg sync.WaitGroup
	var accepted, crossed, replayed atomic.Int32
	for i := range grants {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			g := grants[i]
			if s.ConsumeGrant(ctx, g.ID, grants[(i+1)%len(grants)].Scope, "1", now) == nil {
				crossed.Add(1)
			}
			if s.ConsumeGrant(ctx, g.ID, g.Scope, "1", now) == nil {
				accepted.Add(1)
			}
			if s.ConsumeGrant(ctx, g.ID, g.Scope, "1", now) == nil {
				replayed.Add(1)
			}
		}(i)
	}
	close(start)
	wg.Wait()
	if accepted.Load() != 20 || crossed.Load() != 0 || replayed.Load() != 0 {
		t.Fatalf("accepted=%d cross-scope=%d replay=%d", accepted.Load(), crossed.Load(), replayed.Load())
	}
}

func TestGrantExactScopeAtomicUseAndReceiverRestart(t *testing.T) {
	for _, agent := range []string{"claude", "codex", "codebuddy", "workbuddy", "trae", "trae-cn", "qoder-hooks", "qwenwork", "zcode"} {
		t.Run(agent, func(t *testing.T) { testGrantExactScope(t, agent) })
	}
}

func testGrantExactScope(t *testing.T, agent string) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 100)
	raw := []byte(storeInput)
	if agent == "qwenwork" {
		raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"session","tool_use_id":"native-call","tool_name":"mcp__qw-builtin__mcp_workspace_bash","tool_input":{"command":"printf approved","dir_path":"/tmp"}}`)
	}
	if agent == "codebuddy" {
		raw = []byte(`{"hook_event_name":"PreToolUse","session_id":"session","generation_id":"turn","tool_name":"Bash","tool_input":{"command":"printf approved"}}`)
	}
	user := "501"
	if runtime.GOOS == "windows" {
		user = "S-1-5-21-111-222-333-1001"
	}
	record, err := s.Receive(ctx, testID(1), user, agent, "PreToolUse", raw)
	if err != nil {
		t.Fatal(err)
	}
	scope, err := s.ScopeFor(record, "review-command", "1")
	if err != nil {
		t.Fatal(err)
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	public := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	now := time.Now()
	grant := ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: strings.Repeat("a", 32), Nonce: strings.Repeat("b", 32), Revision: "1", Decision: "allow", Issued: strconv.FormatInt(now.Unix(), 10), Expires: strconv.FormatInt(now.Add(time.Minute).Unix(), 10), Scope: scope}
	envelope := signGrant(t, key, grant)
	if err = s.ApplyGrant(ctx, envelope, public, now); err != nil {
		t.Fatal(err)
	}
	for _, alter := range []func(*ToolScope){
		func(p *ToolScope) { p.Device = "other" }, func(p *ToolScope) { p.Session = "other" }, func(p *ToolScope) { p.Turn = "other" }, func(p *ToolScope) { p.Call = "other" }, func(p *ToolScope) { p.User = "502" }, func(p *ToolScope) { p.Subagent = "other" }, func(p *ToolScope) { p.Tool = "Read" }, func(p *ToolScope) { p.InputDigest = strings.Repeat("c", 64) }, func(p *ToolScope) { p.Attempt = strings.Repeat("d", 32) }, func(p *ToolScope) { p.ExecutionPoint = "os_open" },
	} {
		changed := scope
		alter(&changed)
		if s.ConsumeGrant(ctx, grant.ID, changed, "1", now) == nil {
			t.Fatal("scope mismatch authorized")
		}
	}
	if s.ConsumeGrant(ctx, grant.ID, scope, "2", now) == nil {
		t.Fatal("new policy used old grant")
	}
	var wins atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if s.ConsumeGrant(ctx, grant.ID, scope, "1", now) == nil {
				wins.Add(1)
			}
		}()
	}
	wg.Wait()
	if wins.Load() != 1 {
		t.Fatalf("single-use winners: %d", wins.Load())
	}
	if err = s.ApplyGrant(ctx, envelope, public, now); err != nil {
		t.Fatal(err)
	}
	if s.ConsumeGrant(ctx, grant.ID, scope, "1", now) == nil {
		t.Fatal("delivery replay restored grant")
	}
	grant.Revision = "2"
	if err = s.ApplyGrant(ctx, signGrant(t, key, grant), public, now); err != nil {
		t.Fatal(err)
	}
	if s.ConsumeGrant(ctx, grant.ID, scope, "1", now) == nil {
		t.Fatal("new revision restored consumed grant")
	}
	grant.ID = strings.Repeat("c", 32)
	grant.Nonce = strings.Repeat("d", 32)
	if err = s.ApplyGrant(ctx, signGrant(t, key, grant), public, now); err != nil {
		t.Fatal(err)
	}
	if s.ConsumeGrant(ctx, grant.ID, scope, "1", now) == nil {
		t.Fatal("second grant reused attempt")
	}
	s.Close()
	s = openTestStore(t, dir, 100)
	if s.ApplyGrant(ctx, envelope, public, now) == nil {
		t.Fatal("old receiver authority survived restart")
	}
	if _, err = s.ScopeFor(record, "review-command", "1"); err == nil {
		t.Fatal("old receiver record became current attempt")
	}
}

func TestGrantRevocationExpirySignatureAndVersion(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 100)
	record, err := s.Receive(ctx, testID(1), "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil {
		t.Fatal(err)
	}
	scope, _ := s.ScopeFor(record, "rule", "1")
	now := time.Now()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	public := elliptic.Marshal(elliptic.P256(), key.X, key.Y)
	g := ToolGrant{Schema: 1, Domain: "aidr.tool-grant/1", ID: strings.Repeat("a", 32), Nonce: strings.Repeat("b", 32), Revision: "1", Decision: "allow", Issued: fmt.Sprint(now.Unix()), Expires: fmt.Sprint(now.Add(time.Minute).Unix()), Scope: scope}
	if err = s.ApplyGrant(ctx, signGrant(t, key, g), public, now); err != nil {
		t.Fatal(err)
	}
	if s.ConsumeGrant(ctx, g.ID, scope, "1", now.Add(2*time.Minute)) == nil {
		t.Fatal("expired grant consumed")
	}
	changed := g
	changed.Decision = "deny"
	if s.ApplyGrant(ctx, signGrant(t, key, changed), public, now) == nil {
		t.Fatal("same-version conflict accepted")
	}
	g.Revision = "2"
	g.Decision = "revoke"
	if err = s.ApplyGrant(ctx, signGrant(t, key, g), public, now); err != nil {
		t.Fatal(err)
	}
	if s.ConsumeGrant(ctx, g.ID, scope, "1", now) == nil {
		t.Fatal("revoked grant consumed")
	}
	g.Revision = "1"
	if s.ApplyGrant(ctx, signGrant(t, key, g), public, now) == nil {
		t.Fatal("stale revision accepted")
	}
	g.Revision = "3"
	g.Decision = "allow"
	if s.ApplyGrant(ctx, signGrant(t, key, g), public, now) == nil {
		t.Fatal("revoked nonce restored")
	}
	g.ID = strings.Repeat("e", 32)
	g.Nonce = strings.Repeat("f", 32)
	other, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if s.ApplyGrant(ctx, signGrant(t, other, g), public, now) == nil {
		t.Fatal("untrusted signer accepted")
	}
	g.Domain = "aidr.os-grant/1"
	if s.ApplyGrant(ctx, signGrant(t, key, g), public, now) == nil {
		t.Fatal("foreign authority domain accepted")
	}
}

func TestInputBindingIncludesWorkingDirectory(t *testing.T) {
	first := normalize(t, "codex", "PreToolUse", strings.Replace(storeInput, `"tool_input":`, `"cwd":"/tmp/one","tool_input":`, 1), true)
	second := normalize(t, "codex", "PreToolUse", strings.Replace(storeInput, `"tool_input":`, `"cwd":"/tmp/two","tool_input":`, 1), true)
	if first.InputDigest == second.InputDigest {
		t.Fatal("changed working directory retained authorization digest")
	}
}
