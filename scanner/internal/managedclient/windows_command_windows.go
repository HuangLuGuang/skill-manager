//go:build windows

package managedclient

import (
	"os/exec"
	"syscall"
)

const windowsCreateNoWindow = 0x08000000

func configureWindowsCommand(command *exec.Cmd) *exec.Cmd {
	command.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: windowsCreateNoWindow,
	}
	return command
}
