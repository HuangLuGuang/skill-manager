//go:build darwin || linux

package localstore

import (
	"errors"
	"golang.org/x/sys/unix"
	"os"
)

func privateDirectory(path string) error {
	i, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !i.IsDir() || i.Mode().Perm()&0077 != 0 {
		return errors.New("aidr_store_directory_not_private")
	}
	return nil
}
func lockDirectory(path string) (*os.File, error) {
	// Host inspection processes must not retain the collector's writer lock.
	fd, err := unix.Open(path, unix.O_CREAT|unix.O_RDWR|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0600)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), path)
	if err = unix.Flock(fd, unix.LOCK_EX|unix.LOCK_NB); err != nil {
		f.Close()
		return nil, errors.New("aidr_store_busy")
	}
	return f, nil
}
