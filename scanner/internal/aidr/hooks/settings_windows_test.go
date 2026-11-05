package hooks

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
)

func TestWindowsHookCommandHelper(t *testing.T) {
	if os.Getenv("AGENT_MANAGER_WINDOWS_COMMAND_TEST") != "1" {
		return
	}
	if _, err := io.Copy(os.Stdout, os.Stdin); err != nil {
		os.Exit(1)
	}
	os.Exit(0)
}

func TestWindowsHookCommandPreservesInput(t *testing.T) {
	root := filepath.Join(t.TempDir(), "Windows 队列 & spaces")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	self, _ := os.Executable()
	data, err := os.ReadFile(self)
	if err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(root, "bridge.exe")
	if err := os.WriteFile(binary, data, 0700); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("cmd.exe")
	command := shellArg(binary) + " -test.run=TestWindowsHookCommandHelper"
	cmd.SysProcAttr = &syscall.SysProcAttr{CmdLine: `cmd.exe /d /s /c "` + command + `"`}
	cmd.Env = append(os.Environ(), "AGENT_MANAGER_WINDOWS_COMMAND_TEST=1")
	want := []byte(`{"tool_input":{"command":"echo Windows 中文 & spaces"}}`)
	cmd.Stdin = bytes.NewReader(want)
	got, err := cmd.CombinedOutput()
	if err != nil || !bytes.Equal(got, want) {
		t.Fatalf("native command input: %q %v", got, err)
	}
}
