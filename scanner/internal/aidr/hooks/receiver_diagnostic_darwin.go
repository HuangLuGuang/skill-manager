package hooks

import (
	"golang.org/x/sys/unix"
	"net"
)

func diagnosticPeerPID(c *net.UnixConn) (int, error) {
	raw, e := c.SyscallConn()
	if e != nil {
		return 0, e
	}
	var pid int
	var inner error
	e = raw.Control(func(fd uintptr) { pid, inner = unix.GetsockoptInt(int(fd), unix.SOL_LOCAL, unix.LOCAL_PEERPID) })
	if e != nil {
		return 0, e
	}
	return pid, inner
}
