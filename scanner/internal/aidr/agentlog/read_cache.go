package agentlog

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"os"
	"sync"
	"time"
)

type readStamp struct {
	main, wal os.FileInfo
}

func inspectReadStamp(s Source) (readStamp, bool) {
	main, err := checkedPathInfo(s.Path)
	if err != nil || !main.Mode().IsRegular() || skillChangeTime(main) == 0 {
		return readStamp{}, false
	}
	stamp := readStamp{main: main}
	if s.Agent == "teleagent" {
		for _, suffix := range []string{"-wal", "-shm"} {
			info, err := checkedPathInfo(s.Path + suffix)
			if err != nil && !os.IsNotExist(err) || err == nil && !info.Mode().IsRegular() {
				return readStamp{}, false
			}
			if suffix == "-wal" {
				stamp.wal = info
			}
		}
	}
	return stamp, true
}

func (s readStamp) equal(other readStamp) bool {
	return sameLogFileVersion(s.main, other.main) &&
		(s.wal == nil && other.wal == nil || sameLogFileVersion(s.wal, other.wal))
}

type readMemo struct {
	stamp          readStamp
	cursor, inputs [32]byte
	tracking       bool
	complete       bool
	coverage       []byte
}

// ReadCache is scoped to one collector. Only a completed, unchanged read can
// skip parsing; no event bodies or credentials are retained in this cache.
type ReadCache struct {
	mu      sync.Mutex
	sources map[string]readMemo
}

func readKey(value any) [32]byte {
	raw, _ := json.Marshal(value)
	return sha256.Sum256(raw)
}

func (cache *ReadCache) Read(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, observer *SkillObserver) (ReadBatch, error) {
	// Doubao correlation also depends on SDK logs outside this source file.
	if s.Agent == "doubaowork" || !b.valid() {
		return ReadWithPolicy(ctx, s, old, b, since, policy, observer)
	}
	cache.mu.Lock()
	defer cache.mu.Unlock()
	before, valid := inspectReadStamp(s)
	// The scheduler's remaining time varies each round; it cannot change a completed read.
	inputs := readKey([]any{s, b.Bytes, b.Events, b.LineBytes, b.CollectionResumeAt, since, policy})
	previous, exists := cache.sources[s.ID]
	match := exists && previous.tracking && previous.cursor == readKey(old) && previous.inputs == inputs && valid && previous.stamp.equal(before)
	if match && previous.complete {
		if err := ctx.Err(); err != nil {
			return ReadBatch{}, err
		}
		var coverage Coverage
		if err := json.Unmarshal(previous.coverage, &coverage); err != nil {
			return ReadBatch{}, err
		}
		return ReadBatch{SchemaVersion: SchemaVersion, Source: s, Cursor: old, Coverage: coverage, Events: []Event{}}, nil
	}
	batch, err := ReadWithPolicy(ctx, s, old, b, since, policy, observer)
	if err != nil {
		delete(cache.sources, s.ID)
		return batch, err
	}
	after, current := inspectReadStamp(s)
	tracking := valid && current && before.equal(after)
	if s.Agent == "teleagent" && old.SchemaVersion != 0 && !old.ScanComplete {
		// A mutation between pages invalidates the entire snapshot cycle.
		tracking = tracking && match
	}
	complete := tracking && batch.Coverage.Status == "complete" && batch.Cursor.ContextRepair == nil
	if s.Agent == "teleagent" {
		complete = complete && batch.Cursor.ScanComplete
	} else {
		complete = complete && after.main != nil && batch.Cursor.Offset == after.main.Size()
	}
	if cache.sources == nil || !exists && len(cache.sources) >= 256 {
		cache.sources = make(map[string]readMemo)
	}
	coverage, _ := json.Marshal(batch.Coverage)
	cache.sources[s.ID] = readMemo{stamp: after, cursor: readKey(batch.Cursor), inputs: inputs, tracking: tracking, complete: complete, coverage: coverage}
	return batch, nil
}

func sameLogFileVersion(a, b os.FileInfo) bool {
	return a != nil && b != nil && os.SameFile(a, b) && a.Size() == b.Size() && a.ModTime().Equal(b.ModTime()) && skillChangeTime(a) != 0 && skillChangeTime(a) == skillChangeTime(b)
}
