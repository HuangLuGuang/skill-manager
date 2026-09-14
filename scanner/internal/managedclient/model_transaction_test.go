package managedclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestModelChangeRestoreAndConflict(t *testing.T) {
	for kind := range modelAdapters {
		if len(modelConfigFiles(kind)) == 0 {
			continue
		}
		t.Run(kind, func(t *testing.T) {
			home := t.TempDir()
			revision, err := ModelConfigRevision(home, kind)
			if err != nil {
				t.Fatal(err)
			}
			change, err := ApplyModelConfigRevision(home, "https://gateway.example", kind, kind, "model-a", "test-key", revision)
			if err != nil {
				t.Fatal(err)
			}
			if change.Status != "pending_restart" {
				t.Fatalf("unexpected status %s", change.Status)
			}
			if _, err := ApplyModelConfigRevision(home, "https://gateway.example", kind, kind, "model-b", "test-key", revision); err == nil {
				t.Fatal("accepted stale revision")
			}
			if err := RestoreModelConfig(home, change.ID); err != nil {
				t.Fatal(err)
			}
			if got, _ := ModelConfigRevision(home, kind); got != revision {
				t.Fatal("first-time config not removed")
			}
			if err := ApplyModelConfig(home, "https://gateway.example", kind, kind, "model-a", "test-key"); err != nil {
				t.Fatal(err)
			}
			before, rev, _ := readModelFiles(home, kind)
			change, err = ApplyModelConfigRevision(home, "https://gateway.example", kind, kind, "model-b", "new-key", rev)
			if err != nil {
				t.Fatal(err)
			}
			if got := InspectModelConfig(home, kind).Model; got != "model-b" {
				t.Fatal(got)
			}
			if err := RestoreModelConfig(home, change.ID); err != nil {
				t.Fatal(err)
			}
			after, _, _ := readModelFiles(home, kind)
			for i := range before {
				if string(before[i].Before) != string(after[i].Before) {
					t.Fatal("restore changed original bytes")
				}
			}
			change, err = ApplyModelConfigRevision(home, "https://gateway.example", kind, kind, "model-b", "new-key", "")
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(home, modelConfigFiles(kind)[0])
			if err := os.WriteFile(path, []byte("user edit"), 0o600); err != nil {
				t.Fatal(err)
			}
			if err := RestoreModelConfig(home, change.ID); err == nil || !strings.Contains(err.Error(), "restore_conflict") {
				t.Fatalf("overwrote user edit: %v", err)
			}
		})
	}
}

func TestModelChangeStagesAllFilesBeforeWriting(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, ".hermes", "config.yaml")
	original := []byte("theme: dark\n")
	if err := atomicWriteFile(path, original, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(home, ".hermes", ".env"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(home, "https://gateway.example", "hermes", "hermes", "new", "key"); err == nil {
		t.Fatal("accepted unreadable env")
	}
	body, _ := os.ReadFile(path)
	if string(body) != string(original) {
		t.Fatal("partial write")
	}
}

func TestModelChangeRejectsSymlinkAndConcurrentOperation(t *testing.T) {
	home := t.TempDir()
	unlock, err := lockModelConfig(home, "codex")
	if err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(home, "https://gateway.example", "codex", "codex", "model", "key"); err == nil {
		t.Fatal("ignored lock")
	}
	unlock()
	if err := os.Symlink(t.TempDir(), filepath.Join(home, ".codex")); err != nil {
		t.Fatal(err)
	}
	if err := ApplyModelConfig(home, "https://gateway.example", "codex", "codex", "model", "key"); err == nil {
		t.Fatal("followed symlink")
	}
}
