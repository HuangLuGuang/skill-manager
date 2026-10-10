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
	e = raw.Control(func(fd uintptr) {
		cred, err := unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
		inner = err
		if err == nil {
			pid = int(cred.Pid)
		}
	})
	if e != nil {
		return 0, e
	}
	return pid, inner
}
