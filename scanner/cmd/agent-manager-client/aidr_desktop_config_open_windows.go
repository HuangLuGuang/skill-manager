package main

import (
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
)

var replaceDesktopFile = windows.NewLazySystemDLL("kernel32.dll").NewProc("ReplaceFileW")

func replaceDesktopConfig(from, to string) error {
	source, err := windows.UTF16PtrFromString(from)
	if err != nil {
		return err
	}
	target, err := windows.UTF16PtrFromString(to)
	if err != nil {
		return err
	}
	// MoveFileEx cannot replace an open destination even with delete sharing.
	ok, _, err := replaceDesktopFile.Call(uintptr(unsafe.Pointer(target)), uintptr(unsafe.Pointer(source)), 0, 0, 0, 0)
	if ok != 0 {
		return nil
	}
	if err == windows.ERROR_FILE_NOT_FOUND {
		return os.Rename(from, to)
	}
	return &os.LinkError{Op: "replace", Old: from, New: to, Err: err}
}

func openDesktopConfig(path string) (*os.File, error) {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	// Status readers must allow the writer to atomically replace the old file.
	handle, err := windows.CreateFile(name, windows.GENERIC_READ, windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING, windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(handle), path), nil
}
