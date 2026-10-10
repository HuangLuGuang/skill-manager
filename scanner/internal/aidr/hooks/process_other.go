//go:build !darwin

package hooks

import "net"

func bridgeProcess(c *net.UnixConn) *BridgeProcess { return nil }
