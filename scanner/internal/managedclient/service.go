package managedclient

import (
	"fmt"
	"html"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

type ServiceState struct {
	Installed bool   `json:"installed"`
	Running   bool   `json:"running"`
	Detail    string `json:"detail,omitempty"`
}

func ServiceDefinition(home, executable, goos string) (string, string, error) {
	switch goos {
	case "darwin":
		path := filepath.Join(home, "Library", "LaunchAgents", "com.agent-manager.client.plist")
		body := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.agent-manager.client</string>
  <key>ProgramArguments</key>
  <array>
    <string>%s</string><string>run</string><string>--home</string><string>%s</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict>
</plist>
`,
			html.EscapeString(executable),
			html.EscapeString(home),
			html.EscapeString(filepath.Join(home, ".agent-manager", "logs", "client.log")),
			html.EscapeString(filepath.Join(home, ".agent-manager", "logs", "client-error.log")),
		)
		return path, body, nil
	case "linux":
		path := filepath.Join(home, ".config", "systemd", "user", "agent-manager-client.service")
		body := fmt.Sprintf(`[Unit]
Description=Agent Manager Client
After=network-online.target

[Service]
ExecStart=%s run --home %s
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
`, strconv.Quote(executable), strconv.Quote(home))
		return path, body, nil
	case "windows":
		path := filepath.Join(home, ".agent-manager", "agent-manager-client.cmd")
		body := fmt.Sprintf("@echo off\r\n\"%s\" run --home \"%s\"\r\n", strings.ReplaceAll(executable, "\"", ""), strings.ReplaceAll(home, "\"", ""))
		return path, body, nil
	default:
		return "", "", fmt.Errorf("service installation is not supported on %s", goos)
	}
}

func InstallService(home, executable string) (string, error) {
	path, body, err := ServiceDefinition(home, executable, runtime.GOOS)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Join(home, ".agent-manager", "logs"), 0o700); err != nil {
		return "", err
	}
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		return "", err
	}
	switch runtime.GOOS {
	case "darwin":
		domain := fmt.Sprintf("gui/%d", os.Getuid())
		if exec.Command("launchctl", "bootout", domain, path).Run() == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		}
		if output, err := exec.Command("launchctl", "bootstrap", domain, path).CombinedOutput(); err != nil {
			return "", fmt.Errorf("launchctl bootstrap failed: %s", output)
		}
	case "linux":
		if exec.Command("systemctl", "--user", "stop", "agent-manager-client.service").Run() == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		}
		if output, err := exec.Command("systemctl", "--user", "daemon-reload").CombinedOutput(); err != nil {
			return "", fmt.Errorf("systemctl daemon-reload failed: %s", output)
		}
		if output, err := exec.Command("systemctl", "--user", "enable", "--now", "agent-manager-client.service").CombinedOutput(); err != nil {
			return "", fmt.Errorf("systemctl enable failed: %s", output)
		}
	case "windows":
		if exec.Command("schtasks", "/End", "/TN", "AgentManagerClient").Run() == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		}
		if output, err := exec.Command("schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", "AgentManagerClient", "/TR", path).CombinedOutput(); err != nil {
			return "", fmt.Errorf("schtasks create failed: %s", output)
		}
		_ = exec.Command("schtasks", "/Run", "/TN", "AgentManagerClient").Run()
	}
	return path, nil
}

func UninstallService(home string) error {
	path, _, err := ServiceDefinition(home, "", runtime.GOOS)
	if err != nil {
		return err
	}
	switch runtime.GOOS {
	case "darwin":
		domain := fmt.Sprintf("gui/%d", os.Getuid())
		output, stopErr := exec.Command("launchctl", "bootout", domain, path).CombinedOutput()
		if stopErr != nil {
			output, stopErr = exec.Command("launchctl", "bootout", domain+"/com.agent-manager.client").CombinedOutput()
		}
		if stopErr == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		} else if ServiceStatus(home).Running {
			return fmt.Errorf("launchctl bootout failed: %s", strings.TrimSpace(string(output)))
		}
	case "linux":
		output, stopErr := exec.Command("systemctl", "--user", "disable", "--now", "agent-manager-client.service").CombinedOutput()
		if stopErr == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		} else if ServiceStatus(home).Running {
			return fmt.Errorf("systemctl disable failed: %s", strings.TrimSpace(string(output)))
		}
		_ = exec.Command("systemctl", "--user", "daemon-reload").Run()
	case "windows":
		output, stopErr := exec.Command("schtasks", "/End", "/TN", "AgentManagerClient").CombinedOutput()
		if stopErr == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		} else if ServiceStatus(home).Running {
			return fmt.Errorf("schtasks stop failed: %s", strings.TrimSpace(string(output)))
		}
		_ = exec.Command("schtasks", "/Delete", "/F", "/TN", "AgentManagerClient").Run()
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

func ServiceStatus(home string) ServiceState {
	path, _, err := ServiceDefinition(home, "", runtime.GOOS)
	if err != nil {
		return ServiceState{Detail: err.Error()}
	}
	state := ServiceState{}
	if _, err := os.Stat(path); err != nil {
		return state
	}
	state.Installed = true
	var output []byte
	switch runtime.GOOS {
	case "darwin":
		output, err = exec.Command("launchctl", "print", fmt.Sprintf("gui/%d/com.agent-manager.client", os.Getuid())).CombinedOutput()
	case "linux":
		output, err = exec.Command("systemctl", "--user", "is-active", "agent-manager-client.service").CombinedOutput()
	case "windows":
		output, err = exec.Command("schtasks", "/Query", "/TN", "AgentManagerClient").CombinedOutput()
	}
	state.Running = err == nil
	if err != nil {
		state.Detail = strings.TrimSpace(string(output))
	}
	return state
}
