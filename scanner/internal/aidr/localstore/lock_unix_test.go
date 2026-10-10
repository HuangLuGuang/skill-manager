//go:build darwin || linux

package localstore

import (
	"os/exec"
	"path/filepath"
	"testing"
)

func TestWriterLockNotInheritedByChild(t *testing.T) {
	path := filepath.Join(t.TempDir(), "writer.lock")
	lock, err := lockDirectory(path)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Close()
	child := exec.Command("/bin/sleep", "20")
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
	if err := lock.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := lockDirectory(path)
	if err != nil {
		t.Fatalf("child retained the stopped collector's writer lock: %v", err)
	}
	reopened.Close()
}
