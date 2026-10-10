package hooks

import (
	"os"
	"path/filepath"
	"testing"
)

func TestBridgeGapRejectsUnsafeFilesAndNeverIncludesPayload(t *testing.T) {
	dir := storeDirectory(t)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "bridge-gap.json")
	if gap, err := ReadBridgeGap(path); err != nil || gap != nil {
		t.Fatal("absence is not a saved gap", err)
	}
	if err := WriteBridgeGap(path, "claude", "PreToolUse", "secret-raw-response"); err == nil {
		t.Fatal("arbitrary response saved")
	}
	if got := BridgeFailureCode("secret-raw-response"); got != "aidr_hook_protocol_invalid" {
		t.Fatal("arbitrary error exposed", got)
	}
	if err := WriteBridgeGap(path, "claude", "PreToolUse", "aidr_hook_receiver_unavailable"); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if err := WriteBridgeGap(path, "claude", "PreToolUse", "aidr_hook_receiver_unavailable"); err == nil {
		t.Fatal("public file overwritten")
	}
	if gap, err := ReadBridgeGap(path); err == nil || gap != nil {
		t.Fatal("public file trusted")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	other := filepath.Join(dir, "other.json")
	if err := os.WriteFile(other, []byte(`{"private":"synthetic-do-not-read"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(other, path); err != nil {
		t.Fatal(err)
	}
	if err := WriteBridgeGap(path, "claude", "PreToolUse", "aidr_hook_receiver_unavailable"); err == nil {
		t.Fatal("symlink followed")
	}
	if gap, err := ReadBridgeGap(path); err == nil || gap != nil {
		t.Fatal("symlink content trusted")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"cause":"synthetic-do-not-expose"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if gap, err := ReadBridgeGap(path); err == nil || gap != nil {
		t.Fatal("malformed diagnostic exposed")
	}
}
