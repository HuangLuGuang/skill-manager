//go:build !windows

package hooks

import (
	"context"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

const hookConnectionTimeout = 2 * time.Second

// Listen requires an existing private, caller-owned directory. Existing sockets
// are never removed: an active or stale listener is a visible startup failure.
func Listen(path string, store *Store) (*Receiver, error) {
	if store == nil || !filepath.IsAbs(path) {
		return nil, code("aidr_hook_socket_invalid")
	}
	dir := filepath.Dir(path)
	real, err := filepath.EvalSymlinks(dir)
	if err != nil || real != dir {
		return nil, code("aidr_hook_socket_invalid")
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 || !ownedBy(info, uint32(os.Geteuid())) {
		return nil, code("aidr_hook_socket_invalid")
	}
	if _, err = os.Lstat(path); !os.IsNotExist(err) {
		return nil, code("aidr_hook_socket_exists")
	}
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, code("aidr_hook_socket_unavailable")
	}
	l.SetUnlinkOnClose(false)
	if err = os.Chmod(path, 0600); err != nil {
		l.Close()
		os.Remove(path)
		return nil, code("aidr_hook_socket_invalid")
	}
	info, err = os.Lstat(path)
	if err != nil {
		l.Close()
		return nil, code("aidr_hook_socket_invalid")
	}
	return &Receiver{store: store, listener: l, path: path, file: info, startedAt: time.Now().UTC().Format(time.RFC3339Nano)}, nil
}

func dialHookEndpoint(ctx context.Context, path string) (net.Conn, error) {
	return (&net.Dialer{Timeout: time.Second}).DialContext(ctx, "unix", path)
}
func authenticatedPeer(c net.Conn) (string, error) {
	u, ok := c.(*net.UnixConn)
	if !ok {
		return "", code("aidr_hook_peer_rejected")
	}
	uid, err := peerUID(u)
	if err != nil || uid != uint32(os.Geteuid()) {
		return "", code("aidr_hook_peer_rejected")
	}
	return strconv.FormatUint(uint64(uid), 10), nil
}
func bridgeProcessForConn(c net.Conn) *BridgeProcess {
	u, ok := c.(*net.UnixConn)
	if !ok {
		return nil
	}
	return bridgeProcess(u)
}
