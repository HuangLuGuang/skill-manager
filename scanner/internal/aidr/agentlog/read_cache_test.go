package agentlog

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func cachedTeleAgentFixture(t *testing.T) (Source, *sql.DB) {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "teleagent.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	for _, q := range []string{
		`PRAGMA journal_mode=WAL`,
		`CREATE TABLE session(id TEXT PRIMARY KEY,version TEXT,directory TEXT)`,
		`CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,data TEXT)`,
		`CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,time_created INTEGER,data TEXT)`,
		`INSERT INTO session VALUES('s','2.7.0','/workspace')`,
		`INSERT INTO message VALUES('m','s','{"role":"assistant","time":{"completed":1791714601000}}')`,
		`INSERT INTO part VALUES('p','m','s',1791714600000,'{"type":"tool","callID":"call","tool":"bash","state":{"status":"completed","input":{"command":"printf test"},"output":"test","time":{"start":1791714600000,"end":1791714601000}}}')`,
	} {
		if _, err := db.Exec(q); err != nil {
			t.Fatal(err)
		}
	}
	src, err := NewSource("teleagent", root, path)
	if err != nil {
		t.Fatal(err)
	}
	return src, db
}

func TestReadCacheTeleAgentWALPolicyAndResume(t *testing.T) {
	src, db := cachedTeleAgentFixture(t)
	stamp, valid := inspectReadStamp(src)
	if !valid {
		t.Skip("filesystem has no reliable change-time metadata")
	}
	var cache ReadCache
	policy := AuditPolicy{Version: "1", Enabled: true, Receipt: strings.Repeat("a", 32)}
	budget := DefaultBudget()
	read := func(cursor Cursor) ReadBatch {
		t.Helper()
		batch, err := cache.Read(context.Background(), src, cursor, budget, time.Unix(0, 0), &policy, nil)
		if err != nil || batch.Coverage.Status != "complete" {
			t.Fatalf("read: %+v %v", batch.Coverage, err)
		}
		return batch
	}
	first := read(Cursor{})
	if len(first.Events) != 2 {
		t.Fatal("missing initial events", len(first.Events))
	}
	second := read(first.Cursor)
	if len(second.Events) != 0 || second.Cursor.Generation != first.Cursor.Generation {
		t.Fatal("unchanged database was reparsed")
	}
	if _, err := db.Exec(`UPDATE part SET data=replace(data,'"output":"test"','"output":"edit"') WHERE id='p'`); err != nil {
		t.Fatal(err)
	}
	after, _ := inspectReadStamp(src)
	if !sameLogFileVersion(stamp.main, after.main) || stamp.equal(after) {
		t.Fatal("fixture did not isolate a WAL mutation")
	}
	third := read(second.Cursor)
	if len(third.Events) != 2 || third.Cursor.Generation <= second.Cursor.Generation {
		t.Fatal("WAL row update was skipped")
	}
	policy.Receipt = strings.Repeat("b", 32)
	fourth := read(third.Cursor)
	if fourth.Cursor.Generation <= third.Cursor.Generation {
		t.Fatal("policy change reused the old projection")
	}
	budget.CollectionResumeAt = time.Unix(1, 0)
	fifth := read(fourth.Cursor)
	if fifth.Cursor.Generation <= fourth.Cursor.Generation {
		t.Fatal("resume boundary reused old read")
	}
}

func TestReadCacheTeleAgentMutationBetweenPages(t *testing.T) {
	src, db := cachedTeleAgentFixture(t)
	if _, err := db.Exec(`INSERT INTO part SELECT 'p2',message_id,session_id,time_created,replace(data,'"call"','"call2"') FROM part WHERE id='p'`); err != nil {
		t.Fatal(err)
	}
	var cache ReadCache
	budget := DefaultBudget()
	budget.Events = 2
	first, err := cache.Read(context.Background(), src, Cursor{}, budget, time.Unix(0, 0), nil, nil)
	if err != nil || first.Cursor.ScanComplete {
		t.Fatal("fixture did not paginate", err)
	}
	if _, err := db.Exec(`UPDATE part SET data=replace(data,'"output":"test"','"output":"edit"') WHERE id='p'`); err != nil {
		t.Fatal(err)
	}
	cursor := first.Cursor
	for i := 0; i < 5 && !cursor.ScanComplete; i++ {
		batch, err := cache.Read(context.Background(), src, cursor, budget, time.Unix(0, 0), nil, nil)
		if err != nil {
			t.Fatal(err)
		}
		cursor = batch.Cursor
	}
	if !cursor.ScanComplete || cache.sources[src.ID].complete {
		t.Fatal("a changing paginated snapshot was treated as unchanged")
	}
	next, err := cache.Read(context.Background(), src, cursor, budget, time.Unix(0, 0), nil, nil)
	if err != nil || next.Cursor.Generation <= cursor.Generation || len(next.Events) == 0 {
		t.Fatal("next snapshot did not revisit mutated earlier rows", err)
	}
}

func TestReadCacheRegularRewriteRotationAndMissing(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "session.jsonl")
	raw, err := os.ReadFile("testdata/claude-2.1.220.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	src, _ := NewSource("claude", root, path)
	var cache ReadCache
	budget := DefaultBudget()
	read := func(cursor Cursor) ReadBatch {
		t.Helper()
		b, err := cache.Read(context.Background(), src, cursor, budget, time.Unix(0, 0), nil, nil)
		if err != nil {
			t.Fatal(err)
		}
		return b
	}
	first := read(Cursor{})
	info, _ := os.Stat(path)
	if skillChangeTime(info) == 0 {
		t.Skip("filesystem has no reliable change-time metadata")
	}
	budget.Duration -= time.Millisecond
	second := read(first.Cursor)
	if len(second.Events) != 0 || second.Coverage.Bytes != first.Coverage.Bytes {
		t.Fatal("unchanged file did not reuse the completed read")
	}
	// Preserve size and mtime while changing the file; ctime must invalidate reuse.
	changed := append([]byte(nil), raw...)
	changed[len(changed)-1] = ' '
	if err := os.WriteFile(path, changed, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	third := read(second.Cursor)
	if third.Cursor.Generation <= second.Cursor.Generation {
		t.Fatal("same-size, same-mtime rewrite was skipped")
	}
	if err := os.Rename(path, path+".old"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	fourth := read(third.Cursor)
	if fourth.Cursor.FileIdentity == third.Cursor.FileIdentity {
		t.Fatal("replacement was skipped")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if got := read(fourth.Cursor); got.Coverage.Status != "unavailable" {
		t.Fatal("missing source reused completed coverage")
	}
}

func TestReadCacheDoubaoSnapshotTracksDataFiles(t *testing.T) {
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(base, "IndexedDB")
	folder := filepath.Join(root, doubaoChatDB)
	if err := os.MkdirAll(folder, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(folder, "CURRENT")
	if err := os.WriteFile(path, []byte("MANIFEST-000001\n"), 0600); err != nil {
		t.Fatal(err)
	}
	wal := filepath.Join(folder, "000001.log")
	if err := os.WriteFile(wal, doubaoTestWAL(t, false), 0600); err != nil {
		t.Fatal(err)
	}
	src, _ := NewSource("doubaowork", root, path)
	policy := AuditPolicy{Version: "7", Receipt: strings.Repeat("a", 32), MessageSchema: 1, Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	var cache ReadCache
	first, err := cache.Read(context.Background(), src, Cursor{}, DefaultBudget(), time.Unix(0, 0), &policy, nil)
	if err != nil || len(first.Events) != 4 || !first.Cursor.ScanComplete {
		t.Fatalf("snapshot: %+v %v", first.Coverage, err)
	}
	second, err := cache.Read(context.Background(), src, first.Cursor, DefaultBudget(), time.Unix(0, 0), &policy, nil)
	if err != nil || len(second.Events) != 0 {
		t.Fatal("unchanged snapshot replayed", err)
	}
	if err := os.WriteFile(wal, doubaoTestWAL(t, true), 0600); err != nil {
		t.Fatal(err)
	}
	third, err := cache.Read(context.Background(), src, second.Cursor, DefaultBudget(), time.Unix(0, 0), &policy, nil)
	if err != nil || third.Coverage.Status != "unavailable" {
		t.Fatal("unchanged CURRENT hid a changed WAL", third.Coverage, err)
	}
}

func TestReadStampRejectsReplacedParentAndLeaf(t *testing.T) {
	base, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(base, "logs")
	if err = os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "session.jsonl")
	if err = os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	src, err := NewSource("claude", root, path)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := inspectReadStamp(src); !ok {
		t.Fatal("regular file rejected")
	}
	if err = os.Rename(root, root+".old"); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(root+".old", root); err != nil {
		t.Fatal(err)
	}
	if _, ok := inspectReadStamp(src); ok {
		t.Fatal("replaced parent accepted")
	}
	if err = os.Remove(root); err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(root+".old", root); err != nil {
		t.Fatal(err)
	}
	if err = os.Rename(path, path+".old"); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(path+".old", path); err != nil {
		t.Fatal(err)
	}
	if _, ok := inspectReadStamp(src); ok {
		t.Fatal("replaced leaf accepted")
	}
}
