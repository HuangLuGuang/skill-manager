//go:build windows

package localstore

import (
	"errors"
	"golang.org/x/sys/windows"
	"os"
)

// The Windows deployment must supply a per-user ACL-protected state directory.
// POSIX permission bits cannot certify Windows ACL isolation.
func privateDirectory(path string) error {
	i, e := os.Stat(path)
	if e != nil {
		return e
	}
	if !i.IsDir() {
		return errors.New("aidr_store_path_invalid")
	}
	return nil
}
func lockDirectory(path string) (*os.File, error) {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	e = windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &windows.Overlapped{})
	if e != nil {
		f.Close()
		return nil, errors.New("aidr_store_busy")
	}
	return f, nil
}
