//go:build !windows

package managedclient

import (
	"golang.org/x/sys/unix"
	"os"
)

func redirectDiagnosticOutput(writer *os.File) (func(), error) {
	out, err := unix.Dup(1)
	if err != nil {
		return nil, err
	}
	errout, err := unix.Dup(2)
	if err != nil {
		unix.Close(out)
		return nil, err
	}
	restore := func() {
		_ = unix.Dup2(out, 1)
		_ = unix.Dup2(errout, 2)
		unix.Close(out)
		unix.Close(errout)
	}
	if err = unix.Dup2(int(writer.Fd()), 1); err != nil {
		restore()
		return nil, err
	}
	if err = unix.Dup2(int(writer.Fd()), 2); err != nil {
		restore()
		return nil, err
	}
	return restore, nil
}
