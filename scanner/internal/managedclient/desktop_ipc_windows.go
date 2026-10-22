package managedclient

import (
	"fmt"
	"net"
	"os"
	"path/filepath"

	"github.com/Microsoft/go-winio"
	"golang.org/x/sys/windows"
)

func listenDesktop(home string) (net.Listener, func(), error) {
	lock, err := os.OpenFile(filepath.Join(home, ".agent-manager", "desktop-ipc.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, nil, err
	}
	if err := lockClientFile(lock); err != nil {
		lock.Close()
		return nil, nil, err
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		lock.Close()
		return nil, nil, err
	}
	path := fmt.Sprintf(`\\.\pipe\agent-manager-desktop-%s`, eventID())
	listener, err := winio.ListenPipe(path, &winio.PipeConfig{
		SecurityDescriptor: "D:P(A;;GA;;;" + user.User.Sid.String() + ")",
	})
	if err != nil {
		lock.Close()
		return nil, nil, err
	}
	marker := filepath.Join(home, ".agent-manager", "desktop-pipe")
	temp := marker + ".tmp"
	if err := os.WriteFile(temp, []byte(path), 0600); err != nil {
		listener.Close()
		lock.Close()
		return nil, nil, err
	}
	if err := os.Rename(temp, marker); err != nil {
		os.Remove(temp)
		listener.Close()
		lock.Close()
		return nil, nil, err
	}
	return listener, func() { listener.Close(); os.Remove(marker); lock.Close() }, nil
}
