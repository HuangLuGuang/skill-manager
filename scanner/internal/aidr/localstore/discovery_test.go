package localstore

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"testing"
	"time"
)

func TestUnchangedReadProgressBatchRollbackAndRestart(t *testing.T) {
	const count = 129
	dir, root := tempDir(t), tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	var sources []agentlog.Source
	for i := 0; i < count; i++ {
		path := filepath.Join(root, fmt.Sprintf("%d.jsonl", i))
		if err := os.WriteFile(path, nil, 0600); err != nil {
			t.Fatal(err)
		}
		src, err := agentlog.NewSource("claude", root, path)
		if err != nil {
			t.Fatal(err)
		}
		sources = append(sources, src)
	}
	c, err := s.NewCrawler("claude", root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Step(testContext, 256, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	for _, src := range sources {
		collect(t, s, src)
	}
	if _, err = s.db.Exec(`UPDATE discovery_files SET pending=1,read_ns=0`); err != nil {
		t.Fatal(err)
	}
	if _, err = s.db.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`); err != nil {
		t.Fatal(err)
	}
	for _, src := range sources {
		if _, err = c.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0).UTC()); err != nil {
			t.Fatal(err)
		}
	}
	if info, err := os.Stat(filepath.Join(dir, "state.db-wal")); err != nil || info.Size() != 0 {
		t.Fatal("unchanged reads wrote WAL before batch flush", info, err)
	}
	if _, err = s.db.Exec(`CREATE TRIGGER fail_progress BEFORE UPDATE ON discovery_files WHEN NEW.read_ns>0 BEGIN SELECT RAISE(ABORT,'progress failure'); END`); err != nil {
		t.Fatal(err)
	}
	if err = c.FlushReadProgress(testContext); err == nil {
		t.Fatal("expected flush failure")
	}
	var pending int
	if err = s.db.QueryRow(`SELECT sum(pending) FROM discovery_files`).Scan(&pending); err != nil || pending != count || len(c.readProgress) != count {
		t.Fatal("failed batch lost progress", pending, err)
	}
	if _, err = s.db.Exec(`DROP TRIGGER fail_progress`); err != nil {
		t.Fatal(err)
	}
	if err = c.FlushReadProgress(testContext); err != nil {
		t.Fatal(err)
	}
	if err = s.db.QueryRow(`SELECT sum(pending) FROM discovery_files`).Scan(&pending); err != nil || pending != 0 || len(c.readProgress) != 0 {
		t.Fatal("batch not persisted", pending, err)
	}
	// Discard an unflushed round; its durable checkpoint remains available for retry.
	if _, err = s.db.Exec(`UPDATE discovery_files SET pending=1,read_ns=0`); err != nil {
		t.Fatal(err)
	}
	for _, src := range sources {
		if _, err = c.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0).UTC()); err != nil {
			t.Fatal(err)
		}
	}
	ctx, cancel := context.WithCancel(testContext)
	cancel()
	if err = c.FlushReadProgress(ctx); err == nil {
		t.Fatal("cancelled flush succeeded")
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, DefaultLimits())
	restarted, err := s.NewCrawler("claude", root)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	ready, err := restarted.Ready(testContext, true, 32)
	if err != nil || len(ready) != 32 {
		t.Fatal("unflushed sources were skipped", len(ready), err)
	}
	for _, src := range ready {
		checkpoint, err := restarted.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0).UTC())
		if err != nil || checkpoint.Revision == 0 {
			t.Fatal("durable checkpoint lost", checkpoint, err)
		}
	}
	if err = restarted.FlushReadProgress(testContext); err != nil {
		t.Fatal(err)
	}
}

func TestDiscoveryReadProgressCommitsWithCheckpoint(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	src := source(t, lines(2))
	c, err := s.NewCrawler(src.Agent, src.Root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	if _, err = s.db.Exec(`CREATE TRIGGER fail_source BEFORE INSERT ON sources BEGIN SELECT RAISE(ABORT,'checkpoint failure'); END`); err != nil {
		t.Fatal(err)
	}
	if _, err = c.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0)); err == nil {
		t.Fatal("expected checkpoint failure")
	}
	var read int64
	var pending int
	if err = s.db.QueryRow(`SELECT read_ns,pending FROM discovery_files WHERE id=?`, src.ID).Scan(&read, &pending); err != nil || read != 0 || pending != 1 {
		t.Fatal("failed commit advanced discovery", read, pending, err)
	}
	if _, err = s.db.Exec(`DROP TRIGGER fail_source`); err != nil {
		t.Fatal(err)
	}
	if _, err = c.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0)); err != nil {
		t.Fatal(err)
	}
	if err = s.db.QueryRow(`SELECT read_ns,pending FROM discovery_files WHERE id=?`, src.ID).Scan(&read, &pending); err != nil || read == 0 || pending != 0 {
		t.Fatal("successful checkpoint did not complete discovery", read, pending, err)
	}
}

func TestReadProgressCannotOverwriteNewCheckpoint(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	src := source(t, "")
	c, err := s.NewCrawler(src.Agent, src.Root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	collect(t, s, src)
	if _, err = c.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0).UTC()); err != nil {
		t.Fatal(err)
	}
	old := c.readProgress[src.ID]
	if old.revision == 0 {
		t.Fatal("missing unchanged read marker")
	}
	for i := 1; i <= 2; i++ {
		body := strings.ReplaceAll(lines(i), "2026-09-23T01:00:00Z", time.Now().UTC().Format(time.RFC3339))
		if err = os.WriteFile(src.Path, []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		read := c.Collect
		if i == 2 {
			read = s.Collect
		}
		current, err := read(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0).UTC())
		if err != nil || current.Revision <= old.revision || current.Cursor.Offset != int64(len(body)) {
			t.Fatal("new data was deferred", current, err)
		}
		if i == 1 && len(c.readProgress) != 0 {
			t.Fatal("new checkpoint retained stale progress")
		}
		stored, err := s.Checkpoint(testContext, src.ID)
		if err != nil || stored.Revision != current.Revision {
			t.Fatal("checkpoint was not durable", stored, err)
		}
		var before, after int64
		if err = s.db.QueryRow(`SELECT read_ns FROM discovery_files WHERE id=?`, src.ID).Scan(&before); err != nil {
			t.Fatal(err)
		}
		c.readProgress[src.ID] = old
		if err = c.FlushReadProgress(testContext); err != nil {
			t.Fatal(err)
		}
		if err = s.db.QueryRow(`SELECT read_ns FROM discovery_files WHERE id=?`, src.ID).Scan(&after); err != nil || before != after {
			t.Fatal("stale marker overwrote checkpoint progress", before, after, err)
		}
	}
}

func TestDiscoveryProgressActivityRestartAndRotation(t *testing.T) {
	for _, agent := range []string{"claude", "codex"} {
		t.Run(agent, func(t *testing.T) {
			root := tempDir(t)
			dir := filepath.Join(root, "2025", "01", "01")
			os.MkdirAll(dir, 0700)
			old := time.Now().Add(-48 * time.Hour)
			for i := 0; i < 240; i++ {
				p := filepath.Join(dir, fmt.Sprintf("history-%03d.jsonl", i))
				os.WriteFile(p, []byte("{}\n"), 0600)
				os.Chtimes(p, old, old)
			}
			state := tempDir(t)
			s := openStore(t, state, DefaultLimits())
			c, e := s.NewCrawler(agent, root)
			if e != nil {
				t.Fatal(e)
			}
			seen := map[string]bool{}
			budgetSeen := false
			for i := 0; i < 24; i++ {
				p, e := c.Step(testContext, 31, 200, time.Second)
				if e != nil {
					t.Fatal(e)
				}
				for _, code := range p.Reasons {
					if code == "aidr_log_discovery_budget" {
						budgetSeen = true
					}
				}
				items, e := c.Ready(testContext, false, 20)
				if e != nil {
					t.Fatal(e)
				}
				for _, src := range items {
					seen[src.ID] = true
					if e = c.ReadDone(testContext, src, 3); e != nil {
						t.Fatal(e)
					}
				}
				if i == 3 {
					c.Close()
					s.Close()
					s = openStore(t, state, DefaultLimits())
					c, e = s.NewCrawler(agent, root)
					if e != nil {
						t.Fatal(e)
					}
				}
			}
			defer s.Close()
			defer c.Close()
			if len(seen) != 240 || !budgetSeen {
				t.Fatal("frontier starvation", len(seen), budgetSeen)
			}
			// A new source in an old date directory is discovered; an existing source
			// becomes active again without changing its source identity or read cursor.
			fresh := filepath.Join(dir, "new-session.jsonl")
			os.WriteFile(fresh, []byte("{}\n"), 0600)
			appendPath := filepath.Join(dir, "history-000.jsonl")
			f, _ := os.OpenFile(appendPath, os.O_APPEND|os.O_WRONLY, 0600)
			f.WriteString("{}\n")
			f.Close()
			found := map[string]bool{}
			for i := 0; i < 14; i++ {
				if _, e = c.Step(testContext, 31, 200, time.Second); e != nil {
					t.Fatal(e)
				}
				items, e := c.Ready(testContext, true, 32)
				if e != nil {
					t.Fatal(e)
				}
				for _, src := range items {
					found[src.Path] = true
					c.ReadDone(testContext, src, 999)
				}
			}
			if !found[fresh] || !found[appendPath] {
				t.Fatal("active sources missing", found)
			}
			os.Rename(appendPath, appendPath+".old")
			os.WriteFile(appendPath, []byte("replacement\n"), 0600)
			for i := 0; i < 4; i++ {
				c.Step(testContext, 31, 200, time.Second)
			}
			items, _ := c.Ready(testContext, true, 32)
			rotated := false
			for _, src := range items {
				if src.Path == appendPath {
					rotated = true
				}
			}
			if !rotated {
				t.Fatal("rotation not scheduled")
			}
		})
	}
}

func TestDiscoveryPreservesExistingEventCursor(t *testing.T) {
	src := source(t, lines(1))
	s := openStore(t, tempDir(t), DefaultLimits())
	defer s.Close()
	before, e := s.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0))
	if e != nil {
		t.Fatal(e)
	}
	c, e := s.NewCrawler(src.Agent, src.Root)
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	c.Step(testContext, 64, 1000, time.Second)
	after, e := s.Checkpoint(testContext, src.ID)
	if e != nil {
		t.Fatal(e)
	}
	if before.Cursor.Offset != after.Cursor.Offset || before.Revision != after.Revision {
		t.Fatal("discovery changed ingestion cursor")
	}
}

func TestDiscoveryBudgetsAndSameMetadataRotation(t *testing.T) {
	root := tempDir(t)
	path := filepath.Join(root, "one.jsonl")
	if e := os.WriteFile(path, []byte("{}\n"), 0600); e != nil {
		t.Fatal(e)
	}
	s := openStore(t, tempDir(t), DefaultLimits())
	defer s.Close()
	c, e := s.NewCrawler("codex", root)
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	c.Step(testContext, 64, 100, time.Second)
	src, _ := agentlog.NewSource("codex", root, path)
	c.ReadDone(testContext, src, 3)
	info, _ := os.Stat(path)
	os.Rename(path, path+".old")
	os.WriteFile(path, []byte("[]\n"), 0600)
	os.Chtimes(path, info.ModTime(), info.ModTime())
	// Simulate an elapsed periodic identity-validation interval without sleeping.
	s.db.Exec("UPDATE discovery_files SET read_ns=1")
	c.Step(testContext, 64, 100, time.Second)
	ready, e := c.Ready(testContext, true, 32)
	if e != nil || len(ready) != 1 {
		t.Fatal("same metadata rotation starved", len(ready), e)
	}
	if _, e = c.Ready(testContext, true, 1000000); e == nil {
		t.Fatal("unbounded read batch")
	}
	if _, e = c.Step(testContext, 65, 10001, time.Second); e == nil {
		t.Fatal("unbounded entry budget")
	}
}

func TestDiscoveryCapacityAndPersistentSkippedEntry(t *testing.T) {
	root := tempDir(t)
	for _, name := range []string{"a.jsonl", "b.jsonl"} {
		os.WriteFile(filepath.Join(root, name), []byte("{}\n"), 0600)
	}
	os.Symlink(filepath.Join(root, "a.jsonl"), filepath.Join(root, "linked.jsonl"))
	limits := DefaultLimits()
	limits.Sources = 1
	s := openStore(t, tempDir(t), limits)
	defer s.Close()
	c, e := s.NewCrawler("codex", root)
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	for i := 0; i < 2; i++ {
		p, e := c.Step(testContext, 64, 100, time.Second)
		if e != nil {
			t.Fatal(e)
		}
		has := func(code string) bool {
			for _, v := range p.Reasons {
				if v == code {
					return true
				}
			}
			return false
		}
		if p.Known != 1 || p.Status != "partial" || !has("aidr_log_discovery_capacity") || !has("aidr_log_symlink") {
			t.Fatal(p)
		}
	}
}

func TestMissingDiscoverySeparatesReadHistoryFromUnreadFiles(t *testing.T) {
	src := source(t, lines(1))
	s := openStore(t, tempDir(t), DefaultLimits())
	defer s.Close()
	checkpoint, err := s.Collect(testContext, src, agentlog.DefaultBudget(), time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	c, err := s.NewCrawler(src.Agent, src.Root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(src.Path); err != nil {
		t.Fatal(err)
	}
	p, err := c.Step(testContext, 64, 1000, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if p.HistoricalMissing != 1 || p.UnreadMissing != 0 || p.Pending != 0 {
		t.Fatalf("history classification: %+v", p)
	}
	for _, reason := range p.Reasons {
		if reason == "aidr_log_source_missing" {
			t.Fatal("read history marked current missing")
		}
	}
	// The retained discovery size exceeds the read cursor: missing content remains actionable.
	if _, err = s.db.Exec("UPDATE discovery_files SET size=? WHERE id=?", checkpoint.Cursor.Offset+100, src.ID); err != nil {
		t.Fatal(err)
	}
	p, err = c.Step(testContext, 64, 1000, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if p.HistoricalMissing != 0 || p.UnreadMissing != 1 {
		t.Fatalf("unread classification: %+v", p)
	}
	found := false
	for _, reason := range p.Reasons {
		found = found || reason == "aidr_log_source_missing"
	}
	if !found {
		t.Fatal("unread missing file must remain actionable")
	}
	after, err := s.Checkpoint(testContext, src.ID)
	if err != nil || after.Cursor.Offset != checkpoint.Cursor.Offset {
		t.Fatal("missing classification changed cursor", err)
	}
	// An unfinished context repair stays actionable even if the main cursor reached EOF.
	repair := checkpoint.Cursor
	checkpoint.Cursor.ContextRepair = &repair
	body, _ := json.Marshal(checkpoint.Cursor)
	if _, err = s.db.Exec(`UPDATE discovery_files SET size=0 WHERE id=?`, src.ID); err != nil {
		t.Fatal(err)
	}
	if _, err = s.db.Exec(`UPDATE sources SET cursor=? WHERE id=?`, string(body), src.ID); err != nil {
		t.Fatal(err)
	}
	p, err = c.Step(testContext, 64, 1000, time.Second)
	if err != nil || p.HistoricalMissing != 0 || p.UnreadMissing != 1 {
		t.Fatal("context repair was hidden as completed history", p, err)
	}
}

func TestMissingSourceRetryAndRecovery(t *testing.T) {
	src := source(t, "{}\n")
	info, err := os.Stat(src.Path)
	if err != nil {
		t.Fatal(err)
	}
	s := openStore(t, tempDir(t), DefaultLimits())
	c, err := s.NewCrawler(src.Agent, src.Root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	step := func() {
		t.Helper()
		if _, err := c.Step(testContext, 64, 10000, time.Second); err != nil {
			t.Fatal(err)
		}
	}
	ready := func(want int) {
		t.Helper()
		items, err := c.Ready(testContext, true, 32)
		if err != nil || len(items) != want {
			t.Fatalf("ready=%d want=%d err=%v", len(items), want, err)
		}
	}
	done := func() {
		t.Helper()
		if err := c.ReadDone(testContext, src, 0); err != nil {
			t.Fatal(err)
		}
	}
	step()
	ready(1)
	done()
	if err := os.Remove(src.Path); err != nil {
		t.Fatal(err)
	}
	step()
	ready(1)
	done()
	step()
	ready(0)
	if _, err := s.db.Exec(`UPDATE discovery_files SET read_ns=? WHERE id=?`, time.Now().Add(-time.Minute).UnixNano(), src.ID); err != nil {
		t.Fatal(err)
	}
	ready(1)
	done()
	if err := os.WriteFile(src.Path, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(src.Path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	step()
	ready(1)
}

func TestDiscoveryTransactionRollsBackAndResumes(t *testing.T) {
	src := source(t, "{}\n")
	s := openStore(t, tempDir(t), DefaultLimits())
	c, err := s.NewCrawler(src.Agent, src.Root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = s.db.Exec(`CREATE TRIGGER fail_discovery BEFORE INSERT ON discovery_files BEGIN SELECT RAISE(ABORT,'test failure'); END`); err != nil {
		t.Fatal(err)
	}
	if _, err = c.Step(testContext, 64, 10000, time.Second); err == nil {
		t.Fatal("write failure ignored")
	}
	var probed int
	if err = s.db.QueryRow(`SELECT count(*) FROM discovery_dirs WHERE probe_ns!=0 OR visited_ns!=0`).Scan(&probed); err != nil || probed != 0 {
		t.Fatal("partial probe committed", probed, err)
	}
	if _, err = s.db.Exec(`DROP TRIGGER fail_discovery`); err != nil {
		t.Fatal(err)
	}
	if _, err = c.Step(testContext, 64, 10000, time.Second); err != nil {
		t.Fatal(err)
	}
	ready, err := c.Ready(testContext, true, 32)
	if err != nil || len(ready) != 1 || ready[0].ID != src.ID {
		t.Fatal("source skipped after rollback", ready, err)
	}
}

func TestReadyCheckpointConsumedOnceAndInvalidated(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	src := source(t, lines(1))
	collect(t, s, src)
	c, err := s.NewCrawler(src.Agent, src.Root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err = c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	ready := func() {
		t.Helper()
		if _, err = s.db.Exec(`UPDATE discovery_files SET pending=1`); err != nil {
			t.Fatal(err)
		}
		if _, err = c.Ready(testContext, true, 32); err != nil {
			t.Fatal(err)
		}
		if len(s.readCheckpoints) != 1 {
			t.Fatal("checkpoint not prefetched")
		}
	}
	ready()
	ctx, cancel := context.WithCancel(testContext)
	cancel()
	if _, err = s.checkpointForRead(ctx, src.ID); err != context.Canceled || len(s.readCheckpoints) != 1 {
		t.Fatal("cancellation consumed checkpoint", err)
	}
	first, err := s.checkpointForRead(testContext, src.ID)
	if err != nil || first.Revision == 0 || len(s.readCheckpoints) != 0 {
		t.Fatal(first, err)
	}
	ready()
	batch, err := agentlog.ReadIncremental(testContext, src, first.Cursor, agentlog.DefaultBudget(), time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	current, err := s.Commit(testContext, first, batch)
	if err != nil || current.Revision <= first.Revision || len(s.readCheckpoints) != 0 {
		t.Fatal("commit retained stale checkpoint", err)
	}
	got, err := s.checkpointForRead(testContext, src.ID)
	if err != nil || got.Revision != current.Revision {
		t.Fatal("stale checkpoint returned", got, err)
	}
	ready()
	if _, err = s.Prune(testContext, time.Now()); err != nil || len(s.readCheckpoints) != 0 {
		t.Fatal("prune retained checkpoint", err)
	}
	ready()
	if err = s.Close(); err != nil || len(s.readCheckpoints) != 0 {
		t.Fatal("close retained checkpoint", err)
	}
	if _, err = s.checkpointForRead(testContext, src.ID); err == nil {
		t.Fatal("closed store returned cached success")
	}
}

func TestReadyCheckpointPrefetchByteBudget(t *testing.T) {
	s := openStore(t, tempDir(t), DefaultLimits())
	root := tempDir(t)
	c, err := s.NewCrawler("claude", root)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	for i := 0; i < 3; i++ {
		path := filepath.Join(root, fmt.Sprintf("%d.jsonl", i))
		if err = os.WriteFile(path, nil, 0600); err != nil {
			t.Fatal(err)
		}
		src, _ := agentlog.NewSource("claude", root, path)
		collect(t, s, src)
		if _, err = s.db.Exec(`UPDATE sources SET cursor=?||cursor WHERE id=?`, strings.Repeat(" ", 400<<10), src.ID); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = c.Step(testContext, 64, 1000, time.Second); err != nil {
		t.Fatal(err)
	}
	items, err := c.Ready(testContext, true, 32)
	if err != nil || len(items) != 3 || len(s.readCheckpoints) != 2 {
		t.Fatal("prefetch exceeded byte budget", len(items), len(s.readCheckpoints), err)
	}
	for _, src := range items {
		if cp, err := s.checkpointForRead(testContext, src.ID); err != nil || cp.Revision == 0 {
			t.Fatal("uncached checkpoint unavailable", cp, err)
		}
	}
}
