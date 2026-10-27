package localstore

import (
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	"github.com/fsnotify/fsnotify"
)

type discoveryWatch struct {
	watcher *fsnotify.Watcher
	dirty   atomic.Bool
	failed  atomic.Bool
}

func (w *discoveryWatch) close() {
	w.watcher.Close()
}

// WatchChanges lets the long-running collector avoid unchanged metadata probes.
// Polling remains available if the OS cannot provide a complete watch set.
func (c *Crawler) WatchChanges() error {
	c.watchRequested = true
	c.nextWatchRetry = time.Now().Add(c.RescanInterval)
	if c.watch != nil {
		c.watch.close()
		c.watch = nil
	}
	w, err := fsnotify.NewWatcher()
	if err != nil {
		return err
	}
	watch := &discoveryWatch{watcher: w}
	watch.dirty.Store(true)
	c.watch = watch
	rows, err := c.store.db.Query(`SELECT path FROM discovery_dirs WHERE root_key=?`, c.key)
	if err == nil {
		for rows.Next() {
			var path string
			if err = rows.Scan(&path); err != nil {
				break
			}
			c.watchDirectory(path)
		}
		if err == nil {
			err = rows.Err()
		}
		rows.Close()
	}
	if err != nil {
		watch.failed.Store(true)
	}
	return err
}

func (c *Crawler) watchDirectory(path string) {
	if c.watch == nil || c.watch.failed.Load() {
		return
	}
	// A missing root is observable through its nearest existing ancestor.
	for {
		info, err := safeInfo(path)
		if err == nil && info.IsDir() {
			if c.watch.watcher.Add(path) != nil {
				c.watch.failed.Store(true)
			}
			return
		}
		if err != nil && !os.IsNotExist(err) {
			c.watch.failed.Store(true)
			return
		}
		parent := filepath.Dir(path)
		if parent == path {
			c.watch.failed.Store(true)
			return
		}
		path = parent
	}
}

func (c *Crawler) prepareProbes() map[string]fsnotify.Op {
	now := time.Now()
	if c.watchRequested && (c.watch == nil || c.watch.failed.Load()) && !now.Before(c.nextWatchRetry) {
		_ = c.WatchChanges()
	}
	paths := c.watchChanges()
	if c.watch == nil || c.watch.failed.Load() {
		c.probeBefore = now.UnixNano()
		return nil
	}
	if c.watch.dirty.Swap(false) || !now.Before(c.nextProbe) {
		c.probeBefore = now.UnixNano()
		c.nextProbe = now.Add(c.RescanInterval)
	}
	return paths
}

// Consume notifications at the collector's cadence so the OS can coalesce writes.
func (c *Crawler) watchChanges() map[string]fsnotify.Op {
	if c.watch == nil || c.watch.failed.Load() {
		return nil
	}
	paths := map[string]fsnotify.Op{}
	add := func(event fsnotify.Event, ok bool) {
		if !ok {
			c.watch.failed.Store(true)
			return
		}
		path := filepath.Clean(event.Name)
		if path == c.root || strings.HasPrefix(path, c.root+string(os.PathSeparator)) || strings.HasPrefix(c.root, path+string(os.PathSeparator)) {
			paths[path] |= event.Op
			if event.Op&(fsnotify.Remove|fsnotify.Rename) != 0 && (path == c.root || strings.HasPrefix(c.root, path+string(os.PathSeparator))) {
				c.watch.failed.Store(true)
			}
		}
	}
	select {
	case event, ok := <-c.watch.watcher.Events:
		add(event, ok)
	case <-c.watch.watcher.Errors:
		c.watch.failed.Store(true)
		return nil
	default:
		return nil
	}
	// Allow the unbuffered fsnotify producer to deliver its queued batch, bounded
	// in both time and size so a continuously written root cannot starve intake.
	deadline := time.NewTimer(5 * time.Millisecond)
	defer deadline.Stop()
	for n := 1; n < 256 && !c.watch.failed.Load(); n++ {
		select {
		case event, ok := <-c.watch.watcher.Events:
			add(event, ok)
		case <-c.watch.watcher.Errors:
			c.watch.failed.Store(true)
			return paths
		case <-deadline.C:
			return paths
		}
	}
	c.watch.dirty.Store(true)
	return paths
}
