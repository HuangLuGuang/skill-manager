//go:build !windows

package hooks

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
)

// Keep host work in its own process group. Cancelling a query or finishing a
// short-lived host must also stop children that inherited its pipes or downloads.
func startNativeProcess(cmd *exec.Cmd) (func(), error) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return os.ErrProcessDone
		}
		err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return os.ErrProcessDone
		}
		return err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	return func() { _ = cmd.Cancel() }, nil
}
