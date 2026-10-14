package hooks

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"

	"skill-manager/scanner/internal/runtimeinfo"
)

func proxyListener(address string) (net.Listener, error) {
	if value := os.Getenv("AGENT_MANAGER_PROXY_LISTENER_FD"); value != "" {
		_ = os.Unsetenv("AGENT_MANAGER_PROXY_LISTENER_FD")
		fd, err := strconv.Atoi(value)
		if err != nil || fd < 3 {
			return nil, code("aidr_teleagent_listener_invalid")
		}
		f := os.NewFile(uintptr(fd), "proxy-listener")
		defer f.Close()
		l, err := net.FileListener(f)
		if err != nil {
			return nil, err
		}
		if l.Addr().String() != address {
			l.Close()
			return nil, code("aidr_teleagent_listener_invalid")
		}
		return l, nil
	}
	return net.Listen("tcp", address)
}
func checkProxyCandidate(home, binary string) (runtimeinfo.Info, error) {
	var info runtimeinfo.Info
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, "aidr-teleagent-service", "--home", home, "--action", "check")
	// Preflight must never consume a listener inherited by its parent.
	for _, e := range os.Environ() {
		if !strings.HasPrefix(e, "AGENT_MANAGER_PROXY_LISTENER_FD=") {
			cmd.Env = append(cmd.Env, e)
		}
	}
	out, err := cmd.Output()
	if err != nil {
		return info, err
	}
	err = json.Unmarshal(out, &info)
	if err == nil && info.SHA256 == "" {
		err = code("aidr_teleagent_candidate_invalid")
	}
	return info, err
}
func execProxyCandidate(home string, c proxyCandidate, l net.Listener) error {
	file, err := l.(*net.TCPListener).File()
	if err != nil {
		return err
	}
	defer file.Close()
	// File() creates a close-on-exec duplicate. Only this listener is inherited.
	_, _, errno := syscall.Syscall(syscall.SYS_FCNTL, file.Fd(), syscall.F_SETFD, 0)
	if errno != 0 {
		return errno
	}
	env := append(os.Environ(), "AGENT_MANAGER_PROXY_LISTENER_FD="+strconv.Itoa(int(file.Fd())))
	return syscall.Exec(c.Binary, []string{c.Binary, "aidr-teleagent-service", "--home", home}, env)
}
