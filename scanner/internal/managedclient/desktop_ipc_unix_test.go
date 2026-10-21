//go:build !windows

package managedclient

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"testing"
)

func BenchmarkDesktopUnixIPC(b *testing.B) {
	home, err := os.MkdirTemp("/tmp", "am-bench-")
	if err != nil {
		b.Fatal(err)
	}
	defer os.RemoveAll(home)
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		b.Fatal(err)
	}
	defer store.Close()
	benchmarkInventory(b, store)
	listener, cleanup, err := listenDesktop(home)
	if err != nil {
		b.Fatal(err)
	}
	defer cleanup()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- serveDesktop(ctx, home, listener) }()
	defer func() { cancel(); <-done }()
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		conn, err := net.Dial("unix", filepath.Join(home, ".agent-manager", "desktop-ipc", "desktop.sock"))
		if err != nil {
			b.Fatal(err)
		}
		if _, err := conn.Write([]byte("{\"version\":1,\"method\":\"snapshot\"}\n")); err != nil {
			b.Fatal(err)
		}
		var response map[string]any
		err = json.NewDecoder(conn).Decode(&response)
		conn.Close()
		if err != nil || response["inventory"] == nil {
			b.Fatalf("snapshot: %v", err)
		}
	}
}

func TestDesktopSocketOwnership(t *testing.T) {
	home, err := os.MkdirTemp("/tmp", "am-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(home)
	listener, cleanup, err := listenDesktop(home)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if listener == nil {
		t.Fatal("missing listener")
	}
	if _, secondCleanup, err := listenDesktop(home); err == nil {
		secondCleanup()
		t.Fatal("second owner accepted")
	}
	root := filepath.Join(home, ".agent-manager", "desktop-ipc")
	os.Chmod(root, 0755)
	if _, cleanup, err := listenDesktop(home); err == nil {
		cleanup()
		t.Fatal("shared directory accepted")
	}
}

func TestDesktopSocketDoesNotRemoveRegularFile(t *testing.T) {
	home, err := os.MkdirTemp("/tmp", "am-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(home)
	root := filepath.Join(home, ".agent-manager", "desktop-ipc")
	os.MkdirAll(root, 0700)
	path := filepath.Join(root, "desktop.sock")
	os.WriteFile(path, []byte("keep"), 0600)
	if _, cleanup, err := listenDesktop(home); err == nil {
		cleanup()
		t.Fatal("regular file accepted")
	}
	body, _ := os.ReadFile(path)
	if string(body) != "keep" {
		t.Fatal("existing file changed")
	}
}
