//go:build !darwin && !linux

package hooks

import "net"

func diagnosticPeerPID(*net.UnixConn) (int, error) { return 0, code("aidr_hook_ipc_unsupported") }
