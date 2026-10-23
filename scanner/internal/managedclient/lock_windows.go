package managedclient

import (
	"errors"
	"os"

	"golang.org/x/sys/windows"
)

func lockClientFile(file *os.File) error {
	err := windows.LockFileEx(windows.Handle(file.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &windows.Overlapped{Offset: 0x7fffffff})
	if errors.Is(err, windows.ERROR_LOCK_VIOLATION) {
		return ErrAlreadyRunning
	}
	return err
}

func unlockClientFile(file *os.File) error {
	return windows.UnlockFileEx(windows.Handle(file.Fd()), 0, 1, 0, &windows.Overlapped{Offset: 0x7fffffff})
}

func clientProcessAlive(pid int) bool {
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return !errors.Is(err, windows.ERROR_INVALID_PARAMETER)
	}
	defer windows.CloseHandle(handle)
	var code uint32
	return windows.GetExitCodeProcess(handle, &code) != nil || code == 259
}

func lockClientFileShared(file *os.File) error {
	err := windows.LockFileEx(windows.Handle(file.Fd()), windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &windows.Overlapped{Offset: 0x7fffffff})
	if errors.Is(err, windows.ERROR_LOCK_VIOLATION) {
		return ErrAlreadyRunning
	}
	return err
}
