//go:build !windows

package managedclient

import "os/exec"

func configureWindowsCommand(command *exec.Cmd) *exec.Cmd {
	return command
}
