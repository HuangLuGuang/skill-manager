package hooks

import (
	"net"
	"strconv"
	"strings"
	"syscall"
	"unsafe"

	"golang.org/x/sys/unix"
)

// bridgeProcess observes the IPC bridge, never the requested tool process.
// Audit-token identity and a separately read start time form a candidate that
// requires an exact match against independently collected OS evidence.
func bridgeProcess(c *net.UnixConn) *BridgeProcess {
	raw, err := c.SyscallConn()
	if err != nil {
		return nil
	}
	var token [8]uint32
	length := uint32(unsafe.Sizeof(token))
	var errno syscall.Errno
	err = raw.Control(func(fd uintptr) {
		_, _, errno = syscall.Syscall6(syscall.SYS_GETSOCKOPT, fd, unix.SOL_LOCAL, unix.LOCAL_PEERTOKEN,
			uintptr(unsafe.Pointer(&token)), uintptr(unsafe.Pointer(&length)), 0)
	})
	if err != nil || errno != 0 || length != 32 || token[5] == 0 || token[7] == 0 {
		return nil
	}
	boot, err := unix.Sysctl("kern.bootsessionuuid")
	if err != nil {
		return nil
	}
	info, err := unix.SysctlKinfoProc("kern.proc.pid", int(token[5]))
	if err != nil || info.Proc.P_pid != int32(token[5]) || info.Proc.P_starttime.Sec <= 0 {
		return nil
	}
	start := info.Proc.P_starttime.Sec*1000000 + int64(info.Proc.P_starttime.Usec)
	return &BridgeProcess{BootID: strings.ToLower(strings.TrimSpace(boot)), PID: strconv.FormatUint(uint64(token[5]), 10),
		PIDVersion: strconv.FormatUint(uint64(token[7]), 10), StartUS: strconv.FormatInt(start, 10),
		Method: "macos_socket_audit_token_sysctl", Role: "ipc_bridge"}
}
