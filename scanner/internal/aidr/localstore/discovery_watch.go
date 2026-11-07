package localstore

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/fsnotify/fsnotify"
)

type discoveryWatch struct {
	watcher *fsnotify.Watcher
	dirty   atomic.Bool
	failed  atomic.Bool
	mu      sync.Mutex
	paths   map[string]fsnotify.Op
	done    chan struct{}
}

func (w *discoveryWatch) close() {
	w.watcher.Close()
	<-w.done
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
	watch := &discoveryWatch{watcher: w, paths: map[string]fsnotify.Op{}, done: make(chan struct{})}
	watch.dirty.Store(true)
	c.watch = watch
	// Windows Add waits on the same backend that delivers notifications.
	// Drain continuously so adding a directory cannot wait on this collector.
	go watch.consume(c.root)
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

func (w *discoveryWatch) consume(root string) {
	defer close(w.done)
	for {
		select {
		case event, ok := <-w.watcher.Events:
			if !ok {
				w.failed.Store(true)
				return
			}
			path := filepath.Clean(event.Name)
			if path != root && !strings.HasPrefix(path, root+string(os.PathSeparator)) && !strings.HasPrefix(root, path+string(os.PathSeparator)) {
				continue
			}
			w.mu.Lock()
			if len(w.paths) < 256 || w.paths[path] != 0 {
				w.paths[path] |= event.Op
			} else {
				w.failed.Store(true)
			}
			w.mu.Unlock()
			if event.Op&(fsnotify.Remove|fsnotify.Rename) != 0 && (path == root || strings.HasPrefix(root, path+string(os.PathSeparator))) {
				w.failed.Store(true)
			}
		case _, ok := <-w.watcher.Errors:
			w.failed.Store(true)
			if !ok {
				return
			}
		}
	}
}

func (c *Crawler) watchChanges() map[string]fsnotify.Op {
	if c.watch == nil || c.watch.failed.Load() {
		return nil
	}
	c.watch.mu.Lock()
	defer c.watch.mu.Unlock()
	paths := c.watch.paths
	c.watch.paths = map[string]fsnotify.Op{}
	return paths
}
