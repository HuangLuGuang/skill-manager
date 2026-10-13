package agentlog

import (
	"context"
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/catalog"
	"strings"
	"testing"
	"time"
)

func TestTeleAgentMutableSQLiteAndReadOnly(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
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
		`INSERT INTO message VALUES('m','s','{"role":"assistant","modelID":"test","providerID":"test","time":{"completed":0}}')`,
		`INSERT INTO part VALUES('p','m','s',1791714600000,'{"type":"tool","callID":"call","tool":"write","state":{"status":"running"}}')`,
	} {
		if _, err = db.Exec(q); err != nil {
			t.Fatal(err)
		}
	}
	src, err := NewSource("teleagent", root, path)
	if err != nil {
		t.Fatal(err)
	}
	p := AuditPolicy{Version: "1", Enabled: true, Receipt: strings.Repeat("a", 32), ModelContextSchema: 1}
	first, err := ReadWithPolicy(context.Background(), src, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(first.Events) != 0 || !first.Cursor.ScanComplete {
		t.Fatalf("pending: %+v %v", first, err)
	}
	_, err = db.Exec(`UPDATE part SET data=? WHERE id='p'`, `{"type":"tool","callID":"call","tool":"write","state":{"status":"completed","input":{"filePath":"/workspace/a.txt","content":"SYNTHETIC_BODY"},"output":"written","time":{"start":1791714600000,"end":1791714601000}}}`)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(path)
	second, err := ReadWithPolicy(context.Background(), src, first.Cursor, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(second.Events) != 2 {
		t.Fatalf("updated row: %+v %v", second, err)
	}
	for _, e := range second.Events {
		if err := ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
	}
	raw, _ := json.Marshal(second.Events)
	if strings.Contains(string(raw), "SYNTHETIC_BODY") || !strings.Contains(string(raw), "/workspace/a.txt") {
		t.Fatal("projection", string(raw))
	}
	third, err := ReadWithPolicy(context.Background(), src, second.Cursor, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil || len(third.Events) != 2 || third.Events[0].EventID != second.Events[0].EventID || third.Events[1].LogicalEventID != second.Events[1].LogicalEventID {
		t.Fatal("snapshot identity changed", err)
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("source database was modified")
	}
	if ValidateCursor(third.Cursor, src) != nil {
		t.Fatal("invalid durable checkpoint")
	}
}

func TestRegisteredLogAdaptersCoverCatalog(t *testing.T) {
	for _, product := range catalog.All() {
		if product.Logs == "" {
			continue
		}
		agent := product.ID
		a, ok := logAdapters[agent]
		if !ok || (a.Parse == nil && a.Read == nil) {
			t.Fatalf("missing %s", agent)
		}
	}
}

func TestTeleAgentTurnLinksUseSameSessionUserParent(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
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
		`INSERT INTO session VALUES('s','2.7.0','/workspace'),('other','2.7.0','/workspace')`,
	} {
		if _, err = db.Exec(q); err != nil {
			t.Fatal(err)
		}
	}
	for _, m := range []struct{ id, session, role, parent string }{
		{"u1", "s", "user", ""}, {"u2", "s", "user", ""}, {"foreign", "other", "user", ""},
		{"a2", "s", "assistant", "u2"}, {"a1", "s", "assistant", "u1"}, {"a1tool", "s", "assistant", "u1"},
		{"bad-session", "s", "assistant", "foreign"}, {"bad-role", "s", "assistant", "a1"}, {"missing", "s", "assistant", "absent"},
	} {
		data, _ := json.Marshal(map[string]any{"role": m.role, "parentID": m.parent, "time": map[string]int64{"completed": 1791714601000}})
		if _, err = db.Exec(`INSERT INTO message VALUES(?,?,?)`, m.id, m.session, string(data)); err != nil {
			t.Fatal(err)
		}
		part := `{"type":"text","text":"synthetic"}`
		if m.id == "a1tool" {
			part = `{"type":"tool","callID":"tool-call","tool":"bash","state":{"status":"completed","input":{"command":"true"},"output":"ok","time":{"start":1791714600000,"end":1791714601000}}}`
		}
		if _, err = db.Exec(`INSERT INTO part VALUES(?,?,?,1791714600000,?)`, m.id, m.id, m.session, part); err != nil {
			t.Fatal(err)
		}
	}
	src, _ := NewSource("teleagent", root, path)
	p := AuditPolicy{MessageSchema: 1, Version: "1", Enabled: true, Receipt: strings.Repeat("a", 32), Capture: &CaptureScope{Prompt: true, ModelResponse: true}}
	batch, err := ReadWithPolicy(context.Background(), src, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]string{}
	for _, link := range batch.TurnLinks {
		got[link.CallID] = link.TurnID
	}
	want := map[string]string{"message:u1": "u1", "message:u2": "u2", "message:foreign": "foreign", "message:a1": "u1", "message:a2": "u2", "tool-call": "u1"}
	if len(got) != len(want) {
		t.Fatal(got)
	}
	for call, turn := range want {
		if got[call] != turn {
			t.Fatal(call, got)
		}
	}
}
