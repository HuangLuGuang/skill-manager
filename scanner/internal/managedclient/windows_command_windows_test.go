//go:build windows

package managedclient

import (
	"os/exec"
	"testing"
)

func TestWindowsPowerShellCommandDoesNotCreateConsole(t *testing.T) {
	command := windowsPowerShellCommand("exit 0")
	if command.SysProcAttr == nil || !command.SysProcAttr.HideWindow {
		t.Fatal("PowerShell child process is not hidden")
	}
	if command.SysProcAttr.CreationFlags&windowsCreateNoWindow == 0 {
		t.Fatal("PowerShell child process can still allocate a console window")
	}
}

func TestWindowsAgentCommandDoesNotCreateConsole(t *testing.T) {
	command := configureWindowsCommand(exec.Command("agent.exe", "--version"))
	if command.SysProcAttr == nil || !command.SysProcAttr.HideWindow {
		t.Fatal("Agent child process is not hidden")
	}
	if command.SysProcAttr.CreationFlags&windowsCreateNoWindow == 0 {
		t.Fatal("Agent child process can still allocate a console window")
	}
}
