package hooks

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

const storeInput = `{"hook_event_name":"PreToolUse","session_id":"s","turn_id":"t","tool_use_id":"c","tool_name":"Bash","tool_input":{"command":"echo --password='synthetic-hook-secret' && pwd"}}`

func openTestStore(t *testing.T, dir string, capacity int) *Store {
	t.Helper()
	s, err := OpenStore(dir, "https://platform.example", "device-a", capacity)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func storeDirectory(t *testing.T) string {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Join(root, "state")
}

func testID(n int) string { return fmt.Sprintf("%016x%016x", time.Now().UnixMilli(), n) }

func TestPrepareEmptyThenReceive(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 10)
	if b, err := s.Prepare(ctx); err != nil || b != nil {
		t.Fatal(b, err)
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if _, err := s.Prepare(cancelled); err != context.Canceled {
		t.Fatal("empty queue ignored cancellation", err)
	}
	if _, err := s.Receive(ctx, testID(1), "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
		t.Fatal(err)
	}
	b, err := s.Prepare(ctx)
	if err != nil || b == nil {
		t.Fatal("received event not ready immediately", err)
	}
	if err = s.Acknowledge(ctx, s.device, s.stream, b.Digest, b.Count, true); err != nil {
		t.Fatal(err)
	}
	if b, err = s.Prepare(ctx); err != nil || b != nil {
		t.Fatal("acknowledged queue not empty", b, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Prepare(ctx); err == nil {
		t.Fatal("closed database returned empty success")
	}
}

func TestStatusCountsPendingKindsAndRecentSuppression(t *testing.T) {
	ctx := context.Background()
	s := openTestStore(t, storeDirectory(t), 10)
	if _, err := s.Receive(ctx, testID(1), "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`INSERT INTO hook_attempts(event_id,receiver,user_scope,scope,expires_at) VALUES('pending','test','501','{}',1);
	INSERT INTO hook_attempt_reports(event_id,payload,digest,acked) VALUES('unsent',X'7B7D','test',0),('sent',X'7B7D','test',1);
	INSERT INTO hook_suppressed_receipts(event_id,input_hash,seen_at) VALUES('recent','test',?),('old','test',1)`, time.Now().Unix()); err != nil {
		t.Fatal(err)
	}
	state, err := s.Status(ctx)
	if err != nil || state.Queued != 1 || state.PendingUploads != 3 || state.Suppressed != 1 || state.LastSequence != "1" {
		t.Fatal(state, err)
	}
}

func TestBridgeProvenanceIsFrozenAndCannotChangeOnRetry(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 10)
	id := testID(1)
	peer := &BridgeProcess{BootID: "11111111-1111-1111-1111-111111111111", PID: "123", PIDVersion: "456", StartUS: "1790000000000000", Method: "macos_socket_audit_token_sysctl", Role: "ipc_bridge"}
	first, err := s.receiveWithBridge(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput), peer)
	if err != nil {
		t.Fatal(err)
	}
	frozen, err := s.Prepare(ctx)
	if err != nil || frozen == nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openTestStore(t, dir, 10)
	changed := *peer
	changed.PIDVersion = "457"
	retry, err := s.receiveWithBridge(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput), &changed)
	if err != nil {
		t.Fatal(err)
	}
	a, _ := json.Marshal(first)
	b, _ := json.Marshal(retry)
	if !bytes.Equal(a, b) || retry.Event.ProcessRelation != "unknown" {
		t.Fatal("retry changed provenance or asserted a tool process")
	}
	after, err := s.Prepare(ctx)
	if err != nil || !bytes.Equal(frozen.Payload, after.Payload) || frozen.Digest != after.Digest {
		t.Fatal("frozen bridge batch changed")
	}
}

func TestStoreRedactsBeforePersistenceAndFreezesAcrossRestart(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 10)
	id := testID(1)
	r, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.Prepare(ctx)
	if err != nil || b == nil {
		t.Fatalf("prepare: %v", err)
	}
	if bytes.Contains(b.Payload, []byte("synthetic-hook-secret")) {
		t.Fatal("secret in batch")
	}
	files, err := filepath.Glob(filepath.Join(dir, "*"))
	if err != nil {
		t.Fatal(err)
	}
	for _, file := range files {
		data, e := os.ReadFile(file)
		if e != nil {
			t.Fatal(e)
		}
		if bytes.Contains(data, []byte("synthetic-hook-secret")) {
			t.Fatalf("secret persisted in %s", filepath.Base(file))
		}
	}
	if err = s.SetPolicy(ctx, agentlog.AuditPolicy{Version: "2", Enabled: false, Receipt: strings.Repeat("a", 32)}); err != nil {
		t.Fatal(err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openTestStore(t, dir, 10)
	retry, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil {
		t.Fatal(err)
	}
	original, _ := json.Marshal(r)
	again, _ := json.Marshal(retry)
	if !bytes.Equal(original, again) {
		t.Fatal("retry changed original projection")
	}
	frozen, err := s.Prepare(ctx)
	if err != nil || !bytes.Equal(b.Payload, frozen.Payload) || b.Digest != frozen.Digest {
		t.Fatal("frozen batch changed")
	}
	if _, err = s.Receive(ctx, testID(2), "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		device, stream, hash string
		count                int
		durable              bool
	}{
		{"other", s.stream, b.Digest, b.Count, true},
		{s.device, "other", b.Digest, b.Count, true},
		{s.device, s.stream, "other", b.Count, true},
		{s.device, s.stream, b.Digest, b.Count + 1, true},
		{s.device, s.stream, b.Digest, b.Count, false},
	} {
		if s.Acknowledge(ctx, tc.device, tc.stream, tc.hash, tc.count, tc.durable) == nil {
			t.Fatal("invalid ACK accepted")
		}
		current, e := s.Prepare(ctx)
		if e != nil || !bytes.Equal(current.Payload, b.Payload) {
			t.Fatal("invalid ACK changed queue")
		}
	}
	if err = s.Acknowledge(ctx, s.device, s.stream, b.Digest, b.Count, true); err != nil {
		t.Fatal(err)
	}
	next, err := s.Prepare(ctx)
	if err != nil || next == nil || next.Count != 1 || !bytes.Contains(next.Payload, []byte("synthetic-hook-secret")) {
		t.Fatal("new policy or pending tail lost")
	}
}

func TestStoreBoundedConcurrentReceiptsAndDestination(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 3)
	id := testID(1)
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	b, err := s.Prepare(ctx)
	if err != nil || b.Count != 1 {
		t.Fatal("duplicate receipts inserted")
	}
	if _, err = s.Receive(ctx, id, "502", "codex", "PreToolUse", []byte(storeInput)); err == nil {
		t.Fatal("identity conflict accepted")
	}
	for i := 2; i <= 3; i++ {
		if _, err = s.Receive(ctx, testID(i), "501", "codex", "PreToolUse", []byte(storeInput)); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = s.Receive(ctx, testID(4), "501", "codex", "PreToolUse", []byte(storeInput)); err == nil || err.Error() != "aidr_hook_outbox_full" {
		t.Fatalf("capacity did not reject explicitly: %v", err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	if other, err := OpenStore(dir, "https://platform.example", "device-b", 3); err == nil {
		other.Close()
		t.Fatal("destination changed")
	}
	s = openTestStore(t, dir, 3)
	if current, e := s.Prepare(ctx); e != nil || !bytes.Equal(current.Payload, b.Payload) {
		t.Fatal("capacity failure changed frozen payload")
	}
}

func TestAcknowledgedRetryCannotRestoreRedactedHistory(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 10)
	id := testID(80)
	original, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.Prepare(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.Acknowledge(ctx, s.device, s.stream, b.Digest, b.Count, true); err != nil {
		t.Fatal(err)
	}
	if err = s.SetPolicy(ctx, agentlog.AuditPolicy{Version: "2", Enabled: false, Receipt: strings.Repeat("b", 32)}); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s = openTestStore(t, dir, 10)
	retry, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || retry.Sequence != original.Sequence {
		t.Fatalf("receipt not restored: %v", err)
	}
	if b, err = s.Prepare(ctx); err != nil || b != nil {
		t.Fatal("acknowledged event requeued")
	}
	if _, err = s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(strings.ReplaceAll(storeInput, "pwd", "ls"))); err == nil {
		t.Fatal("acknowledged conflict accepted")
	}
	expired := fmt.Sprintf("%016x%016x", time.Now().Add(-72*time.Hour).UnixMilli(), 81)
	if _, err = s.Receive(ctx, expired, "501", "codex", "PreToolUse", []byte(storeInput)); err == nil || err.Error() != "aidr_hook_event_expired" {
		t.Fatal("expired new ID accepted")
	}
	future := fmt.Sprintf("%016x%016x", time.Now().Add(time.Hour).UnixMilli(), 82)
	if _, err = s.Receive(ctx, future, "501", "codex", "PreToolUse", []byte(storeInput)); err == nil {
		t.Fatal("future ID accepted")
	}
	if id, err := NewEventID(); err != nil || !freshEventID(id, time.Now()) {
		t.Fatal("generated invalid ID")
	}
}
