//go:build darwin || linux

package hooks

import (
	"context"
	"net"
	"os"
	"path/filepath"
	"testing"
)

func TestReceiverDiagnosticVerifiesPeerAndBindingWithoutMutation(t *testing.T) {
	root, e := os.MkdirTemp("", "aidr-diag-")
	if e != nil {
		t.Fatal(e)
	}
	defer os.RemoveAll(root)
	root, e = filepath.EvalSymlinks(root)
	if e != nil {
		t.Fatal(e)
	}
	queue := filepath.Join(root, "state")
	s := openTestStore(t, queue, 10)
	socket := filepath.Join(root, "r.sock")
	r, e := Listen(socket, s)
	if e != nil {
		t.Fatal(e)
	}
	defer r.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go r.Serve(ctx)
	exe, _ := os.Executable()
	server, device := s.Destination()
	before, _ := os.Lstat(socket)
	d := DiagnoseReceiver(ctx, socket, queue, server, device, exe)
	if d.Ownership != "external_verified" || d.PID != os.Getpid() || d.State == nil || d.Receiver.Queue != queue {
		t.Fatalf("diagnostic: %+v", d)
	}
	for _, binding := range []struct{ queue, server, device, binary string }{{queue, server, "different", exe}, {queue, server + "/other", device, exe}, {queue + "other", server, device, exe}, {queue, server, device, "/missing"}} {
		d = DiagnoseReceiver(ctx, socket, binding.queue, binding.server, binding.device, binding.binary)
		if d.Ownership != "external_unverified" || d.State != nil {
			t.Fatalf("unverified binding: %+v", d)
		}
	}
	after, _ := os.Lstat(socket)
	if !os.SameFile(before, after) {
		t.Fatal("diagnosis changed socket")
	}
}
func TestReceiverDiagnosticPreservesStaleSocketAndRejectsPublicParent(t *testing.T) {
	root, e := os.MkdirTemp("", "aidr-stale-")
	if e != nil {
		t.Fatal(e)
	}
	defer os.RemoveAll(root)
	root, _ = filepath.EvalSymlinks(root)
	p := filepath.Join(root, "r.sock")
	l, e := net.ListenUnix("unix", &net.UnixAddr{Name: p, Net: "unix"})
	if e != nil {
		t.Fatal(e)
	}
	l.SetUnlinkOnClose(false)
	os.Chmod(p, 0600)
	l.Close()
	before, _ := os.Lstat(p)
	d := DiagnoseReceiver(context.Background(), p, "q", "https://example.test", "d", "/missing")
	after, _ := os.Lstat(p)
	if d.Ownership != "external_unverified" || !os.SameFile(before, after) {
		t.Fatalf("stale socket: %+v", d)
	}
	os.Chmod(root, 0755)
	d = DiagnoseReceiver(context.Background(), p, "q", "https://example.test", "d", "/missing")
	if d.Code != "aidr_hook_socket_invalid" {
		t.Fatalf("public parent: %+v", d)
	}
}
func TestDiagnosticDestinationRedactsCredentials(t *testing.T) {
	if got := diagnosticServer("https://user:secret@example.test/path?token=secret#secret"); got != "https://example.test/path" {
		t.Fatal(got)
	}
}
