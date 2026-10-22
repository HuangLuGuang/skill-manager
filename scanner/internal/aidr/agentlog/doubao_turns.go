package agentlog

import (
	"bufio"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Only native logger envelopes are accepted; tool output is never searched for IDs.
type doubaoTurnIndex struct {
	requests map[string]string
	calls    map[string]string
}

var doubaoFrontendEnvelope = regexp.MustCompile(`^\[[0-9]+:[0-9]+:[0-9/.:]+:INFO:FRONTEND\(0\)\] \[neotix\] \[(office-api-logger|desktop\.office\.local-slides)\] "`)
var doubaoSandboxEnvelope = regexp.MustCompile(`^\[[0-9]+:[0-9]+:[0-9/.:]+:INFO:[A-Za-z0-9_/]+/saman_sandbox_shell_api_metrics\.cc\([0-9]+\)\] \[sandbox\] shell api call, `)

func newDoubaoTurnIndex() *doubaoTurnIndex {
	return &doubaoTurnIndex{map[string]string{}, map[string]string{}}
}

func uniqueDoubaoID(values map[string]string, key, value string) {
	if key == "" || token(value) == "" {
		return
	}
	if old, ok := values[key]; ok && old != value {
		values[key] = ""
	} else if !ok {
		values[key] = value
	}
}

func (index *doubaoTurnIndex) consume(line string) {
	frontend := doubaoFrontendEnvelope.MatchString(line)
	decode := func(marker string, value any) bool {
		at := strings.Index(line, marker)
		return at >= 0 && json.NewDecoder(strings.NewReader(line[at+len(marker):])).Decode(value) == nil
	}
	if frontend && strings.Contains(line, ":INFO:FRONTEND(0)] [neotix] [office-api-logger] ") {
		var r struct {
			Event string                     `json:"eventName"`
			Meta  map[string]json.RawMessage `json:"meta"`
		}
		if decode("[logifier-report]: ", &r) && r.Event == "on_message_receiving_start" {
			uniqueDoubaoID(index.requests, token(rawString(r.Meta["chat_session_id"])), rawString(r.Meta["send_message_id"]))
		}
	}
	if frontend && strings.Contains(line, ":INFO:FRONTEND(0)] [neotix] [desktop.office.local-slides] ") {
		var r struct {
			Event  string `json:"eventName"`
			Params struct {
				Action, Stage string
				Success       bool
				Session       string `json:"session_id"`
				Message       string `json:"message_id"`
			} `json:"params"`
		}
		if decode("[local-office:slide-tea] ", &r) && r.Event == "flow_doc_slide_tools_bug_trace_dev" && r.Params.Action == "local_office_canvas_lifecycle_emit_finished" && r.Params.Stage == "start" && r.Params.Success {
			uniqueDoubaoID(index.requests, token(r.Params.Session), r.Params.Message)
		}
	}
	if doubaoSandboxEnvelope.MatchString(line) && strings.Contains(line, ", status=enter, sandbox_log_id=") {
		var r struct {
			Session string `json:"conversation_id"`
			Agent   string `json:"agent_id"`
			Call    string `json:"tcid"`
		}
		if decode("sandbox_log_id=", &r) && token(r.Session) != "" && token(r.Call) != "" {
			uniqueDoubaoID(index.calls, r.Session+":"+r.Call, r.Agent)
		}
	}
}

var doubaoLogName = regexp.MustCompile(`^saman(_frontend)?_[0-9]{4}\.[0-9]{4}\.[0-9]+\.log$`)
var doubaoTurnCache struct {
	sync.Mutex
	root  string
	at    time.Time
	index *doubaoTurnIndex
}

func doubaoTurns(ctx context.Context, root, session string) (map[string]string, string) {
	const suffix = "Default/.doubaowork/agent_mode/workspace/.sessions"
	if !strings.HasSuffix(filepath.ToSlash(root), "/"+suffix) {
		return nil, ""
	}
	logRoot := filepath.Join(strings.TrimSuffix(root, filepath.FromSlash(suffix)), "sdk_storage", "log")
	doubaoTurnCache.Lock()
	defer doubaoTurnCache.Unlock()
	if doubaoTurnCache.root != logRoot || time.Since(doubaoTurnCache.at) > 15*time.Second {
		index := newDoubaoTurnIndex()
		entries, err := os.ReadDir(logRoot)
		if err != nil || checkPath(logRoot) != nil {
			return nil, ""
		}
		var bytes int64
		for _, entry := range entries {
			if !doubaoLogName.MatchString(entry.Name()) {
				continue
			}
			path := filepath.Join(logRoot, entry.Name())
			if checkPath(path) != nil {
				return nil, ""
			}
			f, err := openLog(path)
			if err != nil {
				return nil, ""
			}
			scan := bufio.NewScanner(f)
			scan.Buffer(make([]byte, 64<<10), 2<<20)
			for scan.Scan() {
				bytes += int64(len(scan.Bytes()))
				if ctx.Err() != nil || bytes > 128<<20 || len(index.requests)+len(index.calls) > 100000 {
					f.Close()
					return nil, ""
				}
				index.consume(scan.Text())
			}
			err = scan.Err()
			f.Close()
			if err != nil {
				return nil, ""
			}
		}
		doubaoTurnCache.root, doubaoTurnCache.at, doubaoTurnCache.index = logRoot, time.Now(), index
	}
	turns := map[string]string{}
	for key, agent := range doubaoTurnCache.index.calls {
		if strings.HasPrefix(key, session+":") && agent != "" {
			if message := doubaoTurnCache.index.requests[agent]; message != "" {
				turns[strings.TrimPrefix(key, session+":")] = message
			}
		}
	}
	if len(turns) == 0 {
		return nil, ""
	}
	raw, _ := json.Marshal(turns)
	return turns, digest(string(raw))
}
