//go:build darwin || linux || windows

package main

import (
	"context"
	"io"
	"path/filepath"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func TestHookReceiverRecoversAfterRetryExhaustion(t *testing.T) {
	home := shortDesktopTestHome(t)
	cfg := managedclient.Config{Server: "http://127.0.0.1:1", Token: "fictional-token"}
	if err := managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	retry := managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 10}
	prefs := desktopPreferences{Enabled: true, HookMode: "audit", RuntimePolicy: &desktopRuntimePolicy{
		Version: "1", Target: managedclient.RuntimeGovernancePolicy{Retry: retry},
	}}
	if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	plan, err := automaticHookPlan(ctx, home)
	if err != nil {
		t.Fatal(err)
	}
	store, err := hooks.OpenStore(paths.State, cfg.Server, paths.Device, 10)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if store != nil {
			_ = store.Close()
		}
	}()
	raw := []byte(`{"hook_event_name":"PreToolUse","session_id":"retry-test","tool_name":"Read","tool_input":{"file_path":"/tmp/fictional"}}`)
	id, err := hooks.NewEventID()
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.Receive(ctx, id, "retry-test", "claude", "PreToolUse", raw); err != nil {
		t.Fatal(err)
	}
	supervisionPath := filepath.Join(paths.Root, "receiver-supervisor.json")
	old := hookSupervision{Version: 1, Configuration: plan.identity(), Queue: paths.State, Device: paths.Device,
		Attempts: 3, Suspended: true, Code: "aidr_desktop_receiver_failed", NextRetryAt: time.Now().UnixMilli()}
	if err = writeDesktopJSON(supervisionPath, old); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		manageAutomaticHooks(ctx, home, 20*time.Millisecond, func(ctx context.Context) error {
			return aidrHookServeContext(context.WithValue(ctx, managedHookContextKey{}, true), []string{"--managed-home", home}, io.Discard)
		})
	}()
	defer func() { cancel(); <-done }()

	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	for {
		var state hookSupervision
		if readDesktopJSON(supervisionPath, &state) == nil && state.LastFailure == "aidr_store_busy" {
			if state.Suspended || state.Active || state.NextRetryAt-state.LastFailureAt != 10000 {
				t.Fatalf("transient failure did not schedule bounded retry: %+v", state)
			}
			break
		}
		select {
		case <-ctx.Done():
			t.Fatalf("previously suspended receiver did not retry: %+v", state)
		case <-ticker.C:
		}
	}
	if err = store.Close(); err != nil {
		t.Fatal(err)
	}
	store = nil
	for {
		probe, err := hooks.Exchange(ctx, paths.Socket, hooks.IPCRequest{Version: 1, Method: "GetHealth"})
		if err == nil && probe.State != nil {
			if probe.State.Queued != 1 {
				t.Fatalf("pending event lost after recovery: %+v", probe.State)
			}
			id, err := hooks.NewEventID()
			if err != nil {
				t.Fatal(err)
			}
			reply, err := hooks.Exchange(ctx, paths.Socket, hooks.IPCRequest{Version: 1, Method: "SubmitEvent", EventID: id, Agent: "claude", Hook: "PreToolUse", Raw: raw})
			if err != nil || reply.Accepted != 1 {
				t.Fatalf("recovered receiver rejected new event: %+v %v", reply, err)
			}
			return
		}
		select {
		case <-ctx.Done():
			t.Fatal("receiver did not recover after queue lock was released", err)
		case <-ticker.C:
		}
	}
}

func TestHookRetryKeepsExplicitStopsAndCapsContinuousBackoff(t *testing.T) {
	now := time.Now()
	retry := managedclient.ReceiverRetryPolicy{Mode: "continuous", MaxIntervalSeconds: 60}
	state := hookSupervision{Attempts: 21}
	state.failure("aidr_desktop_receiver_ended", retry, now)
	if state.Suspended || state.NextRetryAt != now.Add(time.Minute).UnixMilli() {
		t.Fatalf("continuous retry stopped at the counter limit: %+v", state)
	}
	state.failure("aidr_upload_auth_rejected", retry, now)
	state.resumeLegacyRetry(retry)
	if !state.Suspended || state.NextRetryAt != 0 {
		t.Fatalf("authentication failure should require correction: %+v", state)
	}
	retry.Mode = "none"
	state.failure("aidr_store_busy", retry, now)
	state.resumeLegacyRetry(retry)
	if !state.Suspended || state.NextRetryAt != 0 {
		t.Fatalf("explicit no-retry policy was ignored: %+v", state)
	}
}
