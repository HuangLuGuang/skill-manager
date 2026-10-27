package managedclient

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

type testSkillSource struct {
	changes    chan []string
	errors     chan error
	closed     atomic.Bool
	refreshErr error
	refreshes  atomic.Int32
}

func (s *testSkillSource) Changes() <-chan []string { return s.changes }
func (s *testSkillSource) Errors() <-chan error     { return s.errors }
func (s *testSkillSource) Refresh(string, *Store) error {
	s.refreshes.Add(1)
	return s.refreshErr
}
func (s *testSkillSource) SuppressRoots([]string, time.Duration) {}
func (s *testSkillSource) Close() error                          { s.closed.Store(true); return nil }

func TestHealthyWatcherRefreshesOnlyOnRequest(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	source := &testSkillSource{changes: make(chan []string, 1), errors: make(chan error, 1)}
	monitor, stop := startSkillMonitor(context.Background(), home, store, 10*time.Millisecond, func() (skillWatchSource, error) { return source, nil })
	defer stop()
	select {
	case <-monitor.Changes():
	case <-time.After(time.Second):
		t.Fatal("watcher did not start")
	}
	time.Sleep(50 * time.Millisecond)
	if got := source.refreshes.Load(); got != 1 {
		t.Fatalf("healthy source repeatedly refreshed: %d", got)
	}
	monitor.Refresh(home, store)
	deadline := time.Now().Add(time.Second)
	for source.refreshes.Load() == 1 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if got := source.refreshes.Load(); got != 2 {
		t.Fatalf("explicit refresh not delivered: %d", got)
	}
}

func TestWatcherFailuresDoNotStopDaemonAndRecover(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	gate := make(chan struct{})
	var attempts atomic.Int32
	sources := make(chan *testSkillSource, 10)
	monitor, stop := startSkillMonitor(ctx, home, store, 20*time.Millisecond, func() (skillWatchSource, error) {
		switch attempts.Add(1) {
		case 1:
			select {
			case <-gate:
			case <-ctx.Done():
			}
			return nil, errors.New("watcher_init_failure")
		case 2:
			return &testSkillSource{refreshErr: errors.New("watcher_refresh_failure")}, nil
		default:
			source := &testSkillSource{changes: make(chan []string, 1), errors: make(chan error, 1)}
			sources <- source
			return source, nil
		}
	})
	defer stop()
	previous := AIDRHookRunner
	defer func() { AIDRHookRunner = previous }()
	hookStarted, hookStopped := make(chan struct{}), make(chan struct{})
	AIDRHookRunner = func(ctx context.Context, _ string) { close(hookStarted); <-ctx.Done(); close(hookStopped) }
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests.Add(1); w.WriteHeader(503) }))
	defer server.Close()
	done := make(chan error, 1)
	go func() {
		done <- RunDaemon(ctx, home, NewAPI(server.URL, "token", time.Second), store, 50*time.Millisecond, monitor)
	}()
	defer func() { cancel(); <-done }()
	select {
	case <-hookStarted:
	case <-time.After(3 * time.Second):
		t.Fatal("watcher blocked Hook startup")
	}
	close(gate)
	var first *testSkillSource
	select {
	case first = <-sources:
	case <-time.After(3 * time.Second):
		t.Fatal("watcher did not recover initialization/refresh failure")
	}
	first.errors <- errors.New("watcher_runtime_failure")
	select {
	case <-sources:
	case <-time.After(3 * time.Second):
		t.Fatal("watcher did not recover runtime failure")
	}
	if !first.closed.Load() {
		t.Fatal("failed watcher resources not closed")
	}
	if requests.Load() == 0 {
		t.Fatal("daemon network loops did not run")
	}
	select {
	case <-hookStopped:
		t.Fatal("watcher failure stopped Hook")
	default:
	}
}

func TestWatcherRuntimeFailureImmediateRecoveryAndBackoff(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	sources := make(chan *testSkillSource, 10)
	monitor, stop := startSkillMonitor(context.Background(), home, store, time.Second, func() (skillWatchSource, error) {
		s := &testSkillSource{changes: make(chan []string, 1), errors: make(chan error, 1)}
		sources <- s
		return s, nil
	})
	defer stop()
	first := <-sources
	select {
	case <-monitor.Changes():
	case <-time.After(time.Second):
		t.Fatal("startup")
	}
	first.errors <- errors.New("bad file descriptor")
	var second *testSkillSource
	select {
	case second = <-sources:
	case <-time.After(500 * time.Millisecond):
		t.Fatal("first runtime failure waited for retry interval")
	}
	second.errors <- errors.New("repeated failure")
	select {
	case <-sources:
		t.Fatal("persistent errors cause immediate restart loop")
	case <-time.After(150 * time.Millisecond):
	}
	select {
	case <-sources:
	case <-time.After(2 * time.Second):
		t.Fatal("backoff did not recover")
	}
	if !first.closed.Load() || !second.closed.Load() {
		t.Fatal("failed watchers leaked")
	}
}
