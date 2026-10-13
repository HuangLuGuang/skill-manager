//go:build darwin || linux

package main

import (
	"context"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func managedHookTestHome(t *testing.T) (string, desktopPaths) {
	t.Helper()
	home := shortDesktopTestHome(t)
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
	return home, paths
}

func waitHookTest(t *testing.T, check func() bool) {
	t.Helper()
	deadline := time.Now().Add(8 * time.Second)
	for time.Now().Before(deadline) {
		if check() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("Hook condition timed out")
}

func TestManagedHookReceiverSharesProcessAndSurvivesObserverExit(t *testing.T) {
	home, paths := managedHookTestHome(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		manageAutomaticHooks(ctx, home, 10*time.Millisecond, func(ctx context.Context) error {
			return aidrHookServeContext(context.WithValue(ctx, managedHookContextKey{}, true), []string{"--managed-home", home}, io.Discard)
		})
	}()
	t.Cleanup(func() { cancel(); <-done })
	var first hooks.IPCResponse
	waitHookTest(t, func() bool {
		var err error
		first, err = hooks.Exchange(ctx, paths.Socket, hooks.IPCRequest{Version: 1, Method: "GetHealth"})
		return err == nil
	})
	if first.Receiver == nil || first.Receiver.PID != os.Getpid() {
		t.Fatal("receiver spawned another process")
	}
	for i := 0; i < 3; i++ {
		observer, closeObserver := context.WithCancel(context.Background())
		status := hookReceiverSnapshot(observer, home)
		closeObserver()
		if status["code"] != "aidr_desktop_running" {
			t.Fatalf("observer status: %v", status["code"])
		}
	}
	if err := requestHookRetry(paths); err != nil {
		t.Fatal(err)
	}
	time.Sleep(50 * time.Millisecond)
	after, err := hooks.Exchange(ctx, paths.Socket, hooks.IPCRequest{Version: 1, Method: "GetHealth"})
	if err != nil || after.State.ReceiverInstance != first.State.ReceiverInstance {
		t.Fatal("observer or retry restarted healthy receiver", err)
	}
	// Offline upload cannot stop IPC. A native audit Hook still receives a reply.
	id, _ := hooks.NewEventID()
	reply, err := hooks.Exchange(ctx, paths.Socket, hooks.IPCRequest{Version: 1, Method: "SubmitEvent", EventID: id, Agent: "claude", Hook: "PreToolUse", Raw: []byte(`{"hook_event_name":"PreToolUse","session_id":"daemon-test","tool_name":"Read","tool_input":{"file_path":"/tmp/fictional"}}`)})
	if err != nil || reply.Accepted != 1 {
		t.Fatalf("Hook failed while UI absent: code=%s accepted=%d err=%v", reply.Code, reply.Accepted, err)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("daemon failed to join receiver")
	}
	if _, err = os.Lstat(paths.Socket); !os.IsNotExist(err) {
		t.Fatal("owned socket not cleaned up")
	}
}

func TestManagedHookRetryPersistsAcrossDaemonRestarts(t *testing.T) {
	home, paths := managedHookTestHome(t)
	var starts atomic.Int32
	run := func() (context.CancelFunc, chan struct{}) {
		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan struct{})
		go func() {
			defer close(done)
			manageAutomaticHooks(ctx, home, 10*time.Millisecond, func(context.Context) error { starts.Add(1); return errors.New("aidr_desktop_receiver_failed") })
		}()
		return cancel, done
	}
	cancel, done := run()
	waitHookTest(t, func() bool {
		var s hookSupervision
		return readDesktopJSON(filepath.Join(paths.Root, "receiver-supervisor.json"), &s) == nil && s.Suspended
	})
	cancel()
	<-done
	cancel, done = run()
	defer func() { cancel(); <-done }()
	time.Sleep(80 * time.Millisecond)
	if starts.Load() != 1 {
		t.Fatal("restart erased retry budget")
	}
	if err := requestHookRetry(paths); err != nil {
		t.Fatal(err)
	}
	waitHookTest(t, func() bool { return starts.Load() == 2 })
}

func TestManagedHookWaitsForOldDesktopSupervisor(t *testing.T) {
	home, paths := managedHookTestHome(t)
	release, err := acquireHookSupervisor(paths.Root)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	var starts atomic.Int32
	go func() {
		defer close(done)
		manageAutomaticHooks(ctx, home, 10*time.Millisecond, func(ctx context.Context) error { starts.Add(1); <-ctx.Done(); return nil })
	}()
	defer func() { cancel(); <-done }()
	time.Sleep(50 * time.Millisecond)
	if starts.Load() != 0 {
		t.Fatal("started alongside legacy desktop")
	}
	if _, err := os.Stat(filepath.Join(paths.Root, "receiver-supervisor.json")); !os.IsNotExist(err) {
		t.Fatal("overwrote legacy owner's state")
	}
	release()
	waitHookTest(t, func() bool { return starts.Load() == 1 })
}

func TestManagedHookPolicyDisableAndEnableWithNoRetries(t *testing.T) {
	home, paths := managedHookTestHome(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	var starts atomic.Int32
	go func() {
		defer close(done)
		manageAutomaticHooks(ctx, home, 10*time.Millisecond, func(ctx context.Context) error { starts.Add(1); <-ctx.Done(); return nil })
	}()
	defer func() { cancel(); <-done }()
	waitHookTest(t, func() bool { return starts.Load() == 1 })
	prefs, err := loadDesktopPreferences(home)
	if err != nil {
		t.Fatal(err)
	}
	prefs.Enabled = false
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	waitHookTest(t, func() bool {
		var state hookSupervision
		return readDesktopJSON(filepath.Join(paths.Root, "receiver-supervisor.json"), &state) == nil && state.Code == "aidr_desktop_disabled"
	})
	prefs.Enabled = true
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		t.Fatal(err)
	}
	waitHookTest(t, func() bool { return starts.Load() == 2 })
}

func TestManagedHookSocketRecoveryPreservesUnknownAndLiveSockets(t *testing.T) {
	_, paths := managedHookTestHome(t)
	store, err := hooks.OpenStore(paths.State, "http://127.0.0.1:1", paths.Device, 10)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	r, err := hooks.Listen(paths.Socket, store)
	if err != nil {
		t.Fatal(err)
	}
	proof, err := r.SocketIdentity()
	if err != nil {
		t.Fatal(err)
	}
	if err = writeDesktopJSON(paths.Socket+".owner.json", proof); err != nil {
		t.Fatal(err)
	}
	if recoverManagedHookSocket(paths.Socket) == nil {
		t.Fatal("removed live socket")
	}
	r.Close()
	// A newly created endpoint is not the journaled receiver's inode.
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: paths.Socket, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	l.SetUnlinkOnClose(false)
	l.Close()
	defer os.Remove(paths.Socket)
	// A mismatched journal must never authorize unlinking an unknown endpoint.
	proof["inode"] = "0"
	_ = writeDesktopJSON(paths.Socket+".owner.json", proof)
	if recoverManagedHookSocket(paths.Socket) == nil {
		t.Fatal("removed replacement socket")
	}
	info, err := os.Lstat(paths.Socket)
	if err != nil {
		t.Fatal(err)
	}
	stat := info.Sys().(*syscall.Stat_t)
	proof["device"], proof["inode"] = strconv.FormatUint(uint64(stat.Dev), 10), strconv.FormatUint(stat.Ino, 10)
	if err = writeDesktopJSON(paths.Socket+".owner.json", proof); err != nil {
		t.Fatal(err)
	}
	if err = recoverManagedHookSocket(paths.Socket); err != nil {
		t.Fatal("failed to recover journaled dead listener", err)
	}
	if _, err = os.Lstat(paths.Socket); !os.IsNotExist(err) {
		t.Fatal("dead socket was retained")
	}
}
