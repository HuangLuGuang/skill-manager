package main

import (
	"golang.org/x/sys/windows"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/privatefs"
)

func acquireHookSupervisor(root string) (func(), error) {
	if err := privatefs.PrepareDirectory(root); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(root, "supervisor.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &windows.Overlapped{}); err != nil {
		f.Close()
		return nil, err
	}
	return func() { f.Close() }, nil
}

// Named pipe ownership is held by the kernel and ends with the process.
func recoverManagedHookSocket(path string) error {
	if _, err := os.Lstat(path); os.IsNotExist(err) {
		return nil
	}
	return privatefs.Check(path)
}
