package localstore

import (
	"fmt"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/agentlog"
	"testing"
	"time"
)

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
}
