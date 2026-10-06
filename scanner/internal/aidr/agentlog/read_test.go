package agentlog

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const stamp = "2026-09-23T10:00:00Z"

func claudeCall(id string) string {
	return fmt.Sprintf(`{"type":"assistant","timestamp":%q,"sessionId":"session-a","version":"2.1.220","message":{"content":[{"type":"tool_use","id":%q,"name":"Bash","input":{"command":"TOKEN=SYNTHETIC_SECRET /bin/true","large_integer":18446744073709551615}}]}}`+"\n", stamp, id)
}
func source(t *testing.T, agent, content string) Source {
	t.Helper()
	root, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	path := filepath.Join(root, "session.jsonl")
	if e := os.WriteFile(path, []byte(content), 0600); e != nil {
		t.Fatal(e)
	}
	s, e := NewSource(agent, root, path)
	if e != nil {
		t.Fatal(e)
	}
	return s
}
func read(t *testing.T, s Source, c Cursor) ReadBatch {
	t.Helper()
	b, e := ReadIncremental(context.Background(), s, c, DefaultBudget(), time.Unix(0, 0))
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func has(b ReadBatch, reason string) bool {
	for _, r := range b.Coverage.Reasons {
		if r == reason {
			return true
		}
	}
	return false
}
func TestAppendPartialAndResume(t *testing.T) {
	line := claudeCall("one")
	s := source(t, "claude", line[:len(line)-4])
	b := read(t, s, Cursor{})
	if b.Cursor.Offset != 0 || !has(b, "aidr_log_partial_line") {
		t.Fatalf("%+v", b)
	}
	f, _ := os.OpenFile(s.Path, os.O_APPEND|os.O_WRONLY, 0600)
	f.WriteString(line[len(line)-4:])
	f.Close()
	b = read(t, s, b.Cursor)
	if len(b.Events) != 1 || b.Coverage.Status != "complete" {
		t.Fatalf("%+v", b)
	}
	encoded, _ := json.Marshal(b)
	if strings.Contains(string(encoded), "SYNTHETIC_SECRET") {
		t.Fatal("content leaked")
	}
	again := read(t, s, b.Cursor)
	if len(again.Events) != 0 || again.Cursor.Offset != b.Cursor.Offset {
		t.Fatal("replayed append")
	}
	fresh := read(t, s, Cursor{})
	if fresh.Events[0].EventID != b.Events[0].EventID {
		t.Fatal("unstable replay ID")
	}
}
func TestRotationTruncationAndRewrite(t *testing.T) {
	for _, kind := range []string{"rotate", "truncate", "rewrite"} {
		t.Run(kind, func(t *testing.T) {
			s := source(t, "claude", claudeCall("one")+claudeCall("two"))
			b := read(t, s, Cursor{})
			data := claudeCall("one")
			if kind == "rotate" {
				if e := os.Rename(s.Path, s.Path+".old"); e != nil {
					t.Fatal(e)
				}
			}
			if kind == "rewrite" {
				data = claudeCall("xxx") + claudeCall("yyy")
			}
			os.WriteFile(s.Path, []byte(data), 0600)
			next := read(t, s, b.Cursor)
			if next.Cursor.Generation != 2 || next.Coverage.Status != "partial" || len(next.Events) == 0 {
				t.Fatalf("%+v", next)
			}
			if kind != "rewrite" && next.Events[0].LogicalEventID != b.Events[0].LogicalEventID {
				t.Fatal("reread creates a different logical event")
			}
			stable := read(t, s, next.Cursor)
			if stable.Coverage.Status != "partial" {
				t.Fatal("gap vanished")
			}
		})
	}
}
func TestMissingPermissionAndEmptyAreDistinct(t *testing.T) {
	s := source(t, "claude", "")
	if read(t, s, Cursor{}).Coverage.Status != "complete" {
		t.Fatal("empty")
	}
	os.Chmod(s.Path, 0000)
	if os.Geteuid() != 0 {
		if !has(read(t, s, Cursor{}), "aidr_log_permission_denied") {
			t.Fatal("permission")
		}
	}
	os.Chmod(s.Path, 0600)
	os.Remove(s.Path)
	if !has(read(t, s, Cursor{}), "aidr_log_source_missing") {
		t.Fatal("missing")
	}
}
func TestMalformedAndKnownInvalidFormatPreserveOffset(t *testing.T) {
	for _, tail := range []string{"not json\n", "{\"type\":\"assistant\",\"message\":{\"content\":{}}}\n"} {
		line := claudeCall("one")
		s := source(t, "claude", line+tail+claudeCall("two"))
		b := read(t, s, Cursor{})
		if b.Cursor.Offset != int64(len(line)) || len(b.Events) != 1 || b.Coverage.Status != "partial" {
			t.Fatalf("%+v", b)
		}
		again := read(t, s, b.Cursor)
		if len(again.Events) != 0 || again.Cursor.Offset != b.Cursor.Offset {
			t.Fatal("skipped malformed record")
		}
	}
}
func TestBudgetsCancellationAndSymlink(t *testing.T) {
	s := source(t, "claude", claudeCall("one"))
	b := DefaultBudget()
	b.LineBytes = 32
	r, e := ReadIncremental(context.Background(), s, Cursor{}, b, time.Unix(0, 0))
	if e != nil || !has(r, "aidr_log_record_too_large") || r.Cursor.Offset == 0 {
		t.Fatalf("%+v %v", r, e)
	}
	b = DefaultBudget()
	b.Bytes = 20
	r, e = ReadIncremental(context.Background(), s, Cursor{}, b, time.Unix(0, 0))
	if e != nil || !has(r, "aidr_log_read_budget") {
		t.Fatal("byte budget")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r, e = ReadIncremental(ctx, s, Cursor{}, DefaultBudget(), time.Unix(0, 0))
	if e != nil || !has(r, "aidr_log_canceled") {
		t.Fatal("cancel")
	}
	os.Rename(s.Path, s.Path+".real")
	os.Symlink(s.Path+".real", s.Path)
	if !has(read(t, s, Cursor{}), "aidr_log_symlink") {
		t.Fatal("symlink")
	}
}
func TestTenThousandIncrementalEvents(t *testing.T) {
	var content strings.Builder
	for i := 0; i < 10000; i++ {
		content.WriteString(claudeCall(fmt.Sprintf("call-%d", i)))
	}
	s := source(t, "claude", content.String())
	c := Cursor{}
	ids := map[string]bool{}
	total := 0
	for n := 0; n < 100; n++ {
		b := read(t, s, c)
		for _, e := range b.Events {
			if ids[e.EventID] {
				t.Fatal("duplicate")
			}
			ids[e.EventID] = true
			total++
		}
		c = b.Cursor
		if c.Offset == int64(content.Len()) {
			break
		}
	}
	if total != 10000 {
		t.Fatalf("got %d", total)
	}
}
func TestDiscoveryBoundsAndScopes(t *testing.T) {
	s := source(t, "claude", "")
	os.WriteFile(filepath.Join(s.Root, "second.jsonl"), []byte{}, 0600)
	d := Discover(context.Background(), "claude", s.Root, 1, 10, time.Second)
	if len(d.Sources) != 1 || d.Coverage.Status != "partial" {
		t.Fatalf("%+v", d)
	}
	d = Discover(context.Background(), "claude", s.Root+"/absent", 10, 10, time.Second)
	if d.Coverage.Status != "unavailable" {
		t.Fatal("missing root")
	}
	if _, e := NewSource("claude", s.Root, filepath.Join(s.Root, "..", "outside.jsonl")); e == nil {
		t.Fatal("escaped root")
	}
}
func TestCodexCallsResultsAndContextAcrossBatches(t *testing.T) {
	rows := []string{
		`{"type":"session_meta","payload":{"id":"s","cli_version":"0.155.0-alpha.9.2"}}`,
		`{"type":"turn_context","payload":{"turn_id":"t"}}`,
		`{"timestamp":"2026-09-23T10:00:00Z","type":"response_item","payload":{"type":"custom_tool_call","call_id":"c","name":"exec","input":"SYNTHETIC_SECRET"}}`,
		`{"timestamp":"2026-09-23T10:00:01Z","type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"c","output":[{"type":"text","text":"result"}]}}`,
	}
	s := source(t, "codex", strings.Join(rows, "\n")+"\n")
	budget := DefaultBudget()
	budget.Events = 1
	a, e := ReadIncremental(context.Background(), s, Cursor{}, budget, time.Unix(0, 0))
	if e != nil || len(a.Events) != 1 {
		t.Fatalf("%+v %v", a, e)
	}
	b := read(t, s, a.Cursor)
	if len(b.Events) != 1 || b.Events[0].LogicalCallID != a.Events[0].LogicalCallID || b.Events[0].Outcome != "unknown" || b.Events[0].TurnID != "t" {
		t.Fatalf("%+v", b)
	}
}

func TestAnonymizedLiveFixtures(t *testing.T) {
	for _, name := range []string{"claude-2.1.220.jsonl", "codex-0.155.0-alpha.9.2.jsonl", "codex-0.158.0-alpha.2.1.jsonl", "codex-0.160.0.jsonl"} {
		t.Run(name, func(t *testing.T) {
			data, e := os.ReadFile(filepath.Join("testdata", name))
			if e != nil {
				t.Fatal(e)
			}
			agent := "codex"
			if strings.HasPrefix(name, "claude") {
				agent = "claude"
			}
			s := source(t, agent, string(data))
			b := read(t, s, Cursor{})
			calls, results := 0, 0
			for _, v := range b.Events {
				if v.Kind == "tool_call" {
					calls++
				} else if v.Kind == "tool_result" {
					results++
				}
				if v.SessionID == "" || v.ProcessRelation != "unknown" {
					t.Fatal("invalid binding")
				}
			}
			if b.Coverage.Status != "complete" || calls == 0 || results == 0 {
				t.Fatalf("calls=%d results=%d coverage=%+v", calls, results, b.Coverage)
			}
		})
	}
}

func TestCodex158ControlledOperations(t *testing.T) {
	data, err := os.ReadFile("testdata/codex-0.158.0-alpha.2.1.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	s := source(t, "codex", string(data))
	p := DefaultAuditPolicy()
	b, err := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"mkdir sample", "printf '[BODY OMITTED]' > sample/input.txt", "cat sample/input.txt", "printf '[BODY OMITTED]' > sample/input.txt", "cat sample/input.txt", "mv sample/input.txt sample/renamed.txt", "cat sample/renamed.txt", "/usr/bin/true", "/bin/sh -c 'exit 7'", "/bin/sleep 1"}
	if len(b.Events) != 20 || b.Coverage.Status != "complete" {
		t.Fatalf("event count/coverage: %d %s", len(b.Events), b.Coverage.Status)
	}
	for i, command := range want {
		call, result := b.Events[2*i], b.Events[2*i+1]
		if call.Kind != "tool_call" || len(call.Behavior.Actions) != 1 || call.Behavior.Actions[0].Command != command {
			t.Fatalf("call %d differs", i+1)
		}
		code := 0
		if i == 8 {
			code = 7
		}
		if result.Kind != "tool_result" || result.LogicalCallID != call.LogicalCallID || result.Behavior.ExitCode == nil || *result.Behavior.ExitCode != code {
			t.Fatalf("result %d differs", i+1)
		}
		if call.ProcessRelation != "unknown" || result.ProcessRelation != "unknown" {
			t.Fatal("fabricated process relation")
		}
	}
}
func TestCodex160ControlledOperationsAndCursorResume(t *testing.T) {
	data, err := os.ReadFile("testdata/codex-0.160.0.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	s := source(t, "codex", string(data))
	policy := DefaultAuditPolicy()
	budget := DefaultBudget()
	budget.Events = 5
	var cursor Cursor
	var events []Event
	for round := 0; round < 8; round++ {
		batch, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &policy)
		if err != nil {
			t.Fatal(err)
		}
		events = append(events, batch.Events...)
		// Persist and reopen the cursor between bounded reads, as the worker does.
		raw, err := json.Marshal(batch.Cursor)
		if err != nil || json.Unmarshal(raw, &cursor) != nil {
			t.Fatal("cursor persistence failed", err)
		}
		if cursor.Offset == int64(len(data)) {
			if batch.Coverage.Status != "complete" {
				t.Fatal("recognized final snapshot incomplete", batch.Coverage)
			}
			break
		}
	}
	want := []string{"mkdir sample", "printf '[BODY OMITTED]' > sample/input.txt", "cat sample/input.txt", "printf '[BODY OMITTED]' > sample/input.txt", "cat sample/input.txt", "/usr/bin/true", "/bin/sh -c 'exit 7'"}
	if len(events) != 14 || cursor.Offset != int64(len(data)) {
		t.Fatal("bounded resume omitted or duplicated events", len(events), cursor.Offset)
	}
	seen := map[string]bool{}
	for i, command := range want {
		call, result := events[2*i], events[2*i+1]
		if call.Kind != "tool_call" || call.Tool != "exec" || len(call.Behavior.Actions) != 1 || call.Behavior.Actions[0].Command != command || call.Behavior.Actions[0].Cwd != "/owned/work" {
			t.Fatalf("operation %d differs from independent expectation", i+1)
		}
		code, status := 0, "reported_success"
		if i == 6 {
			code, status = 7, "reported_error"
		}
		if result.Kind != "tool_result" || result.LogicalCallID != call.LogicalCallID || result.TurnID != call.TurnID || result.Behavior.ExitCode == nil || *result.Behavior.ExitCode != code || result.Behavior.Status != status {
			t.Fatalf("result %d differs from log evidence", i+1)
		}
		for _, event := range []Event{call, result} {
			if event.ProcessRelation != "unknown" || seen[event.LogicalEventID] || event.SessionID != "anonymous-session-160" {
				t.Fatal("invalid process/session binding or duplicate identity")
			}
			seen[event.LogicalEventID] = true
		}
	}
	if VersionSupport("codex", "0.160.0") != "available" || VersionSupport("codex", "0.160.1") != "unverified" {
		t.Fatal("unverified neighboring version accepted")
	}
	end, err := ReadWithPolicy(context.Background(), s, cursor, budget, time.Unix(0, 0), &policy)
	if err != nil || len(end.Events) != 0 {
		t.Fatal("confirmed cursor reread events", err)
	}
}

func TestUnknownVersionAndSessionAreExplicit(t *testing.T) {
	for _, data := range []string{strings.Replace(claudeCall("a"), "2.1.220", "99.0", 1), strings.Replace(claudeCall("a"), `"sessionId":"session-a",`, "", 1)} {
		b := read(t, source(t, "claude", data), Cursor{})
		if b.Coverage.Status != "partial" || len(b.Events) != 1 {
			t.Fatalf("%+v", b)
		}
	}
}
func TestOutcomeAndToolDifferencesHaveDistinctLogicalIDs(t *testing.T) {
	a := claudeCall("a")
	b := strings.Replace(a, `"Bash"`, `"Read"`, 1)
	batch := read(t, source(t, "claude", a+b), Cursor{})
	if len(batch.Events) != 2 || batch.Events[0].LogicalEventID == batch.Events[1].LogicalEventID {
		t.Fatal("distinct events collapsed")
	}
}

func TestSharedContractVectors(t *testing.T) {
	data, e := os.ReadFile("testdata/contracts.json")
	if e != nil {
		t.Fatal(e)
	}
	var cases []struct {
		Name  string          `json:"name"`
		Valid bool            `json:"valid"`
		Event json.RawMessage `json:"event"`
	}
	if e = json.Unmarshal(data, &cases); e != nil {
		t.Fatal(e)
	}
	for _, v := range cases {
		t.Run(v.Name, func(t *testing.T) {
			var event Event
			err := json.Unmarshal(v.Event, &event)
			if err == nil {
				err = ValidateEvent(event)
			}
			if (err == nil) != v.Valid {
				t.Fatalf("valid=%v err=%v", v.Valid, err)
			}
		})
	}
}
func TestDefaultLookbackAndCursorValidation(t *testing.T) {
	s := source(t, "claude", strings.Replace(claudeCall("old"), stamp, "2000-01-01T00:00:00Z", 1))
	b, err := ReadIncremental(context.Background(), s, Cursor{}, DefaultBudget(), time.Time{})
	if err != nil || len(b.Events) != 0 || b.Coverage.Filtered != 1 {
		t.Fatal("lookback", err)
	}
	b.Cursor.ParserVersion = "future"
	if _, err := ReadIncremental(context.Background(), s, b.Cursor, DefaultBudget(), time.Time{}); err == nil {
		t.Fatal("unknown cursor accepted")
	}
}

func TestOversizedRecordSkipsBoundedlyAndReportsGap(t *testing.T) {
	huge := `{"type":"assistant","message":"` + strings.Repeat("x", 5000) + `"}` + "\n"
	s := source(t, "claude", huge+claudeCall("after"))
	budget := DefaultBudget()
	budget.Bytes = 700
	budget.LineBytes = 512
	var cursor Cursor
	skipped := int64(0)
	var events []Event
	for i := 0; i < 20; i++ {
		b, err := ReadIncremental(context.Background(), s, cursor, budget, time.Unix(0, 0))
		if err != nil {
			t.Fatal(err)
		}
		if b.Coverage.Bytes > 700 {
			t.Fatal("read budget exceeded")
		}
		if !has(b, "aidr_log_record_too_large") {
			t.Fatal("gap hidden")
		}
		if b.Cursor.Offset == cursor.Offset {
			t.Fatal("oversized record stalled")
		}
		skipped += b.Coverage.SkippedBytes
		events = append(events, b.Events...)
		cursor = b.Cursor
		if cursor.Offset == int64(len(huge)+len(claudeCall("after"))) {
			break
		}
	}
	if len(events) != 1 || events[0].CallID != "after" || skipped != int64(len(huge)) || cursor.Discarding {
		t.Fatalf("events=%d skipped=%d cursor=%+v", len(events), skipped, cursor)
	}
	again := read(t, s, cursor)
	if again.Coverage.Status != "partial" {
		t.Fatal("oversize gap disappeared")
	}
}

func TestLargeIntegerContentAndDuplicateEvidence(t *testing.T) {
	a := claudeCall("same")
	b := strings.Replace(a, "18446744073709551615", "18446744073709551614", 1)
	batch := read(t, source(t, "claude", a+a+b), Cursor{})
	if len(batch.Events) != 3 {
		t.Fatal("evidence discarded")
	}
	if batch.Events[0].LogicalEventID != batch.Events[1].LogicalEventID || batch.Events[0].EventID == batch.Events[1].EventID {
		t.Fatal("logical and evidence identity conflated")
	}
	if batch.Events[0].ContentDigest == batch.Events[2].ContentDigest {
		t.Fatal("integer precision lost")
	}
	for _, e := range batch.Events {
		if err := ValidateEvent(e); err != nil {
			t.Fatal(err)
		}
	}
}
func TestGapDetailsAreBounded(t *testing.T) {
	c := Coverage{Status: "complete"}
	for n := int64(0); n < 100; n++ {
		c.gap(n*10, n*10+9, "aidr_log_record_too_large")
	}
	if len(c.Gaps) != 32 || !c.GapDetailsTruncated || c.Status != "partial" {
		t.Fatalf("%+v", c)
	}
}

func TestDifferentSourcesDoNotInferSameRun(t *testing.T) {
	a := read(t, source(t, "claude", claudeCall("same")), Cursor{})
	b := read(t, source(t, "claude", claudeCall("same")), Cursor{})
	if a.Events[0].LogicalCallID == b.Events[0].LogicalCallID || a.Events[0].LogicalEventID == b.Events[0].LogicalEventID {
		t.Fatal("cross-source binding inferred from copied IDs")
	}
}

func TestSessionMetadataClearsPreviousTurn(t *testing.T) {
	c := Cursor{Session: "old", Turn: "old-turn"}
	_, err := normalize("codex", []byte(`{"type":"session_meta","payload":{"id":"new","cli_version":"0.155.0-alpha.9.2"}}`), &c)
	if err != nil || c.Session != "new" || c.Turn != "" {
		t.Fatalf("%+v %v", c, err)
	}
}
