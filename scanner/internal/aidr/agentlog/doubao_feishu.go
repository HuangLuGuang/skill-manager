package agentlog

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"skill-manager/scanner/internal/aidr/catalog"
)

const feishuChatDB = "https_www.doubao.com_0.indexeddb.leveldb"
const feishuUsers = "Library/Application Support/LarkShell/aha/users"
const feishuWorkspace = "doubao/.doubao/agent_mode/workspace"

// Limit discovery to per-user Doubao workspaces and the Doubao WebView cache.
func doubaoRoots(home string) []string {
	roots := catalog.LogRoots("doubaowork", home)
	if runtime.GOOS != "darwin" {
		return roots
	}
	base := filepath.Join(home, feishuUsers)
	if checkPath(base) != nil {
		return roots
	}
	f, err := openLog(base)
	if err != nil {
		return roots
	}
	defer f.Close()
	names, _ := f.Readdirnames(16)
	sort.Strings(names)
	for _, name := range names {
		if name == "global" || name == ".." || token(name) == "" {
			continue
		}
		profile := filepath.Join(base, name)
		for _, sub := range []string{feishuWorkspace + "/.sessions", "profile_explorer/IndexedDB"} {
			root := filepath.Join(profile, filepath.FromSlash(sub))
			if checkPath(root) == nil {
				roots = append(roots, root)
			}
		}
	}
	return roots
}

func feishuProfile(root string) string {
	path := filepath.ToSlash(filepath.Clean(root))
	for _, suffix := range []string{"/" + feishuWorkspace + "/.sessions", "/profile_explorer/IndexedDB"} {
		if !strings.HasSuffix(path, suffix) {
			continue
		}
		profile := strings.TrimSuffix(path, suffix)
		if strings.HasSuffix(filepath.ToSlash(filepath.Dir(profile)), "/"+feishuUsers) && token(filepath.Base(profile)) != "" {
			return filepath.FromSlash(profile)
		}
	}
	return ""
}

func doubaoCacheDirs(root string) []string {
	if feishuProfile(root) != "" {
		return []string{feishuChatDB}
	}
	return []string{doubaoChatDB, doubaoLauncherDB}
}

// Native message IDs are shared by the two clients in this OS user's account.
// Keep the original standalone identity so existing queued/history events dedupe.
func doubaoMessageScope(s Source) string {
	profile := feishuProfile(s.Root)
	if profile == "" {
		return s.ID
	}
	home := strings.TrimSuffix(filepath.ToSlash(filepath.Dir(profile)), "/"+feishuUsers)
	path := filepath.Join(filepath.FromSlash(home), "Library/Application Support/DoubaoWork/Default/IndexedDB", doubaoChatDB, "CURRENT")
	return digest(s.Agent, path)
}

// SharedDoubaoCacheEvent identifies native cache evidence, not ID-less transcripts.
func SharedDoubaoCacheEvent(e Event) bool {
	return e.Agent == "doubaowork" && (strings.HasPrefix(e.CallID, "message:indexeddb:") || strings.HasPrefix(e.CallID, "cache-mcp:"))
}

func doubaoMCPBlock(block map[string]any, row doubaoCacheMessage, add func(doubaoCacheMessage)) {
	if block["block_type"] != float64(10019) || block["is_finish"] != true || doubaoObject(block["control_info"])["is_visible"] == false {
		return
	}
	id := token(doubaoString(block["block_id"]))
	file := doubaoObject(doubaoObject(block["content"])["file_operation_block"])
	tool := token(doubaoString(file["path"]))
	if id == "" || len(id) > 100 || !strings.HasPrefix(tool, "mcp__") {
		return
	}
	text := doubaoString(file["content"])
	if len(text) > 2<<20 || !strings.HasPrefix(text, "入参\n") {
		return
	}
	args, result, ok := strings.Cut(strings.TrimPrefix(text, "入参\n"), "\n\n执行结果\n")
	if !ok || rawObject(json.RawMessage(args)) == nil {
		return
	}
	row.ID += ":" + id
	row.Tool, row.Role, row.Payload = tool, "tool_call", json.RawMessage(canonical([]byte(args)))
	add(row)
	row.Role = "tool_result"
	row.Payload, _ = json.Marshal(result)
	add(row)
}

var feishuInfraEnvelope = regexp.MustCompile(`^\[[^\]\r\n]+\]\([0-9]+\|[0-9]+\)\[I\]\[agent_infra_object\.cpp:[0-9]+\] agent_infra invoke, method=local_runtime:(shell:run_task|file_tool:[a-z_]+), sdk_call_id=`)

var feishuTurnCache struct {
	sync.Mutex
	entries map[string]struct {
		at    time.Time
		calls map[string]string
	}
}

func feishuTurns(ctx context.Context, root, session string) (map[string]string, string) {
	profile := feishuProfile(root)
	if profile == "" {
		return nil, ""
	}
	feishuTurnCache.Lock()
	defer feishuTurnCache.Unlock()
	if cached, ok := feishuTurnCache.entries[profile]; ok && time.Since(cached.at) < 15*time.Second {
		return feishuSessionTurns(cached.calls, session)
	}
	rows, err := doubaoCacheSnapshot(ctx, filepath.Join(profile, "profile_explorer/IndexedDB"))
	if err != nil {
		return nil, ""
	}
	requests := map[string]string{}
	for _, row := range rows {
		if row.Request != "" && row.Turn != "" {
			uniqueDoubaoID(requests, row.Session+":"+row.Request, row.Turn)
		}
	}
	logRoot := filepath.Join(filepath.Dir(filepath.Dir(filepath.Dir(profile))), "sdk_storage/log/agent_infra")
	entries, err := os.ReadDir(logRoot)
	if err != nil || checkPath(logRoot) != nil {
		return nil, ""
	}
	turns := map[string]string{}
	var size int64
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "agent_infra_") || !strings.HasSuffix(entry.Name(), ".log") {
			continue
		}
		path := filepath.Join(logRoot, entry.Name())
		if checkPath(path) != nil {
			return nil, ""
		}
		raw, err := readDoubaoFile(ctx, path, &size)
		if err != nil {
			return nil, ""
		}
		for _, line := range strings.Split(string(raw), "\n") {
			prefix := feishuInfraEnvelope.FindString(line)
			if prefix == "" {
				continue
			}
			var meta struct {
				Session string `json:"conversation_id"`
				Request string `json:"agent_id"`
				Call    string `json:"tcid"`
			}
			if json.NewDecoder(strings.NewReader(strings.TrimPrefix(line, prefix))).Decode(&meta) == nil && token(meta.Session) != "" && token(meta.Call) != "" {
				uniqueDoubaoID(turns, meta.Session+":"+meta.Call, requests[meta.Session+":"+meta.Request])
			}
		}
	}
	if feishuTurnCache.entries == nil || len(feishuTurnCache.entries) >= 16 {
		feishuTurnCache.entries = make(map[string]struct {
			at    time.Time
			calls map[string]string
		})
	}
	feishuTurnCache.entries[profile] = struct {
		at    time.Time
		calls map[string]string
	}{time.Now(), turns}
	return feishuSessionTurns(turns, session)
}

func feishuSessionTurns(calls map[string]string, session string) (map[string]string, string) {
	turns := map[string]string{}
	for key, turn := range calls {
		if strings.HasPrefix(key, session+":") && turn != "" {
			turns[strings.TrimPrefix(key, session+":")] = turn
		}
	}
	if len(turns) == 0 {
		return nil, ""
	}
	raw, _ := json.Marshal(turns)
	return turns, digest(string(raw))
}
