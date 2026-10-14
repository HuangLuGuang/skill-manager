package localstore

import (
	"database/sql"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestTeleAgentSnapshotCyclesDeduplicateAndResume(t *testing.T) {
	root := tempDir(t)
	path := filepath.Join(root, "teleagent.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for _, q := range []string{
		`CREATE TABLE session(id TEXT PRIMARY KEY,version TEXT,directory TEXT)`,
		`CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,data TEXT)`,
		`CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,time_created INTEGER,data TEXT)`,
		`INSERT INTO session VALUES('s','2.7.0','/workspace')`,
		`INSERT INTO message VALUES('m','s','{"role":"assistant","time":{"completed":1791714601000}}')`,
		`INSERT INTO part VALUES('p','m','s',1791714600000,'{"type":"tool","callID":"call","tool":"bash","state":{"status":"completed","input":{"command":"printf test"},"output":"test","time":{"start":1791714600000,"end":1791714601000}}}')`,
	} {
		if _, err = db.Exec(q); err != nil {
			t.Fatal(err)
		}
	}
	src, err := agentlog.NewSource("teleagent", root, path)
	if err != nil {
		t.Fatal(err)
	}
	dir := tempDir(t)
	store := openStore(t, dir, DefaultLimits())
	policy := &agentlog.AuditPolicy{Version: "1", Enabled: true, Receipt: strings.Repeat("a", 32)}
	store.policy = policy
	first := collect(t, store, src)
	collect(t, store, src)
	if v := status(t, store); v.LogicalEvents != 2 || v.Evidence != 2 {
		t.Fatalf("replayed unchanged snapshots: %+v", v)
	}
	store.Close()
	store = openStore(t, dir, DefaultLimits())
	store.policy = policy
	next := collect(t, store, src)
	if next.Cursor.Generation <= first.Cursor.Generation {
		t.Fatal("snapshot cycle not resumed")
	}
	if v := status(t, store); v.LogicalEvents != 2 || v.Evidence != 2 {
		t.Fatalf("restart duplicated events: %+v", v)
	}
	// An upgrade enriches already acknowledged history without restoring bodies.
	for {
		batch, err := store.Prepare(testContext, 500, 1<<20)
		if err != nil {
			t.Fatal(err)
		}
		if batch == nil {
			break
		}
		if err = store.Acknowledge(testContext, batch.ID, batch.Digest); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = db.Exec(`INSERT INTO message VALUES('user-turn','s','{"role":"user"}'); UPDATE message SET data=json_set(data,'$.parentID','user-turn') WHERE id='m'`); err != nil {
		t.Fatal(err)
	}
	collect(t, store, src)
	batch, err := store.Prepare(testContext, 500, 1<<20)
	if err != nil || batch == nil {
		t.Fatal("missing metadata replay", err)
	}
	var wire struct {
		Records []struct {
			Kind    string `json:"kind"`
			Payload struct {
				Links []agentlog.TurnLink `json:"turn_links"`
			} `json:"payload"`
		} `json:"records"`
	}
	if err = json.Unmarshal(batch.Payload, &wire); err != nil {
		t.Fatal(err)
	}
	links := 0
	for _, r := range wire.Records {
		if r.Kind == "event" {
			t.Fatal("acknowledged content replayed")
		}
		for _, link := range r.Payload.Links {
			if link.TurnID != "user-turn" {
				t.Fatal(link)
			}
			links++
		}
	}
	if links != 2 || status(t, store).LogicalEvents != 2 || status(t, store).RetainedPayloads != 0 {
		t.Fatal("history repair duplicated or restored content", links)
	}
	if err = store.Acknowledge(testContext, batch.ID, batch.Digest); err != nil {
		t.Fatal(err)
	}
	collect(t, store, src)
	var count int
	if err = store.db.QueryRow(`SELECT count(*) FROM outbox WHERE json_array_length(payload,'$.turn_links')>0`).Scan(&count); err != nil || count != 0 {
		t.Fatal("duplicate turn metadata", count, err)
	}
	_, err = db.Exec(`UPDATE part SET data=replace(data,'"output":"test"','"output":"updated"') WHERE id='p'`)
	if err != nil {
		t.Fatal(err)
	}
	collect(t, store, src)
	if v := status(t, store); v.LogicalEvents != 3 {
		t.Fatalf("in-place output update lost: %+v", v)
	}
}
