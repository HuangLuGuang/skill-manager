//go:build !windows

package managedclient

import (
	"os"
	"path/filepath"
	"syscall"
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
	deadline := time.Now().Add(2 * time.Second)
	for {
		err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
		if err == nil {
			return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); _ = f.Close() }, nil
		}
		if time.Now().After(deadline) {
			f.Close()
			return nil, err
		}
		time.Sleep(10 * time.Millisecond)
	}
}
