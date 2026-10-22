//go:build !windows

package managedclient

import (
	"fmt"
	"net"
	"os"
	"path/filepath"
	"syscall"
)

func listenDesktop(home string) (net.Listener, func(), error) {
	root := filepath.Join(home, ".agent-manager", "desktop-ipc")
	if err := os.MkdirAll(root, 0700); err != nil {
		return nil, nil, err
	}
	info, err := os.Lstat(root)
	if err != nil {
		return nil, nil, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !info.IsDir() || info.Mode().Perm()&0077 != 0 || !ok || stat.Uid != uint32(os.Geteuid()) {
		return nil, nil, fmt.Errorf("client_ipc_directory_permissions")
	}
	lock, err := os.OpenFile(filepath.Join(root, "owner.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, nil, err
	}
	if err := lockClientFile(lock); err != nil {
		lock.Close()
		return nil, nil, err
	}
	path := filepath.Join(root, "desktop.sock")
	// Only the lock owner may reclaim a socket left by a terminated daemon.
	if info, err := os.Lstat(path); err == nil {
		if info.Mode()&os.ModeSocket == 0 {
			lock.Close()
			return nil, nil, fmt.Errorf("client_ipc_path_not_socket")
		}
		if err := os.Remove(path); err != nil {
			lock.Close()
			return nil, nil, err
		}
	}
	listener, err := net.Listen("unix", path)
	if err != nil {
		lock.Close()
		return nil, nil, err
	}
	return listener, func() { listener.Close(); lock.Close() }, nil
}
