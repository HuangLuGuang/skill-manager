package managedclient

import (
	"golang.org/x/sys/windows"
	"os"
)

func redirectDiagnosticOutput(writer *os.File) (func(), error) {
	out, err := windows.GetStdHandle(windows.STD_OUTPUT_HANDLE)
	if err != nil {
		return nil, err
	}
	errout, err := windows.GetStdHandle(windows.STD_ERROR_HANDLE)
	if err != nil {
		return nil, err
	}
	stdout, stderr := os.Stdout, os.Stderr
	restore := func() {
		_ = windows.SetStdHandle(windows.STD_OUTPUT_HANDLE, out)
		_ = windows.SetStdHandle(windows.STD_ERROR_HANDLE, errout)
		os.Stdout, os.Stderr = stdout, stderr
	}
	if err = windows.SetStdHandle(windows.STD_OUTPUT_HANDLE, windows.Handle(writer.Fd())); err != nil {
		return nil, err
	}
	if err = windows.SetStdHandle(windows.STD_ERROR_HANDLE, windows.Handle(writer.Fd())); err != nil {
		restore()
		return nil, err
	}
	os.Stdout, os.Stderr = writer, writer
	return restore, nil
}
