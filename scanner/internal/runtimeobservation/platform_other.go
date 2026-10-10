//go:build !darwin

package runtimeobservation

import (
	"net"
	"os"
)

func ownerUID(info os.FileInfo) (uint32, bool)   { return 0, false }
func dialVerified(path string) (net.Conn, error) { return nil, ErrUnsupported }
