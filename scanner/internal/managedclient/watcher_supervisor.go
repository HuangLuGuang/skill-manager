package managedclient

import (
	"context"
	"errors"
	"sync"
	"time"
)

type SkillMonitor interface {
	Changes() <-chan []string
	Refresh(string, *Store) error
	SuppressRoots([]string, time.Duration)
}

type skillWatchSource interface {
	SkillMonitor
	Errors() <-chan error
	Close() error
}

// A failed directory monitor is recoverable independently of Hook intake,
// heartbeat and task execution. Periodic patrol remains the compensating path.
type resilientSkillMonitor struct {
	mu      sync.Mutex
	source  skillWatchSource
	changes chan []string
	refresh chan struct{}
}

func (m *resilientSkillMonitor) Changes() <-chan []string { return m.changes }
func (m *resilientSkillMonitor) Refresh(string, *Store) error {
	select {
	case m.refresh <- struct{}{}:
	default:
	}
	return nil
}
func (m *resilientSkillMonitor) SuppressRoots(paths []string, duration time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.source != nil {
		m.source.SuppressRoots(paths, duration)
	}
}

func StartSkillMonitor(ctx context.Context, home string, store *Store) (SkillMonitor, func()) {
	return startSkillMonitor(ctx, home, store, 30*time.Second, func() (skillWatchSource, error) { return NewSkillWatcher() })
}

func startSkillMonitor(parent context.Context, home string, store *Store, retry time.Duration, factory func() (skillWatchSource, error)) (*resilientSkillMonitor, func()) {
	ctx, cancel := context.WithCancel(parent)
	m := &resilientSkillMonitor{changes: make(chan []string, 1), refresh: make(chan struct{}, 1)}
	done := make(chan struct{})
	go func() {
		defer close(done)
		var retryTimer *time.Timer
		var retryC <-chan time.Time
		retryDelay := min(time.Second, retry)
		defer func() {
			if retryTimer != nil {
				retryTimer.Stop()
			}
		}()
		scheduleRetry := func() {
			if retryTimer == nil {
				retryTimer = time.NewTimer(retryDelay)
			} else {
				retryTimer.Reset(retryDelay)
			}
			retryC = retryTimer.C
			retryDelay = min(2*retryDelay, retry)
		}
		var nextImmediate time.Time
		var source skillWatchSource
		closeSource := func() {
			m.mu.Lock()
			m.source = nil
			m.mu.Unlock()
			if source != nil {
				_ = source.Close()
				source = nil
			}
		}
		defer closeSource()
		changed := func(paths []string) {
			select {
			case m.changes <- paths:
			default:
				// A full queue may lose path detail; request a compensating scan.
				select {
				case <-m.changes:
				default:
				}
				select {
				case m.changes <- nil:
				default:
				}
			}
		}
		refresh := func() {
			if ctx.Err() != nil {
				return
			}
			newSource := source == nil
			var err error
			if newSource {
				source, err = factory()
			}
			if err == nil {
				err = source.Refresh(home, store)
			}
			syncError(store, "watcher", err)
			if err != nil {
				closeSource()
				changed(nil)
				scheduleRetry()
				return
			}
			m.mu.Lock()
			m.source = source
			m.mu.Unlock()
			if newSource {
				changed(nil)
			}
		}
		recoverSource := func(err error) {
			syncError(store, "watcher", err)
			closeSource()
			changed(nil)
			if !time.Now().Before(nextImmediate) {
				retryDelay = min(time.Second, retry)
				nextImmediate = time.Now().Add(retry)
				refresh()
			} else {
				scheduleRetry()
			}
		}
		refresh()
		for {
			var changes <-chan []string
			var failures <-chan error
			if source != nil {
				changes, failures = source.Changes(), source.Errors()
			}
			select {
			case <-ctx.Done():
				return
			case <-retryC:
				retryC = nil
				if source == nil {
					nextImmediate = time.Now().Add(retry)
					refresh()
				}
			case <-m.refresh:
				// Creation failures retry on the timer, not on every compensating scan.
				if source != nil {
					refresh()
				}
			case paths, ok := <-changes:
				if ok {
					changed(paths)
				} else {
					recoverSource(errors.New("skill_watcher_closed"))
				}
			case err, ok := <-failures:
				if !ok || err == nil {
					err = errors.New("skill_watcher_closed")
				}
				recoverSource(err)
			}
		}
	}()
	return m, func() { cancel(); <-done }
}
