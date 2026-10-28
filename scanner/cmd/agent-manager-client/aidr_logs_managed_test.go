package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"skill-manager/scanner/internal/managedclient"
)

func TestAutomaticDoubaoIncludesFeishuLocalRoots(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("macOS source")
	}
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic"}); err != nil {
		t.Fatal(err)
	}
	profile := filepath.Join(home, "Library/Application Support/LarkShell/aha/users/test")
	for _, sub := range []string{"doubao/.doubao/agent_mode/workspace/.sessions", "profile_explorer/IndexedDB"} {
		if err := os.MkdirAll(filepath.Join(profile, sub), 0700); err != nil {
			t.Fatal(err)
		}
	}
	p := logTestPolicy()
	p.Classification.RuntimeGovernance.LogSources = []string{"doubaowork"}
	plan, err := automaticLogPlan(home, p)
	if err != nil || len(plan.roots) != 4 || !plan.enabled {
		t.Fatalf("plan %+v %v", plan, err)
	}
	p.Classification.RuntimeGovernance.Channels.Logs = false
	disabled, err := automaticLogPlan(home, p)
	if err != nil || disabled.enabled {
		t.Fatal("log switch bypassed", err)
	}
}

func logTestPolicy() managedclient.Policy {
	return managedclient.Policy{Classification: &managedclient.ClassificationPolicy{RuntimeGovernanceConfigured: true, RuntimeGovernanceVersion: "1", RuntimeGovernance: &managedclient.RuntimeGovernancePolicy{Enabled: true, Channels: &managedclient.RuntimeCollectionChannels{Logs: true, Hooks: true}, Installation: "manual", AccessMode: "ordinary", Updates: "manual", Retry: managedclient.ReceiverRetryPolicy{Mode: "fixed", Retries: 2, MaxIntervalSeconds: 10}}}}
}

func TestAutomaticLogLegacyAndDestinationBinding(t *testing.T) {
	home := shortDesktopTestHome(t)
	cfg := managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-log-token"}
	if err := managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	p := logTestPolicy()
	p.Classification.RuntimeGovernance.Channels = nil
	legacy, err := automaticLogPlan(home, p)
	if err != nil || legacy.state != "" {
		t.Fatal("old policy enabled new channel", err)
	}
	p = logTestPolicy()
	first, err := automaticLogPlan(home, p)
	if err != nil || !first.enabled {
		t.Fatal(err)
	}
	cfg.Token = "synthetic-rotated-log-token"
	if err := managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	rotated, _ := automaticLogPlan(home, p)
	if first.state != rotated.state || first.identity() == rotated.identity() {
		t.Fatal("rotation did not refresh transport or changed queue")
	}
	cfg.Server = "http://127.0.0.1:10"
	if err := managedclient.SaveConfig(home, cfg); err != nil {
		t.Fatal(err)
	}
	other, _ := automaticLogPlan(home, p)
	if other.state == first.state {
		t.Fatal("different platform reused queue")
	}
}

func TestAutomaticLogNoRestartForRevisionAndSwitchAndJoinedExit(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-log-token"}); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	p := logTestPolicy()
	get := func() managedclient.Policy { mu.Lock(); defer mu.Unlock(); return p }
	starts := make(chan *atomic.Bool, 3)
	stopped := make(chan struct{}, 3)
	var startsCount atomic.Int32
	worker := func(ctx context.Context, _ string, _ logRunPlan, enabled *atomic.Bool) error {
		startsCount.Add(1)
		starts <- enabled
		<-ctx.Done()
		stopped <- struct{}{}
		return ctx.Err()
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { manageAutomaticLogs(ctx, home, get, 5*time.Millisecond, worker); close(done) }()
	var enabled *atomic.Bool
	select {
	case enabled = <-starts:
	case <-time.After(time.Second):
		t.Fatal("no automatic start")
	}
	mu.Lock()
	p = logTestPolicy()
	p.Classification.RuntimeGovernanceVersion = "2"
	p.Classification.RuntimeGovernance.Channels.Logs = false
	mu.Unlock()
	deadline := time.Now().Add(time.Second)
	for enabled.Load() && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if enabled.Load() || startsCount.Load() != 1 {
		t.Fatal("OFF restarted or failed to pause")
	}
	mu.Lock()
	p = logTestPolicy()
	p.Classification.RuntimeGovernanceVersion = "3"
	mu.Unlock()
	deadline = time.Now().Add(time.Second)
	for !enabled.Load() && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if !enabled.Load() || startsCount.Load() != 1 {
		t.Fatal("same binding revision restarted worker")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("did not join worker")
	}
	select {
	case <-stopped:
	default:
		t.Fatal("orphan worker")
	}
	plan, _ := automaticLogPlan(home, get())
	var state logSupervision
	if err := readDesktopJSON(filepath.Join(plan.state, "log-supervisor.json"), &state); err != nil || state.Attempts != 0 {
		t.Fatal("clean exit consumed retry", err, state)
	}
}

func TestAutomaticLogConflictIsSuspendedAcrossRestart(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-log-token"}); err != nil {
		t.Fatal(err)
	}
	p := logTestPolicy()
	var attempts atomic.Int32
	worker := func(context.Context, string, logRunPlan, *atomic.Bool) error {
		attempts.Add(1)
		return errors.New("aidr_store_busy")
	}
	for i := 0; i < 2; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), 70*time.Millisecond)
		manageAutomaticLogs(ctx, home, func() managedclient.Policy { return p }, 5*time.Millisecond, worker)
		cancel()
	}
	if attempts.Load() != 1 {
		t.Fatal("conflict restart loop", attempts.Load())
	}
	plan, _ := automaticLogPlan(home, p)
	var saved logSupervision
	if err := readDesktopJSON(filepath.Join(plan.state, "log-supervisor.json"), &saved); err != nil || !saved.Suspended || saved.Code != "aidr_store_busy" {
		t.Fatal("conflict hidden", err)
	}
}

func TestAutomaticLogRetryBudgetPersistsAcrossRestart(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-log-token"}); err != nil {
		t.Fatal(err)
	}
	p := logTestPolicy()
	p.Classification.RuntimeGovernance.Retry.Mode = "none"
	var attempts atomic.Int32
	worker := func(context.Context, string, logRunPlan, *atomic.Bool) error {
		attempts.Add(1)
		return errors.New("aidr_log_test_failure")
	}
	for i := 0; i < 2; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), 70*time.Millisecond)
		manageAutomaticLogs(ctx, home, func() managedclient.Policy { return p }, 5*time.Millisecond, worker)
		cancel()
	}
	if attempts.Load() != 1 {
		t.Fatal("restart granted more attempts", attempts.Load())
	}
}

func TestAutomaticLogExplicitRetryIsBoundAndConsumedOnce(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "synthetic-log-token"}); err != nil {
		t.Fatal(err)
	}
	p := logTestPolicy()
	p.Classification.RuntimeGovernance.Retry.Mode = "none"
	var attempts atomic.Int32
	worker := func(context.Context, string, logRunPlan, *atomic.Bool) error {
		attempts.Add(1)
		return errors.New("aidr_store_busy")
	}
	run := func() {
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Millisecond)
		defer cancel()
		manageAutomaticLogs(ctx, home, func() managedclient.Policy { return p }, 5*time.Millisecond, worker)
	}
	run()
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	if err = requestLogRetry(paths); err != nil {
		t.Fatal(err)
	}
	run()
	run()
	if attempts.Load() != 2 {
		t.Fatal("retry replayed or skipped", attempts.Load())
	}
	plan, _ := automaticLogPlan(home, p)
	var state logSupervision
	if err = readDesktopJSON(filepath.Join(plan.state, "log-supervisor.json"), &state); err != nil || state.RetryRequest == "" || !state.Suspended {
		t.Fatal("retry receipt missing", err)
	}
	now := time.Now()
	request := logRetryRequest{Configuration: state.Configuration, PolicyVersion: state.PolicyVersion, Nonce: "00000000000000000000000000000000", RequestedAt: now.UTC().Format(time.RFC3339Nano)}
	if !request.valid(state, now) {
		t.Fatal("valid retry rejected")
	}
	request.PolicyVersion = "99"
	if request.valid(state, now) {
		t.Fatal("different revision accepted")
	}
	request.PolicyVersion = state.PolicyVersion
	request.Configuration = "different-device"
	if request.valid(state, now) {
		t.Fatal("different binding accepted")
	}
	request.Configuration = state.Configuration
	request.RequestedAt = now.Add(-6 * time.Minute).UTC().Format(time.RFC3339Nano)
	if request.valid(state, now) {
		t.Fatal("expired retry accepted")
	}
}

func TestLogResumeSinceIncludesDowntime(t *testing.T) {
	now := time.Date(2026, 10, 20, 0, 0, 0, 0, time.UTC)
	for _, item := range []struct {
		ack  string
		want time.Time
	}{
		{"", now.Add(-24 * time.Hour)},
		{"invalid", now.Add(-24 * time.Hour)},
		{now.Add(time.Hour).Format(time.RFC3339), now.Add(-24 * time.Hour)},
		{now.Add(-time.Hour).Format(time.RFC3339), now.Add(-24 * time.Hour)},
		{now.Add(-6 * 24 * time.Hour).Format(time.RFC3339), now.Add(-6 * 24 * time.Hour)},
	} {
		if got := logResumeSince(now, item.ack); !got.Equal(item.want) {
			t.Fatalf("ack=%s got=%s want=%s", item.ack, got, item.want)
		}
	}
}
