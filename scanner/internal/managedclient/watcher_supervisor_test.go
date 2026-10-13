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
}

func (s *testSkillSource) Changes() <-chan []string              { return s.changes }
func (s *testSkillSource) Errors() <-chan error                  { return s.errors }
func (s *testSkillSource) Refresh(string, *Store) error          { return s.refreshErr }
func (s *testSkillSource) SuppressRoots([]string, time.Duration) {}
func (s *testSkillSource) Close() error                          { s.closed.Store(true); return nil }

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
