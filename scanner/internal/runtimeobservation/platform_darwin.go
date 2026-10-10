//go:build darwin

package runtimeobservation

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

func ownerUID(info os.FileInfo) (uint32, bool) {
	value, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return 0, false
	}
	return value.Uid, true
}

func dialVerified(path string) (net.Conn, error) {
	if !filepath.IsAbs(path) {
		return nil, fmt.Errorf("runtime_observation_socket_path_absolute")
	}
	clean := filepath.Clean(path)
	info, err := os.Lstat(clean)
	if err != nil {
		return nil, fmt.Errorf("runtime_observation_socket_unavailable: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 {
		return nil, fmt.Errorf("runtime_observation_unsafe_socket_type")
	}
	uid, ok := ownerUID(info)
	if !ok || uid != uint32(os.Geteuid()) || info.Mode().Perm()&0077 != 0 {
		return nil, fmt.Errorf("runtime_observation_unsafe_socket_permissions")
	}
	for dir := filepath.Dir(clean); dir != "/"; dir = filepath.Dir(dir) {
		item, statErr := os.Lstat(dir)
		if statErr != nil {
			return nil, statErr
		}
		owner, ownerOK := ownerUID(item)
		if !ownerOK || owner != 0 || !item.IsDir() || item.Mode()&os.ModeSymlink != 0 || item.Mode().Perm()&0022 != 0 {
			return nil, fmt.Errorf("runtime_observation_unsafe_socket_path")
		}
	}
	conn, err := net.DialTimeout("unix", clean, 2*time.Second)
	if err != nil {
		return nil, err
	}
	unixConn := conn.(*net.UnixConn)
	raw, err := unixConn.SyscallConn()
	if err != nil {
		conn.Close()
		return nil, err
	}
	var peer uint32
	var controlErr error
	err = raw.Control(func(fd uintptr) {
		var cred *unix.Xucred
		cred, controlErr = unix.GetsockoptXucred(int(fd), unix.SOL_LOCAL, unix.LOCAL_PEERCRED)
		if controlErr == nil {
			peer = cred.Uid
		}
	})
	if err != nil || controlErr != nil || peer != 0 {
		conn.Close()
		return nil, fmt.Errorf("runtime_observation_untrusted_peer")
	}
	return conn, nil
}
