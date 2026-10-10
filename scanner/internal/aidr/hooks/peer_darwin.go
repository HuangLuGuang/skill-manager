package hooks

import (
	"golang.org/x/sys/unix"
	"net"
	"os"
	"syscall"
)

func ownedBy(info os.FileInfo, uid uint32) bool {
	s, ok := info.Sys().(*syscall.Stat_t)
	return ok && s.Uid == uid
}
func peerUID(c *net.UnixConn) (uint32, error) {
	raw, err := c.SyscallConn()
	if err != nil {
		return 0, err
	}
	var uid uint32
	var inner error
	err = raw.Control(func(fd uintptr) {
		var cred *unix.Xucred
		cred, inner = unix.GetsockoptXucred(int(fd), unix.SOL_LOCAL, unix.LOCAL_PEERCRED)
		if inner == nil {
			uid = cred.Uid
		}
	})
	if err != nil {
		return 0, err
	}
	return uid, inner
}
