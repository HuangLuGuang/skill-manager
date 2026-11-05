//go:build !windows

package privatefs

import (
	"errors"
	"os"
	"syscall"
)

func Check(path string) error {
	i, err := os.Lstat(path)
	if err != nil {
		return err
	}
	s, ok := i.Sys().(*syscall.Stat_t)
	if !ok || s.Uid != uint32(os.Geteuid()) || i.Mode()&os.ModeSymlink != 0 || i.Mode().Perm()&0077 != 0 {
		return errors.New("aidr_private_path_invalid")
	}
	return nil
}

func PrepareDirectory(path string) error {
	if err := os.MkdirAll(path, 0700); err != nil {
		return err
	}
	return Check(path)
}

func SecureFile(path string) error { return Check(path) }
