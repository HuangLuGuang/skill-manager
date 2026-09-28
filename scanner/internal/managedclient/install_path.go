package managedclient

import (
	"fmt"
	"os"
	"path/filepath"
)

type symlinkCreator func(string, string) error

func createManagedPath(target, path string, copyOnSymlinkFailure bool) error {
	return createManagedPathWithSymlink(target, path, copyOnSymlinkFailure, os.Symlink)
}

func createManagedPathWithSymlink(target, path string, copyOnSymlinkFailure bool, symlink symlinkCreator) error {
	symlinkErr := symlink(target, path)
	if symlinkErr == nil {
		return nil
	}
	if !copyOnSymlinkFailure {
		return symlinkErr
	}

	parent := filepath.Dir(path)
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return fmt.Errorf("create managed path after symlink failure (%v): %w", symlinkErr, err)
	}
	staging, err := os.MkdirTemp(parent, "."+filepath.Base(path)+".copy-")
	if err != nil {
		return fmt.Errorf("create managed path after symlink failure (%v): %w", symlinkErr, err)
	}
	defer os.RemoveAll(staging)
	if err := copyDir(target, staging); err != nil {
		return fmt.Errorf("copy managed path after symlink failure (%v): %w", symlinkErr, err)
	}
	if err := os.Rename(staging, path); err != nil {
		return fmt.Errorf("activate managed path after symlink failure (%v): %w", symlinkErr, err)
	}
	return nil
}
