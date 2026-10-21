package managedclient

import (
	"context"
	"path/filepath"
	"time"

	"github.com/fsnotify/fsnotify"
)

const eventWakeFile = "events-wake"
const eventRepairInterval = 30 * time.Second

func eventUploadDelay(store *Store, server string) time.Duration {
	var pending bool
	if err := store.db.QueryRow(`SELECT EXISTS(SELECT 1 FROM client_events_queue WHERE server=? AND sealed>=0)`, server).Scan(&pending); err != nil || !pending {
		return eventRepairInterval
	}
	if cachedPolicy(store).OrdinaryEventsProtocol < 1 {
		return eventRepairInterval
	}
	var due int64
	_ = store.db.QueryRow(`SELECT MAX(next_send,retry_at,lease_until) FROM client_event_sender WHERE server=?`, server).Scan(&due)
	delay := time.Until(time.UnixMilli(due))
	if delay < 100*time.Millisecond {
		return 100 * time.Millisecond
	}
	if delay > eventRepairInterval {
		return eventRepairInterval
	}
	return delay
}

func runEventUploader(ctx context.Context, api API, store *Store) {
	var changes <-chan fsnotify.Event
	var errors <-chan error
	if watcher, err := fsnotify.NewWatcher(); err == nil {
		defer watcher.Close()
		if err := watcher.Add(store.root); err == nil {
			changes, errors = watcher.Events, watcher.Errors
		}
	}
	// The durable queue is authoritative; the timer repairs missed filesystem hints.
	timer := time.NewTimer(0)
	defer timer.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case event, ok := <-changes:
			if !ok {
				changes = nil
				continue
			}
			if filepath.Base(event.Name) != eventWakeFile {
				continue
			}
		case _, ok := <-errors:
			if !ok {
				errors = nil
			}
		case <-timer.C:
		}
		if ctx.Err() != nil {
			return
		}
		request, cancel := context.WithTimeout(ctx, 30*time.Second)
		_ = flushEvents(request, api, store)
		cancel()
		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
		timer.Reset(eventUploadDelay(store, api.server))
	}
}
