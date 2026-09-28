package managedclient

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCreateManagedPathCopiesAtomicallyWhenSymlinkIsUnavailable(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "target")
	writeSkill(t, target, "trusted-content")
	path := filepath.Join(root, "agent", "safe-skill")
	symlinkErr := errors.New("symlink privilege unavailable")

	if err := createManagedPathWithSymlink(target, path, true, func(string, string) error {
		return symlinkErr
	}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("copy fallback did not create a real directory: %v %v", info, err)
	}
	content, err := os.ReadFile(filepath.Join(path, "SKILL.md"))
	if err != nil || !strings.Contains(string(content), "name: trusted-content") {
		t.Fatalf("copy fallback changed release content: %q %v", content, err)
	}
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil || len(entries) != 1 || entries[0].Name() != filepath.Base(path) {
		t.Fatalf("copy fallback left staging content: %#v %v", entries, err)
	}
}

func TestCreateManagedPathPreservesSymlinkErrorWithoutFallback(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "release")
	symlinkErr := errors.New("symlink failed")
	err := createManagedPathWithSymlink(filepath.Join(root, "target"), path, false, func(string, string) error {
		return symlinkErr
	})
	if !errors.Is(err, symlinkErr) {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatalf("disabled fallback created a path: %v", err)
	}
}

func TestCreateManagedPathCleansFailedCopy(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "agent", "safe-skill")
	err := createManagedPathWithSymlink(filepath.Join(root, "missing"), path, true, func(string, string) error {
		return errors.New("symlink failed")
	})
	if err == nil {
		t.Fatal("missing source unexpectedly copied")
	}
	entries, readErr := os.ReadDir(filepath.Dir(path))
	if readErr != nil || len(entries) != 0 {
		t.Fatalf("failed fallback left partial content: %#v %v", entries, readErr)
	}
}
