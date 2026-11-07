package hooks

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestWindowsGUIBridgeWaitsForDecision(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(dir, "main.go")
	binary := filepath.Join(dir, "客户's bridge.exe")
	if err := os.WriteFile(source, []byte(`package main
import ("io"; "os"; "time")
func main() {
 input, _ := io.ReadAll(os.Stdin)
 time.Sleep(700*time.Millisecond)
 if err := os.WriteFile(os.Args[1], input, 0600); err != nil { os.Exit(3) }
 switch os.Args[2] {
 case "json": os.Stdout.Write(input)
 case "deny": os.Stderr.WriteString("aidr_hook_rule_deny"); os.Exit(2)
 }
}
`), 0600); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("go", "build", "-ldflags=-H=windowsgui", "-o", binary, source).CombinedOutput(); err != nil {
		t.Fatalf("build production-subsystem helper: %v: %s", err, out)
	}
	for _, mode := range []string{"json", "allow", "deny"} {
		for _, host := range []string{"encoded", "direct", "captured"} {
			t.Run(mode+"/"+host, func(t *testing.T) {
				receipt := filepath.Join(t.TempDir(), "receipt")
				args := []string{receipt, mode, "--event", "PreToolUse"}
				script := windowsHookScript(binary, args)
				ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
				defer cancel()
				cmd := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script)
				if host == "encoded" {
					cmd = exec.CommandContext(ctx, "cmd.exe", "/d", "/s", "/c", windowsHookCommand(binary, args))
				} else if host == "captured" {
					cmd = exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", windowsCapturedHookScript(binary, args))
				}
				// Files avoid Go's pipe-copy wait masking a prematurely exiting shell.
				out, err := os.CreateTemp(t.TempDir(), "stdout")
				if err != nil {
					t.Fatal(err)
				}
				defer out.Close()
				stderr, err := os.CreateTemp(t.TempDir(), "stderr")
				if err != nil {
					t.Fatal(err)
				}
				defer stderr.Close()
				want := `{"command":"echo 中文"}`
				cmd.Stdin, cmd.Stdout, cmd.Stderr = strings.NewReader(want), out, stderr
				err = cmd.Run()
				got, readErr := os.ReadFile(receipt)
				if readErr != nil || string(bytes.TrimSpace(got)) != want {
					t.Fatalf("shell returned before decision/input receipt: %q %v (%v)", got, readErr, err)
				}
				output, _ := os.ReadFile(out.Name())
				diagnostic, _ := os.ReadFile(stderr.Name())
				code := 0
				if mode == "deny" {
					code = 2
				}
				if cmd.ProcessState == nil || cmd.ProcessState.ExitCode() != code {
					t.Fatalf("lost decision exit %d: %v stdout=%s stderr=%s", code, err, output, diagnostic)
				}
				if mode == "json" && string(bytes.TrimSpace(output)) != want {
					t.Fatalf("lost response: %s", output)
				}
				if mode != "json" && len(bytes.TrimSpace(output)) != 0 {
					t.Fatalf("unexpected response: %s", output)
				}
			})
		}
	}
}
