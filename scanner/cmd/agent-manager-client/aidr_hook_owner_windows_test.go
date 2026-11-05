package main

import (
	"context"
	"io"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
	"testing"
	"time"
)

func TestWindowsAutomaticHookRestart(t *testing.T) {
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:1", Token: "fictional-token"}); err != nil {
		t.Fatal(err)
	}
	_, paths, err := desktopBinding(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs := desktopPreferences{Enabled: true, HookMode: "audit", Hosts: map[string]desktopHost{}, RuntimePolicy: &desktopRuntimePolicy{Version: "1", Target: managedclient.RuntimeGovernancePolicy{Retry: managedclient.ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 10}}}}
	if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	prior := ""
	for i := 0; i < 2; i++ {
		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan struct{})
		go func() {
			defer close(done)
			manageAutomaticHooks(ctx, home, 20*time.Millisecond, func(ctx context.Context) error {
				return aidrHookServeContext(context.WithValue(ctx, managedHookContextKey{}, true), []string{"--managed-home", home}, io.Discard)
			})
		}()
		deadline := time.Now().Add(10 * time.Second)
		var reply hooks.IPCResponse
		for time.Now().Before(deadline) {
			reply, err = hooks.Exchange(ctx, paths.Socket, hooks.IPCRequest{Version: 1, Method: "GetHealth"})
			if err == nil {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
		if err != nil || reply.State == nil || reply.State.ReceiverInstance == "" || reply.State.ReceiverInstance == prior {
			cancel()
			<-done
			t.Fatal("receiver failed to restart", reply, err)
		}
		if !automaticHookReady(ctx, home) {
			cancel()
			<-done
			t.Fatal("daemon hook readiness false")
		}
		if release, err := acquireHookSupervisor(paths.Root); err == nil {
			release()
			cancel()
			<-done
			t.Fatal("second supervisor acquired ownership")
		}
		prior = reply.State.ReceiverInstance
		cancel()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
			t.Fatal("daemon receiver failed to drain")
		}
	}
}
