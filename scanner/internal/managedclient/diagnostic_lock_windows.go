package managedclient

import (
	"golang.org/x/sys/windows"
	"os"
	"path/filepath"
	"time"
)

func lockDiagnostics(root string) (func(), error) {
	if err := os.MkdirAll(logRoot(root), 0700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(root, "diagnostics.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	var overlapped windows.Overlapped
	deadline := time.Now().Add(2 * time.Second)
	for {
		err = windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &overlapped)
		if err == nil {
			return func() { _ = windows.UnlockFileEx(windows.Handle(f.Fd()), 0, 1, 0, &overlapped); _ = f.Close() }, nil
		}
		if time.Now().After(deadline) {
			f.Close()
			return nil, err
		}
		time.Sleep(10 * time.Millisecond)
	}
}
