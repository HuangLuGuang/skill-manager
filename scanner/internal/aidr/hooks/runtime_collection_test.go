package hooks

import (
	"bytes"
	"context"
	"os"
	"testing"
)

func TestRuntimeStopPreservesFrozenBatchReceiptsAndRestart(t *testing.T) {
	ctx := context.Background()
	dir := storeDirectory(t)
	s := openTestStore(t, dir, 10)
	id := testID(301)
	first, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil {
		t.Fatal(err)
	}
	frozen, err := s.Prepare(ctx)
	if err != nil || frozen == nil {
		t.Fatal(err)
	}
	if err = s.SetRuntimeCollection(ctx, false, "9:2"); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Receive(ctx, testID(302), "501", "codex", "PreToolUse", []byte(storeInput)); err == nil || err.Error() != "aidr_hook_collection_disabled" {
		t.Fatal("new intake accepted", err)
	}
	duplicate, err := s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || duplicate.Sequence != first.Sequence {
		t.Fatal("existing identity changed", err)
	}
	pending, err := PendingUploads(ctx, dir)
	if err != nil || pending != 1 {
		t.Fatal(pending, err)
	}
	if err = s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openTestStore(t, dir, 10)
	status, err := s.Status(ctx)
	if err != nil || status.RuntimeEnabled == nil || *status.RuntimeEnabled || status.RuntimeVersion != "9:2" {
		t.Fatal(status, err)
	}
	after, err := s.Prepare(ctx)
	if err != nil || !bytes.Equal(frozen.Payload, after.Payload) || frozen.Digest != after.Digest {
		t.Fatal("frozen content changed", err)
	}
	if err = s.Acknowledge(ctx, status.Device, status.Stream, after.Digest, after.Count, true); err != nil {
		t.Fatal(err)
	}
	pending, err = PendingUploads(ctx, dir)
	if err != nil || pending != 0 {
		t.Fatal(pending, err)
	}
	duplicate, err = s.Receive(ctx, id, "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || duplicate.Sequence != first.Sequence {
		t.Fatal("acknowledged identity replayed as new event", err)
	}
	pending, err = PendingUploads(ctx, dir)
	if err != nil || pending != 0 {
		t.Fatal("replay requeued an event", pending, err)
	}
	if err = s.SetRuntimeCollection(ctx, true, "9:3"); err != nil {
		t.Fatal(err)
	}
	resumed, err := s.Receive(ctx, testID(303), "501", "codex", "PreToolUse", []byte(storeInput))
	if err != nil || resumed.Sequence != "2" {
		t.Fatal("resume sequence reset", resumed.Sequence, err)
	}
}

func TestPendingReadNeverCreatesState(t *testing.T) {
	dir := storeDirectory(t)
	pending, err := PendingUploads(context.Background(), dir)
	if err != nil || pending != 0 {
		t.Fatal(pending, err)
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatal("read created state", err)
	}
}
