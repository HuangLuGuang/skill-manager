package localstore

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestDoubaoSyncedCacheOneOutboxTwoEvidence(t *testing.T) {
	for _, acked := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_ack", true: "after_ack"}[acked], func(t *testing.T) {
			root := tempDir(t)
			path := filepath.Join(root, "9001/agents/main/system/trajectory.jsonl")
			os.MkdirAll(filepath.Dir(path), 0700)
			os.WriteFile(path, []byte(`{"role":"assistant","tool_calls":[{"id":"cache-mcp:2001:block","function":{"name":"mcp__probe__ping","arguments":{}}}]}`+"\n"), 0600)
			src, _ := agentlog.NewSource("doubaowork", root, path)
			p := agentlog.AuditPolicy{Version: "1", Receipt: strings.Repeat("a", 32), Enabled: true}
			b, err := agentlog.ReadWithPolicy(testContext, src, agentlog.Cursor{}, agentlog.DefaultBudget(), time.Unix(0, 0), &p)
			if err != nil || len(b.Events) != 1 {
				t.Fatal(err)
			}
			store := openStore(t, tempDir(t), DefaultLimits())
			if _, err = store.Commit(testContext, Checkpoint{}, b); err != nil {
				t.Fatal(err)
			}
			// ACK removes bodies; a later synced copy must still match the retained hash.
			if _, err = store.db.Exec(`UPDATE logical_events SET acked_ns=1,payload=NULL WHERE ?`, acked); err != nil {
				t.Fatal(err)
			}
			copySource, _ := agentlog.NewSource("doubaowork", root, filepath.Join(root, "synced/CURRENT"))
			b.Source = copySource
			b.Cursor.SourceID = copySource.ID
			b.Events[0].SourceID = copySource.ID
			b.Events[0].EventID = hash([]byte("copy evidence"))
			b.Events[0].SourceInstanceID = hash([]byte("copy instance"))
			c, err := store.Commit(testContext, Checkpoint{}, b)
			if err != nil {
				t.Fatalf("synced source conflict: %v", err)
			}
			var events, evidence, queued int
			store.db.QueryRow(`SELECT count(*) FROM logical_events`).Scan(&events)
			store.db.QueryRow(`SELECT count(*) FROM evidence`).Scan(&evidence)
			store.db.QueryRow(`SELECT count(*) FROM outbox WHERE kind='event'`).Scan(&queued)
			if events != 1 || evidence != 2 || queued != 1 {
				t.Fatalf("events=%d evidence=%d queued=%d", events, evidence, queued)
			}
			// An ID collision with a different result is still rejected.
			b.Events[0].ContentDigest = hash([]byte("different body"))
			if _, err = store.Commit(testContext, c, b); !errors.Is(err, ErrBatchConflict) {
				t.Fatalf("content conflict accepted: %v", err)
			}

		})
	}
}
