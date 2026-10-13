package hooks

import (
	"context"
	"crypto/sha256"
	"fmt"
	"html"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

func teleAgentServiceLabel(home string) string {
	sum := sha256.Sum256([]byte(filepath.Clean(home)))
	return fmt.Sprintf("com.agent-manager.teleagent-proxy.%x", sum[:6])
}

func teleAgentServiceDefinition(home, binary string) (string, []byte) {
	label := teleAgentServiceLabel(home)
	logPath := filepath.Join(home, ".agent-manager/aidr/teleagent-proxy/service.log")
	body := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>%s</string>
<key>ProgramArguments</key><array><string>%s</string><string>aidr-teleagent-service</string><string>--home</string><string>%s</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>5</integer>
<key>StandardOutPath</key><string>%s</string>
<key>StandardErrorPath</key><string>%s</string>
</dict></plist>
`, label, html.EscapeString(binary), html.EscapeString(home), html.EscapeString(logPath), html.EscapeString(logPath))
	return filepath.Join(home, "Library/LaunchAgents", label+".plist"), []byte(body)
}

// Stage a private executable outside the app bundle. Replacing its directory entry
// leaves the running proxy and active streams intact; launchd uses it on next start.
func stageTeleAgentProxy(source, target string) error {
	src, err := os.Open(source)
	if err != nil {
		return err
	}
	defer src.Close()
	f, err := os.CreateTemp(filepath.Dir(target), ".proxy-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	hash := sha256.New()
	if _, err = io.Copy(io.MultiWriter(f, hash), src); err != nil {
		return err
	}
	if old, e := os.Open(target); e == nil {
		h := sha256.New()
		_, e = io.Copy(h, old)
		old.Close()
		if e == nil && string(h.Sum(nil)) == string(hash.Sum(nil)) {
			return nil
		}
	}
	if err = f.Chmod(0700); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), target)
}

func teleAgentLaunchctl(args ...string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return exec.CommandContext(ctx, "launchctl", args...).Run()
}

// Ensure registers once and never stops or kickstarts an existing service.
// Desktop shutdown and prepare-update do not own this LaunchAgent.
func EnsureTeleAgentProxyService(home, executable string) error {
	if !TeleAgentProxyRequired(home) {
		return nil
	}
	if !filepath.IsAbs(home) || !filepath.IsAbs(executable) || os.Getuid() == 0 {
		return code("aidr_teleagent_service_failed")
	}
	if _, err := readTeleAgentState(home); err != nil {
		return code("aidr_teleagent_config_invalid")
	}
	root := filepath.Join(home, ".agent-manager/aidr/teleagent-proxy")
	if err := os.MkdirAll(root, 0700); err != nil {
		return code("aidr_teleagent_service_failed")
	}
	lock, err := os.OpenFile(filepath.Join(root, "install.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return code("aidr_teleagent_service_failed")
	}
	defer lock.Close()
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return code("aidr_desktop_action_busy")
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
	binary := filepath.Join(root, "agent-manager-client")
	if err = stageTeleAgentProxy(executable, binary); err != nil {
		return code("aidr_teleagent_service_failed")
	}
	path, body := teleAgentServiceDefinition(home, binary)
	if err = teleAgentAtomic(path, body); err != nil {
		return code("aidr_teleagent_service_failed")
	}
	domain := fmt.Sprintf("gui/%d", os.Getuid())
	if teleAgentLaunchctl("print", domain+"/"+teleAgentServiceLabel(home)) == nil {
		return nil
	}
	if teleAgentLaunchctl("bootstrap", domain, path) != nil {
		return code("aidr_teleagent_service_failed")
	}
	return nil
}
