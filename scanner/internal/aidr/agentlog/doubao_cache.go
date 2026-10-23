package agentlog

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

const doubaoChatDB = "chrome_doubaowork-chat_0.indexeddb.leveldb"
const doubaoLauncherDB = "chrome_doubaowork-launcher_0.indexeddb.leveldb"

var doubaoCacheFile = regexp.MustCompile(`^[0-9]{6}\.(log|ldb)$`)
var doubaoMessageID = regexp.MustCompile(`^[1-9][0-9]{1,30}$`)

type doubaoCacheMessage struct {
	Session, ID, Turn, Role, Text string
	At                            time.Time
}

func doubaoCacheSource(root, path string) bool {
	return filepath.Base(root) == "IndexedDB" && filepath.Clean(path) == filepath.Join(root, doubaoChatDB, "CURRENT")
}

func doubaoObject(x any) map[string]any { m, _ := x.(map[string]any); return m }
func doubaoString(x any) string         { s, _ := x.(string); return s }

func doubaoCachedMessages(state map[string]any, add func(doubaoCacheMessage)) {
	for _, v := range doubaoObject(doubaoObject(state["state"])["mainTaskDataMap"]) {
		task := doubaoObject(v)
		for _, side := range []string{"sentMessages", "receivedMessages"} {
			for id, v := range doubaoObject(task[side]) {
				m := doubaoObject(v)
				e := doubaoObject(m["extra"])
				session := doubaoString(e["conversation_id"])
				if !doubaoMessageID.MatchString(id) || doubaoString(e["message_id"]) != id || !doubaoMessageID.MatchString(session) {
					continue
				}
				ms, _ := e["create_time"].(float64)
				if !(ms >= 946684800000 && ms <= 4102444800000) {
					continue
				}
				role, turn := "user", id
				if side == "sentMessages" && e["status"] != float64(1) {
					continue
				}
				if side == "receivedMessages" {
					role = "assistant"
					turn = doubaoString(e["reply_id"])
					other := doubaoString(doubaoObject(e["ext"])["chat_id"])
					if !doubaoMessageID.MatchString(turn) || (other != "" && turn != other) {
						turn = ""
					}
				}
				blocks := doubaoObject(e["content_blocks_v2"])
				keys := make([]string, 0, len(blocks))
				for k := range blocks {
					keys = append(keys, k)
				}
				// Array indices are sorted numerically, preserving the original text order.
				sort.Slice(keys, func(i, j int) bool {
					if len(keys[i]) != len(keys[j]) {
						return len(keys[i]) < len(keys[j])
					}
					return keys[i] < keys[j]
				})
				var prompt []string
				for _, k := range keys {
					b := doubaoObject(blocks[k])
					if b["block_type"] != float64(10000) {
						continue
					}
					text := doubaoString(doubaoObject(doubaoObject(b["content"])["text_block"])["text"])
					if text == "" || len(text) > 2<<20 {
						continue
					}
					if role == "user" {
						prompt = append(prompt, text)
						continue
					}
					// Parent blocks contain hidden thinking or tool UI, not assistant prose.
					block := doubaoString(b["block_id"])
					if b["is_finish"] != true || doubaoObject(b["control_info"])["is_visible"] == false || doubaoString(b["parent_id"]) != "" || token(block) == "" || len(block) > 100 {
						continue
					}
					add(doubaoCacheMessage{session, id + ":" + block, turn, role, text, time.UnixMilli(int64(ms)).UTC()})
				}
				if role == "user" && len(prompt) > 0 {
					text := strings.Join(prompt, "\n")
					if len(text) <= 2<<20 {
						add(doubaoCacheMessage{session, id, turn, role, text, time.UnixMilli(int64(ms)).UTC()})
					}
				}
			}
		}
	}
}

func doubaoCacheSnapshot(ctx context.Context, root string) ([]doubaoCacheMessage, error) {
	values := map[string]doubaoCacheMessage{}
	conflicts := map[string]bool{}
	var retained int
	var overflow bool
	add := func(m doubaoCacheMessage) {
		key := m.Session + ":" + m.Role + ":" + m.ID
		if len(values) >= 10000 || retained+len(m.Text) > 8<<20 {
			overflow = true
			return
		}
		if old, ok := values[key]; ok {
			retained -= len(old.Text)
		}
		retained += len(m.Text)
		if old, ok := values[key]; ok {
			if old.Text != m.Text || old.Turn != m.Turn {
				conflicts[key] = true
			}
			// The two WebViews stamp arrival separately; IDs and body establish identity.
			if old.At.Before(m.At) {
				m.At = old.At
			}
		}
		values[key] = m
	}
	consume := func(k, v []byte) error {
		if !doubaoStateKey(k) {
			return nil
		}
		raw, err := doubaoUnwrap(v)
		if err != nil {
			return err
		}
		state, err := decodeDoubaoV8(raw)
		if err != nil {
			return err
		}
		doubaoCachedMessages(state, add)
		if overflow {
			return errDoubaoCache
		}
		return nil
	}
	var total int64
	for _, dir := range []string{doubaoChatDB, doubaoLauncherDB} {
		folder := filepath.Join(root, dir)
		if err := checkPath(folder); errors.Is(err, os.ErrNotExist) && dir == doubaoLauncherDB {
			continue
		} else if err != nil {
			return nil, errDoubaoCache
		}
		entries, err := os.ReadDir(folder)
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			if !doubaoCacheFile.MatchString(entry.Name()) {
				continue
			}
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			path := filepath.Join(folder, entry.Name())
			if checkPath(path) != nil {
				return nil, errDoubaoCache
			}
			f, err := openLog(path)
			if err != nil {
				return nil, err
			}
			raw, err := io.ReadAll(io.LimitReader(f, 32<<20+1))
			f.Close()
			total += int64(len(raw))
			if err != nil || len(raw) > 32<<20 || total > 64<<20 {
				return nil, errDoubaoCache
			}
			if strings.HasSuffix(path, ".log") {
				err = doubaoWAL(ctx, raw, consume)
			} else {
				err = doubaoTable(ctx, raw, consume)
			}
			if err != nil {
				return nil, err
			}
		}
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		if !conflicts[key] {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	result := make([]doubaoCacheMessage, 0, len(keys))
	for _, key := range keys {
		result = append(result, values[key])
	}
	return result, nil
}

func readDoubaoCache(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, p *AuditPolicy, observer *SkillObserver) (ReadBatch, error) {
	out := ReadBatch{SchemaVersion: SchemaVersion, Source: s, Cursor: old, Events: []Event{}, Coverage: Coverage{Status: "complete", Reasons: []string{}}}
	expected, err := NewSource(s.Agent, s.Root, s.Path)
	if err != nil || expected.ID != s.ID || !b.valid() {
		return out, errors.New("aidr_log_request_invalid")
	}
	if old.SchemaVersion != 0 {
		if err = ValidateCursor(old, s); err != nil {
			return out, err
		}
		since = old.Since
	}
	if p == nil || !p.CollectionEnabled() || p.MessageSchema != 1 || p.Capture == nil {
		out.Coverage.mark("unavailable", "aidr_audit_collection_disabled")
		return out, nil
	}
	if checkPath(s.Path) != nil {
		out.Coverage.mark("unavailable", "aidr_log_source_changed")
		return out, nil
	}
	if since.IsZero() {
		since = time.Now().Add(-24 * time.Hour)
	}
	ctx, cancel := context.WithTimeout(ctx, b.Duration)
	defer cancel()
	rows, err := doubaoCacheSnapshot(ctx, s.Root)
	if err != nil {
		out.Coverage.mark("unavailable", ioReason(err))
		return out, nil
	}
	raw, _ := json.Marshal(rows)
	identity := digest(string(raw))
	c := old
	if c.SchemaVersion == 0 || c.FileIdentity != identity {
		c = Cursor{SchemaVersion: SchemaVersion, ParserVersion: ParserVersion, SourceID: s.ID, FileIdentity: identity, Generation: old.Generation + 1, Since: since, Anchor: identity, Gaps: []string{}}
	}
	// Offset is a row index in this immutable snapshot, not a LevelDB byte offset.
	if c.Offset > int64(len(rows)) {
		return out, errDoubaoCache
	}
	for c.Offset < int64(len(rows)) && len(out.Events) < b.Events {
		m := rows[c.Offset]
		body, _ := json.Marshal(m.Text)
		phase := "unspecified"
		if m.Role == "assistant" {
			phase = "commentary"
		}
		d, ok := messageDraft(m.Role, phase, "indexeddb:"+m.ID, m.Turn, body, m.At)
		if ok {
			c.Session = m.Session
			evidence, _ := json.Marshal(m)
			projectDrafts(ctx, s, []draft{d}, &c, c, identity, evidence, p, b, observer, time.Now().Add(b.Duration), 0, &out)
			if len(out.Events) > 0 {
				out.Events[len(out.Events)-1].ObservedAtSource = ""
			}
		}
		c.Offset++
		out.Coverage.Records++
	}
	if c.Offset < int64(len(rows)) {
		out.Coverage.mark("partial", "aidr_log_event_budget")
	}
	c.ScanComplete = c.Offset == int64(len(rows))
	out.Cursor = c
	return out, nil
}
