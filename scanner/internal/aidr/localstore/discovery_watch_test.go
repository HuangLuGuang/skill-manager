package localstore

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/fsnotify/fsnotify"
)

func TestDiscoveryWatchOverflowAndBlockedClose(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	root := tempDir(t)
	c, err := s.NewCrawler("claude", root)
	if err != nil {
		t.Fatal(err)
	}
	if err = c.WatchChanges(); err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	delivered := make(chan struct{})
	go func() { c.watch.watcher.Errors <- fsnotify.ErrEventOverflow; close(delivered) }()
	deadline := time.Now().Add(time.Second)
	for !c.watch.failed.Load() && time.Now().Before(deadline) {
		c.prepareProbes()
		time.Sleep(time.Millisecond)
	}
	if !c.watch.failed.Load() {
		t.Fatal("overflow did not restore polling")
	}
	<-delivered
	if err = os.WriteFile(filepath.Join(root, "new.jsonl"), []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if p, err := c.Step(testContext, 64, 1000, time.Second); err != nil || p.Known != 1 {
		t.Fatal("overflow lost discovery", p, err)
	}
	closed := make(chan struct{})
	go func() { c.Close(); close(closed) }()
	select {
	case <-closed:
	case <-time.After(time.Second):
		t.Fatal("blocked notifier prevented close")
	}
}

func TestDiscoveryWatchIdleAndChanges(t *testing.T) {
	root := tempDir(t)
	s := openStore(t, tempDir(t), DefaultLimits())
	defer s.Close()
	path := filepath.Join(root, "session.jsonl")
	if err := os.WriteFile(path, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	idlePath := filepath.Join(root, "idle.jsonl")
	if err := os.WriteFile(idlePath, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := s.NewCrawler("claude", root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if err := c.WatchChanges(); err != nil {
		t.Fatal(err)
	}
	step := func() {
		t.Helper()
		if _, err := c.Step(testContext, 64, 1000, time.Second); err != nil {
			t.Fatal(err)
		}
	}
	step()
	step() // Probe newly enumerated files before measuring an idle pass.
	if c.watch.failed.Load() {
		t.Fatal("watch did not initialize")
	}
	probeTime := func() int64 {
		t.Helper()
		var stamp int64
		if err := s.db.QueryRow(`SELECT probe_ns FROM discovery_files WHERE path=?`, path).Scan(&stamp); err != nil {
			t.Fatal(err)
		}
		return stamp
	}
	before := probeTime()
	step()
	if probeTime() != before {
		t.Fatal("idle pass rewrote file probes")
	}
	ready, err := c.Ready(testContext, true, 32)
	if err != nil || len(ready) != 2 {
		t.Fatal(ready, err)
	}
	for _, source := range ready {
		if err := c.ReadDone(testContext, source, 3); err != nil {
			t.Fatal(err)
		}
	}
	var idleBefore int64
	if err := s.db.QueryRow(`SELECT probe_ns FROM discovery_files WHERE path=?`, idlePath).Scan(&idleBefore); err != nil {
		t.Fatal(err)
	}
	await := func(check func() bool) {
		t.Helper()
		deadline := time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			step()
			if check() {
				return
			}
			time.Sleep(5 * time.Millisecond)
		}
		t.Fatal("change not discovered")
	}
	if err := os.WriteFile(path, []byte("{}\n{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	await(func() bool { items, _ := c.Ready(testContext, true, 32); return len(items) == 1 })
	var idleAfter int64
	if err := s.db.QueryRow(`SELECT probe_ns FROM discovery_files WHERE path=?`, idlePath).Scan(&idleAfter); err != nil || idleAfter != idleBefore {
		t.Fatal("one file change reprobed an unchanged sibling", err)
	}
	newPath := filepath.Join(root, "nested", "new.jsonl")
	if err := os.MkdirAll(filepath.Dir(newPath), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(newPath, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	await(func() bool {
		var n int
		s.db.QueryRow(`SELECT count(*) FROM discovery_files WHERE path=?`, newPath).Scan(&n)
		return n == 1
	})
	if err := os.Rename(path, path+".old"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("replacement\n"), 0600); err != nil {
		t.Fatal(err)
	}
	await(func() bool {
		var size int
		s.db.QueryRow(`SELECT size FROM discovery_files WHERE path=?`, path).Scan(&size)
		return size == 12
	})
	// A missed event still causes a probe when the reconciliation deadline expires.
	c.watch.dirty.Store(false)
	c.nextProbe = time.Now().Add(-time.Second)
	before = probeTime()
	step()
	if probeTime() <= before {
		t.Fatal("periodic reconciliation did not probe")
	}
	// An overflow/closed notification stream falls back to per-round polling.
	c.watch.failed.Store(true)
	c.nextWatchRetry = time.Now().Add(time.Minute)
	before = probeTime()
	step()
	if probeTime() <= before {
		t.Fatal("failed watcher stopped polling")
	}
}

func TestDiscoveryWatchMissingRootAndRecreation(t *testing.T) {
	root := filepath.Join(tempDir(t), "logs")
	s := openStore(t, tempDir(t), DefaultLimits())
	defer s.Close()
	c, err := s.NewCrawler("claude", root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if err := c.WatchChanges(); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	for _, body := range []string{"first", "replacement"} {
		if err := os.MkdirAll(root, 0700); err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(root, "session.jsonl")
		if err := os.WriteFile(path, []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		deadline := time.Now().Add(3 * time.Second)
		found := false
		for time.Now().Before(deadline) {
			if _, err := c.Step(testContext, 64, 1000, time.Second); err != nil {
				t.Fatal(err)
			}
			var size int
			if err := s.db.QueryRow(`SELECT size FROM discovery_files WHERE path=?`, path).Scan(&size); err == nil && size == len(body) {
				found = true
				break
			}
			time.Sleep(5 * time.Millisecond)
		}
		if !found {
			t.Fatal("recreated root not discovered")
		}
		if err := os.RemoveAll(root); err != nil {
			t.Fatal(err)
		}
	}
}
