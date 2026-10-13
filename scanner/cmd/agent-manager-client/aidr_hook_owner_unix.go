//go:build darwin || linux

package main

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

func acquireHookSupervisor(root string) (func(), error) {
	fd, err := unix.Open(filepath.Join(root, "supervisor.lock"), unix.O_CREAT|unix.O_RDWR|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0600)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(fd), "supervisor.lock")
	if err = unix.Flock(fd, unix.LOCK_EX|unix.LOCK_NB); err != nil {
		file.Close()
		return nil, err
	}
	return func() { file.Close() }, nil
}

// Called only by the daemon holding supervisor.lock and the queue writer lock.
// Recover its exact journaled inode after a crash, never an unknown endpoint.
func recoverManagedHookSocket(socket string) error {
	info, err := os.Lstat(socket)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	var proof map[string]string
	if readDesktopJSON(socket+".owner.json", &proof) != nil {
		return errors.New("aidr_hook_socket_exists")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || info.Mode()&os.ModeSocket == 0 || stat.Uid != uint32(os.Geteuid()) || proof["kind"] != "aidr_receiver_socket" || proof["device"] != strconv.FormatUint(uint64(stat.Dev), 10) || proof["inode"] != strconv.FormatUint(stat.Ino, 10) {
		return errors.New("aidr_hook_socket_exists")
	}
	c, err := net.DialTimeout("unix", socket, 200*time.Millisecond)
	if err == nil {
		c.Close()
		return errors.New("aidr_hook_socket_exists")
	}
	if !errors.Is(err, syscall.ECONNREFUSED) {
		return errors.New("aidr_hook_socket_exists")
	}
	if after, err := os.Lstat(socket); err != nil || !os.SameFile(info, after) {
		return errors.New("aidr_hook_socket_exists")
	}
	return os.Remove(socket)
}
