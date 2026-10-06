//go:build darwin || linux

package agentlog

import (
	"fmt"
	"os"
	"syscall"
)

func fileIdentity(_ *os.File, info os.FileInfo) (string, error) {
	s := info.Sys().(*syscall.Stat_t)
	return fmt.Sprintf("%d:%d", s.Dev, s.Ino), nil
}
