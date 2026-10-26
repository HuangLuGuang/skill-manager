package agentlog

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"hash/crc32"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
	"unicode/utf16"
)

// Synthetic Blink/V8 records: no customer cache or message content in fixtures.
func feishuWAL(t *testing.T, state map[string]any, feishu bool) []byte {
	t.Helper()
	var encode func(any) []byte
	encode = func(v any) []byte {
		switch x := v.(type) {
		case string:
			return append(binary.AppendUvarint([]byte{'S'}, uint64(len(x))), []byte(x)...)
		case bool:
			if x {
				return []byte{'T'}
			}
			return []byte{'F'}
		case float64:
			return binary.LittleEndian.AppendUint64([]byte{'N'}, math.Float64bits(x))
		case map[string]any:
			b := []byte{'o'}
			keys := []string{}
			for k := range x {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				b = append(b, encode(k)...)
				b = append(b, encode(x[k])...)
			}
			return binary.AppendUvarint(append(b, '{'), uint64(len(keys)))
		default:
			t.Fatalf("unexpected synthetic value %T", v)
			return nil
		}
	}
	name := "im-sdk:user:123:default-chat-im-protocol-store"
	if feishu {
		name = "default-chat-im-protocol-store"
	}
	u := utf16.Encode([]rune(name))
	key := binary.AppendUvarint([]byte{0, 1, 1, 1, 1}, uint64(len(u)))
	for _, c := range u {
		key = binary.BigEndian.AppendUint16(key, c)
	}
	value := append([]byte{1, 255, 21, 254}, make([]byte, 12)...)
	value = append(value, 255, 15)
	value = append(value, encode(state)...)
	batch := make([]byte, 12)
	binary.LittleEndian.PutUint32(batch[8:], 1)
	batch = append(batch, 1)
	batch = binary.AppendUvarint(batch, uint64(len(key)))
	batch = append(batch, key...)
	batch = binary.AppendUvarint(batch, uint64(len(value)))
	batch = append(batch, value...)
	if len(batch) > 32761 {
		t.Fatal("synthetic WAL exceeds one block")
	}
	frame := make([]byte, 7)
	frame[6] = 1
	binary.LittleEndian.PutUint16(frame[4:], uint16(len(batch)))
	frame = append(frame, batch...)
	x := crc32.Checksum(frame[6:], crc32.MakeTable(crc32.Castagnoli))
	binary.LittleEndian.PutUint32(frame, (x>>15|x<<17)+0xa282ead8)
	return frame
}

func feishuState(profile string) map[string]any {
	sent, received := map[string]any{}, map[string]any{}
	for _, pair := range [][3]string{{"1001", "2001", "request-a"}, {"1002", "2002", "request-b"}} {
		param, _ := json.Marshal(map[string]any{"runtime_type": 2, "client_option": map[string]any{"agent_workspace": map[string]any{"agent_workspace": filepath.Join(profile, filepath.FromSlash(feishuWorkspace))}}})
		extra := func(id, reply string) map[string]any {
			return map[string]any{"message_id": id, "reply_id": reply, "conversation_id": "9001", "status": float64(1), "create_time": "1792990084", "ext": map[string]any{"chat_id": pair[0], "reply_unique_key": pair[2], "general_task_param": string(param)}}
		}
		u := extra(pair[0], "0")
		u["content_blocks_v2"] = map[string]any{"0": map[string]any{"block_id": "prompt", "block_type": float64(10000), "content": map[string]any{"text_block": map[string]any{"text": "repeat prompt api_key=SYNTHETIC_PRIVATE"}}}}
		sent[pair[0]] = map[string]any{"extra": u}
		a := extra(pair[1], pair[0])
		a["create_time"] = float64(1792990085000)
		a["content_blocks_v2"] = map[string]any{
			"0": map[string]any{"block_id": "answer", "block_type": float64(10000), "is_finish": true, "content": map[string]any{"text_block": map[string]any{"text": "reply api_key=SYNTHETIC_PRIVATE"}}},
			"1": map[string]any{"block_id": "mcp-block", "block_type": float64(10019), "is_finish": true, "content": map[string]any{"file_operation_block": map[string]any{"path": "mcp__probe__ping", "content": "入参\n{}\n\n执行结果\nOK api_key=SYNTHETIC_PRIVATE"}}},
			"2": map[string]any{"block_id": "pending", "block_type": float64(10000), "is_finish": false, "content": map[string]any{"text_block": map[string]any{"text": "unfinished"}}},
		}
		received[pair[1]] = map[string]any{"extra": a}
	}
	return map[string]any{"state": map[string]any{"mainTaskDataMap": map[string]any{"task": map[string]any{"sentMessages": sent, "receivedMessages": received}}}}
}

func writeFeishuCache(t *testing.T, root string, state map[string]any, feishu bool) Source {
	t.Helper()
	name := doubaoChatDB
	if feishu {
		name = feishuChatDB
	}
	dir := filepath.Join(root, name)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "CURRENT"), []byte("MANIFEST-000001\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "000001.log"), feishuWAL(t, state, feishu), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := NewSource("doubaowork", root, filepath.Join(dir, "CURRENT"))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestFeishuCachePolicyIdentityAndMCP(t *testing.T) {
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	profile := filepath.Join(home, filepath.FromSlash(feishuUsers), "profile-a")
	state := feishuState(profile)
	fs := writeFeishuCache(t, filepath.Join(profile, "profile_explorer/IndexedDB"), state, true)
	db := writeFeishuCache(t, filepath.Join(home, "Library/Application Support/DoubaoWork/Default/IndexedDB"), state, false)
	policy := AuditPolicy{Version: "1", Receipt: strings.Repeat("a", 32), Enabled: true, MessageSchema: 1, Capture: &CaptureScope{Prompt: true, ModelResponse: true, ToolOutput: true}}
	read := func(s Source, p AuditPolicy) ReadBatch {
		t.Helper()
		b, e := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
		if e != nil || b.Coverage.Status != "complete" {
			t.Fatalf("read %v %+v", e, b.Coverage)
		}
		return b
	}
	a, b := read(fs, policy), read(db, policy)
	if len(a.Events) != 8 || len(b.Events) != 8 {
		t.Fatalf("events %d/%d", len(a.Events), len(b.Events))
	}
	ids := map[string]bool{}
	for i, e := range a.Events {
		if ValidateEvent(e) != nil || e.LogicalEventID != b.Events[i].LogicalEventID || e.LogicalCallID != b.Events[i].LogicalCallID || e.SourceID == b.Events[i].SourceID {
			t.Fatalf("sync identity %+v", e)
		}
		if ids[e.LogicalEventID] || e.TurnID == "" {
			t.Fatal("repeated identical calls merged or turn lost")
		}
		ids[e.LogicalEventID] = true
		encoded, _ := json.Marshal(e)
		if strings.Contains(string(encoded), "SYNTHETIC_PRIVATE") {
			t.Fatal("redaction bypassed")
		}
	}
	policy.Capture = &CaptureScope{}
	for _, e := range read(fs, policy).Events {
		if e.Message != nil && len(e.Message.Contents) > 0 || e.Behavior != nil && len(e.Behavior.Contents) > 0 {
			t.Fatal("capture switch bypassed")
		}
	}
	policy.Lifecycle = &AuditLifecycle{Enabled: false, RetentionDays: 7}
	batch, _ := ReadWithPolicy(context.Background(), fs, Cursor{}, DefaultBudget(), time.Unix(0, 0), &policy)
	if len(batch.Events) != 0 {
		t.Fatal("disabled collection")
	}
	if rows, e := doubaoCacheSnapshot(context.Background(), filepath.Join(profile, "profile_explorer/IndexedDB")); e != nil || len(rows) != 12 {
		t.Fatalf("rows %d %v", len(rows), e)
	}
	// A different profile must not collect remote/synced execution as its local task.
	other := filepath.Join(home, filepath.FromSlash(feishuUsers), "profile-b", "profile_explorer/IndexedDB")
	writeFeishuCache(t, other, state, true)
	rows, e := doubaoCacheSnapshot(context.Background(), other)
	if e != nil || len(rows) != 0 {
		t.Fatalf("foreign workspace collected %v", e)
	}
}

func TestFeishuTurnsAndHistoricalRepair(t *testing.T) {
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	profile := filepath.Join(home, filepath.FromSlash(feishuUsers), "profile")
	root := filepath.Join(profile, filepath.FromSlash(feishuWorkspace), ".sessions")
	path := filepath.Join(root, "9001/agents/main/system/trajectory.jsonl")
	os.MkdirAll(filepath.Dir(path), 0700)
	os.WriteFile(path, []byte(`{"role":"assistant","tool_calls":[{"id":"call-a","function":{"name":"Bash","arguments":{"command":"printf a"}}},{"id":"call-b","function":{"name":"Read","arguments":{"file_path":"/tmp/probe"}}},{"id":"unknown","function":{"name":"Bash","arguments":{"command":"printf unknown"}}}]}`+"\n"+`{"role":"tool","tool_call_id":"call-a","content":"ok"}`+"\n"), 0600)
	s, _ := NewSource("doubaowork", root, path)
	p := AuditPolicy{Version: "1", Receipt: strings.Repeat("a", 32), Enabled: true}
	first, e := ReadWithPolicy(context.Background(), s, Cursor{}, DefaultBudget(), time.Unix(0, 0), &p)
	if e != nil || len(first.Events) != 4 || len(first.TurnLinks) != 0 {
		t.Fatalf("first %v %+v", e, first)
	}
	writeFeishuCache(t, filepath.Join(profile, "profile_explorer/IndexedDB"), feishuState(profile), true)
	log := filepath.Join(home, "Library/Application Support/LarkShell/sdk_storage/log/agent_infra/agent_infra_test.log")
	os.MkdirAll(filepath.Dir(log), 0700)
	line := func(call, request string) string {
		return `[2026-10-26T12:48:09+08:00](1|2)[I][agent_infra_object.cpp:61] agent_infra invoke, method=local_runtime:shell:run_task, sdk_call_id={"conversation_id":"9001","agent_id":"` + request + `","tcid":"` + call + `"}, task_id=1` + "\n"
	}
	os.WriteFile(log, []byte(line("call-a", "request-a")+line("call-b", "request-b")+"tool stdout: "+line("unknown", "request-a")), 0600)
	second, e := ReadWithPolicy(context.Background(), s, first.Cursor, DefaultBudget(), time.Unix(0, 0), &p)
	if e != nil || len(second.TurnLinks) != 3 {
		t.Fatalf("repair %v %+v", e, second)
	}
	for _, l := range second.TurnLinks {
		want := "1001"
		if l.CallID == "call-b" {
			want = "1002"
		}
		if l.TurnID != want || l.CallID == "unknown" {
			t.Fatal("incorrect native link", l)
		}
	}
}

func TestFeishuLiveReadOnly(t *testing.T) {
	root, session := os.Getenv("FEISHU_TEST_SESSIONS"), os.Getenv("FEISHU_TEST_SESSION")
	if root == "" || session == "" {
		t.Skip("dedicated non-sensitive test conversation required")
	}
	if feishuProfile(root) == "" || !doubaoMessageID.MatchString(session) {
		t.Fatal("invalid test scope")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	turns, _ := feishuTurns(ctx, root, session)
	if len(turns) < 2 {
		rows, _ := doubaoCacheSnapshot(ctx, filepath.Join(feishuProfile(root), "profile_explorer/IndexedDB"))
		for _, row := range rows {
			if row.Session == session {
				t.Log(row.Role, row.ID, row.Turn, row.Request)
			}
		}
		t.Fatalf("expected multi-turn native links, got %d", len(turns))
	}
	paths, _ := filepath.Glob(filepath.Join(root, session, "agents/*/system/trajectory.jsonl"))
	policy := AuditPolicy{Version: "1", Receipt: strings.Repeat("a", 32), Enabled: true, MessageSchema: 1, Capture: &CaptureScope{}}
	total, links, mcpResults := 0, 0, 0
	verified := map[string]string{}
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		for _, line := range strings.Split(string(raw), "\n") {
			var record struct {
				Calls []struct {
					ID       string `json:"id"`
					Function struct {
						Arguments struct {
							Command string `json:"command"`
						} `json:"arguments"`
					} `json:"function"`
				} `json:"tool_calls"`
			}
			if json.Unmarshal([]byte(line), &record) != nil {
				continue
			}
			for _, call := range record.Calls {
				for _, marker := range []string{"FS_COLLECTOR_F_OK", "FS_COLLECTOR_G_OK"} {
					if strings.Contains(call.Function.Arguments.Command, marker) {
						verified[marker] = turns[call.ID]
					}
				}
			}
		}
		s, _ := NewSource("doubaowork", root, path)
		budget := DefaultBudget()
		budget.Duration = 10 * time.Second
		b, err := ReadWithPolicy(ctx, s, Cursor{}, budget, time.Unix(0, 0), &policy)
		if err != nil {
			t.Fatal(err)
		}
		for _, e := range b.Events {
			if e.Kind == "tool_result" && strings.HasPrefix(e.Tool, "mcp__") {
				mcpResults++
			}
			if ValidateEvent(e) != nil {
				t.Fatal("invalid live projected event")
			}
			if e.Behavior != nil && len(e.Behavior.Contents) != 0 || e.Message != nil && len(e.Message.Contents) != 0 {
				t.Fatal("disabled body capture leaked content")
			}
		}
		total += len(b.Events)
		links += len(b.TurnLinks)
	}
	if verified["FS_COLLECTOR_F_OK"] == "" || verified["FS_COLLECTOR_G_OK"] == "" || verified["FS_COLLECTOR_F_OK"] == verified["FS_COLLECTOR_G_OK"] {
		t.Fatalf("new probe turns not distinct: %v", verified)
	}
	cache := filepath.Join(feishuProfile(root), "profile_explorer/IndexedDB")
	rows, err := doubaoCacheSnapshot(ctx, cache)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	for _, r := range rows {
		if r.Session == session {
			counts[r.Role]++
		}
	}
	if counts["user"] < 2 || mcpResults < 2 || links < 2 {
		t.Fatalf("missing test records: %v links=%d", counts, links)
	}
	t.Logf("test session: trajectory events=%d native turn links=%d native MCP results=%d cache counts=%v", total, links, mcpResults, counts)
}
