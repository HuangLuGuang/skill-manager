package hooks

import (
	"net"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"golang.org/x/sys/unix"
)

func TestBridgeProcessFromKernelSocket(t *testing.T) {
	root, err := os.MkdirTemp("/private/tmp", "aidr-peer-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(root) })
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: filepath.Join(root, "p.sock"), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	c, err := net.DialUnix("unix", nil, l.Addr().(*net.UnixAddr))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	peer, err := l.AcceptUnix()
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	got := bridgeProcess(peer)
	if got == nil {
		t.Fatal("kernel peer identity unavailable")
	}
	info, err := unix.SysctlKinfoProc("kern.proc.pid", os.Getpid())
	if err != nil {
		t.Fatal(err)
	}
	start := strconv.FormatInt(info.Proc.P_starttime.Sec*1000000+int64(info.Proc.P_starttime.Usec), 10)
	if got.PID != strconv.Itoa(os.Getpid()) || got.StartUS != start || got.PIDVersion == "" || got.Role != "ipc_bridge" {
		t.Fatalf("unexpected peer: %+v", got)
	}
}
