//go:build !darwin && !linux

package hooks

import (
	"net"
	"os"
)

func ownedBy(os.FileInfo, uint32) bool      { return false }
func peerUID(*net.UnixConn) (uint32, error) { return 0, code("aidr_hook_ipc_unsupported") }
