package hooks

import (
	"context"
	"crypto/sha256"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unsafe"

	"github.com/Microsoft/go-winio"
	"golang.org/x/sys/windows"
	"skill-manager/scanner/internal/aidr/privatefs"
)

// Windows pipe I/O shares the command bridge's four-second submission budget.
const hookConnectionTimeout = 4 * time.Second

type hookPipeConn struct {
	net.Conn
	server bool
}
type hookPipeListener struct{ net.Listener }

func (l hookPipeListener) Accept() (net.Conn, error) {
	c, err := l.Listener.Accept()
	if err != nil {
		return nil, err
	}
	return hookPipeConn{c, true}, nil
}

func hookPipeName(path string) (string, error) {
	sid, err := privatefs.UserSID()
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256([]byte(sid + "\x00" + strings.ToLower(filepath.Clean(path))))
	return fmt.Sprintf(`\\.\pipe\agent-manager-hook-%x`, digest[:16]), nil
}

func Listen(path string, store *Store) (*Receiver, error) {
	if store == nil || !filepath.IsAbs(path) || privatefs.Check(filepath.Dir(path)) != nil {
		return nil, code("aidr_hook_socket_invalid")
	}
	if err := ValidateBridgePrivateFile(path); err != nil {
		return nil, err
	}
	name, err := hookPipeName(path)
	if err != nil {
		return nil, err
	}
	sid, err := privatefs.UserSID()
	if err != nil {
		return nil, err
	}
	// go-winio reserves the first instance and rejects remote clients.
	l, err := winio.ListenPipe(name, &winio.PipeConfig{SecurityDescriptor: "D:P(A;;GA;;;" + sid + ")"})
	if err != nil {
		return nil, code("aidr_hook_socket_exists")
	}
	// Keep a private filesystem marker for health and upgrade journals. A crash
	// releases the kernel pipe; a stale marker cannot reserve or remove a pipe.
	if err = os.WriteFile(path, []byte(name), 0600); err != nil {
		l.Close()
		return nil, err
	}
	info, err := os.Lstat(path)
	if err != nil {
		l.Close()
		return nil, err
	}
	return &Receiver{store: store, listener: hookPipeListener{l}, path: path, file: info, startedAt: time.Now().UTC().Format(time.RFC3339Nano)}, nil
}

func dialHookEndpoint(ctx context.Context, path string) (net.Conn, error) {
	if !filepath.IsAbs(path) || ValidateBridgePrivateFile(path) != nil {
		return nil, code("aidr_hook_socket_invalid")
	}
	name, err := hookPipeName(path)
	if err != nil {
		return nil, err
	}
	bounded, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	c, err := winio.DialPipeContext(bounded, name)
	if err != nil {
		return nil, err
	}
	return hookPipeConn{c, false}, nil
}

var pipeKernel = windows.NewLazySystemDLL("kernel32.dll")
var pipeClientPID = pipeKernel.NewProc("GetNamedPipeClientProcessId")
var pipeServerPID = pipeKernel.NewProc("GetNamedPipeServerProcessId")

func pipePeerPID(c net.Conn) (uint32, error) {
	p, ok := c.(hookPipeConn)
	if !ok {
		return 0, code("aidr_hook_peer_rejected")
	}
	f, ok := p.Conn.(interface{ Fd() uintptr })
	if !ok {
		return 0, code("aidr_hook_peer_rejected")
	}
	proc := pipeServerPID
	if p.server {
		proc = pipeClientPID
	}
	var pid uint32
	result, _, err := proc.Call(f.Fd(), uintptr(unsafe.Pointer(&pid)))
	if result == 0 || pid == 0 {
		return 0, err
	}
	return pid, nil
}

func authenticatedPeer(c net.Conn) (string, error) {
	pid, err := pipePeerPID(c)
	if err != nil {
		return "", err
	}
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, pid)
	if err != nil {
		return "", err
	}
	defer windows.CloseHandle(h)
	var token windows.Token
	if err := windows.OpenProcessToken(h, windows.TOKEN_QUERY, &token); err != nil {
		return "", err
	}
	defer token.Close()
	u, err := token.GetTokenUser()
	if err != nil {
		return "", err
	}
	sid, err := privatefs.UserSID()
	if err != nil || u.User.Sid.String() != sid {
		return "", code("aidr_hook_peer_rejected")
	}
	return sid, nil
}

func bridgeProcessForConn(net.Conn) *BridgeProcess { return nil }

func (r *Receiver) SocketIdentity() (map[string]string, error) {
	name, err := hookPipeName(r.path)
	return map[string]string{"kind": "aidr_receiver_pipe", "pipe": name}, err
}
