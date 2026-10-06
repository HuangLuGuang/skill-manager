//go:build darwin || linux

package hooks

import (
	"strconv"
	"syscall"
)

// SocketIdentity reports the instance created by Listen, not a later path lookup.
// Desktop supervision receives this only through its own child's stdout pipe.
func (r *Receiver) SocketIdentity() (map[string]string, error) {
	stat, ok := r.file.Sys().(*syscall.Stat_t)
	if !ok {
		return nil, code("aidr_hook_socket_invalid")
	}
	return map[string]string{"kind": "aidr_receiver_socket", "device": strconv.FormatUint(uint64(stat.Dev), 10), "inode": strconv.FormatUint(stat.Ino, 10)}, nil
}
