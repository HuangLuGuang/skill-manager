//go:build darwin || linux

package hooks

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func upgradeSocket(t *testing.T) string {
	t.Helper()
	root, err := os.MkdirTemp("", "hook-upgrade-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(root) })
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Join(root, "h.sock")
}

func TestUpgradeWaitsForReceiverAndPreservesPolicyDecision(t *testing.T) {
	for _, decision := range []string{"allow", "deny"} {
		t.Run(decision, func(t *testing.T) {
			path := upgradeSocket(t)
			finish, err := BeginReceiverUpgrade(path)
			if err != nil {
				t.Fatal(err)
			}
			defer finish()
			s := openTestStore(t, filepath.Join(filepath.Dir(path), "state"), 10)
			s.controlMode = "intercept"
			s.bridgeIntercept.Store(true)
			s.controlPolicy = &ToolPolicy{Revision: "7", Default: decision}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			started := make(chan struct{})
			done := make(chan error, 1)
			go func() {
				time.Sleep(200 * time.Millisecond)
				r, e := Listen(path, s)
				close(started)
				if e != nil {
					done <- e
					return
				}
				done <- r.Serve(ctx)
			}()
			before := time.Now()
			reply, err := ExchangeForHost(ctx, path, IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(1), Agent: "codex", Hook: "PreToolUse", Raw: json.RawMessage(storeInput)}, time.Second)
			cancel()
			<-started
			if e := <-done; e != nil {
				t.Fatal(e)
			}
			if err != nil || reply.Decision == nil || reply.Decision.Decision != decision || time.Since(before) < 200*time.Millisecond {
				t.Fatalf("%+v %v", reply, err)
			}
			var count int
			if err = s.db.QueryRow("SELECT count(*) FROM hook_events").Scan(&count); err != nil || count != 1 {
				t.Fatalf("duplicate/missing event: %d %v", count, err)
			}
		})
	}
}

func TestUpgradeWaitRequiresValidMarkerAndHonorsCancellation(t *testing.T) {
	path := upgradeSocket(t)
	for _, mode := range []string{"missing", "expired", "public", "invalid", "cancelled"} {
		t.Run(mode, func(t *testing.T) {
			finish, err := BeginReceiverUpgrade(path)
			if err != nil {
				t.Fatal(err)
			}
			defer finish()
			switch mode {
			case "missing":
				finish()
			case "expired":
				now := time.Now().Add(-time.Minute)
				body, _ := json.Marshal(upgradeWindow{now, now.Add(upgradeWindowLifetime)})
				os.WriteFile(path+".upgrade.json", body, 0600)
			case "public":
				os.Chmod(path+".upgrade.json", 0644)
			case "invalid":
				os.WriteFile(path+".upgrade.json", []byte(`{}`), 0600)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
			defer cancel()
			before := time.Now()
			_, err = ExchangeForHost(ctx, path, IPCRequest{Version: 1, Method: "GetHealth"}, time.Second)
			elapsed := time.Since(before)
			if err == nil || elapsed > time.Second {
				t.Fatalf("unbounded wait: %v %v", elapsed, err)
			}
			if mode == "cancelled" && elapsed < 100*time.Millisecond {
				t.Fatal("did not wait during upgrade")
			}
			if mode != "cancelled" && elapsed >= 100*time.Millisecond {
				t.Fatal("waited without private active marker")
			}
		})
	}
}

func TestUpgradeDoesNotReplayConnectedFailureOrDenial(t *testing.T) {
	path := upgradeSocket(t)
	finish, err := BeginReceiverUpgrade(path)
	if err != nil {
		t.Fatal(err)
	}
	defer finish()
	for _, failure := range []string{"aidr_hook_peer_rejected", "aidr_hook_protocol_invalid", "aidr_hook_transport_failed", ""} {
		calls := 0
		reply, err := exchangeForHost(context.Background(), path, IPCRequest{}, time.Second, func(context.Context, string, IPCRequest) (IPCResponse, error) {
			calls++
			if failure != "" {
				return IPCResponse{}, code(failure)
			}
			return IPCResponse{Decision: &ToolDecision{Decision: "deny", Code: "aidr_hook_rule_deny"}}, nil
		})
		if calls != 1 || (failure == "" && (err != nil || reply.Decision.Decision != "deny")) {
			t.Fatalf("replayed final result: %d %+v %v", calls, reply, err)
		}
	}
}

func TestUpgradeWindowExpiryBoundsWaiting(t *testing.T) {
	path := upgradeSocket(t)
	finish, err := BeginReceiverUpgrade(path)
	if err != nil {
		t.Fatal(err)
	}
	defer finish()
	now := time.Now().UTC()
	body, _ := json.Marshal(upgradeWindow{now.Add(-upgradeWindowLifetime + 200*time.Millisecond), now.Add(200 * time.Millisecond)})
	if err = os.WriteFile(path+".upgrade.json", body, 0600); err != nil {
		t.Fatal(err)
	}
	_, err = ExchangeForHost(context.Background(), path, IPCRequest{Version: 1, Method: "GetHealth"}, 20*time.Millisecond)
	if err == nil || time.Since(now) < 150*time.Millisecond || time.Since(now) > time.Second {
		t.Fatalf("expiry not enforced: %v %v", time.Since(now), err)
	}
	finish()
	if _, err = os.Stat(path + ".upgrade.json"); !os.IsNotExist(err) {
		t.Fatal("upgrade marker was not removed")
	}
}

func TestUpgradeWaitDoesNotOutliveRequestBudget(t *testing.T) {
	path := upgradeSocket(t)
	finish, err := BeginReceiverUpgrade(path)
	if err != nil {
		t.Fatal(err)
	}
	defer finish()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	started := time.Now()
	_, err = ExchangeForHost(ctx, path, IPCRequest{Version: 1, Method: "GetHealth"}, time.Second)
	if err == nil || time.Since(started) < 7500*time.Millisecond || time.Since(started) > 9*time.Second {
		t.Fatalf("request budget was not enforced: %v %v", time.Since(started), err)
	}
}

func TestReceiverDrainsAcceptedRequestOnStop(t *testing.T) {
	path := upgradeSocket(t)
	s := openTestStore(t, filepath.Join(filepath.Dir(path), "state"), 10)
	r, err := Listen(path, s)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- r.Serve(ctx) }()
	c, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.SetDeadline(time.Now().Add(3 * time.Second))
	// An accepted partial frame must remain usable after listener shutdown.
	var frame strings.Builder
	if err = writeFrame(&frame, IPCRequest{Version: 1, Method: "SubmitEvent", EventID: testID(1), Agent: "codex", Hook: "PreToolUse", Raw: json.RawMessage(storeInput)}); err != nil {
		t.Fatal(err)
	}
	c.Write([]byte(frame.String()[:1]))
	time.Sleep(50 * time.Millisecond)
	cancel()
	until := time.Now().Add(time.Second)
	for {
		probe, e := net.Dial("unix", path)
		if e != nil {
			break
		}
		probe.Close()
		if time.Now().After(until) {
			t.Fatal("listener did not stop")
		}
		time.Sleep(time.Millisecond)
	}
	if _, err = io.WriteString(c, frame.String()[1:]); err != nil {
		t.Fatal(err)
	}
	var reply IPCResponse
	if err = readFrame(c, &reply); err != nil || reply.Code != "aidr_hook_recorded" {
		t.Fatalf("lost accepted request: %+v %v", reply, err)
	}
	if err = <-done; err != nil {
		t.Fatal(err)
	}
}

func TestTeleAgentUpgradeWaitPreservesDecision(t *testing.T) {
	path := upgradeSocket(t)
	finish, err := BeginReceiverUpgrade(path)
	if err != nil {
		t.Fatal(err)
	}
	defer finish()
	started := time.Now()
	id := ""
	h, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: path, Secret: strings.Repeat("a", 64), Exchange: func(ctx context.Context, _ string, req IPCRequest) (IPCResponse, error) {
		if id != "" && id != req.EventID {
			t.Error("event identity changed")
		}
		id = req.EventID
		if time.Since(started) < 1200*time.Millisecond {
			return IPCResponse{}, code("aidr_hook_receiver_unavailable")
		}
		return IPCResponse{Decision: &ToolDecision{Decision: "deny", Code: "aidr_hook_rule_deny"}}, nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "http://localhost/"+strings.Repeat("a", 64)+"/security/instruction/review", strings.NewReader(teleReview))
	r.RemoteAddr = "127.0.0.1:12345"
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if !strings.Contains(w.Body.String(), `"result":2`) || !strings.Contains(w.Body.String(), "aidr_hook_rule_deny") {
		t.Fatal(w.Body.String())
	}
}

func TestTeleAgentConnectedReviewUsesReceiverDeadline(t *testing.T) {
	for _, decision := range []string{"allow", "deny"} {
		t.Run(decision, func(t *testing.T) {
			calls := 0
			h, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: upgradeSocket(t), Secret: strings.Repeat("a", 64), Exchange: func(ctx context.Context, _ string, req IPCRequest) (IPCResponse, error) {
				calls++
				select {
				case <-ctx.Done():
					return IPCResponse{}, ctx.Err()
				case <-time.After(1200 * time.Millisecond):
				}
				return IPCResponse{Decision: &ToolDecision{Decision: decision, Code: "aidr_hook_rule_" + decision}}, nil
			}})
			if err != nil {
				t.Fatal(err)
			}
			r := httptest.NewRequest(http.MethodPost, "http://localhost/"+strings.Repeat("a", 64)+"/security/instruction/review", strings.NewReader(teleReview))
			r.RemoteAddr = "127.0.0.1:12345"
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if calls != 1 || !strings.Contains(w.Body.String(), "aidr_hook_rule_"+decision) {
				t.Fatalf("premature timeout or replay: %d %s", calls, w.Body.String())
			}
		})
	}
}
