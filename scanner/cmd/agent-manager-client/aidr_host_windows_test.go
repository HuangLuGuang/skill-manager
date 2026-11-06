package main

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestWindowsNativeHostDiscovery(t *testing.T) {
	home := t.TempDir()
	write := func(path string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("synthetic discovery fixture"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	claude := filepath.Join(home, ".local", "bin", "claude.exe")
	write(claude)
	if got := desktopFindHost("claude", home); got.Binary != claude {
		t.Fatal(got)
	}
	npm := filepath.Join(home, "npm")
	write(filepath.Join(npm, "codex.cmd"))
	t.Setenv("PATH", npm)
	t.Setenv("PATHEXT", ".EXE;.CMD")
	if got := desktopFindHost("codex", home); got.Binary != "" {
		t.Fatal("batch shim accepted", got)
	}
	triple := "x86_64-pc-windows-msvc"
	if runtime.GOARCH == "arm64" {
		triple = "aarch64-pc-windows-msvc"
	}
	native := filepath.Join(npm, "node_modules", "@openai", "codex", "vendor", triple, "codex", "codex.exe")
	write(native)
	if got := desktopFindHost("codex", home); got.Binary != native {
		t.Fatal(got)
	}
	standalone := filepath.Join(home, ".codex", "packages", "standalone", "current", "bin", "codex.exe")
	write(standalone)
	if got := desktopFindHost("codex", home); got.Binary != standalone {
		t.Fatal(got)
	}
}
