package managedclient

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"html"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

type ServiceState struct {
	Installed bool   `json:"installed"`
	Running   bool   `json:"running"`
	Detail    string `json:"detail,omitempty"`
}

type ServiceReconcileResult struct {
	Restarted bool         `json:"restarted"`
	Reason    string       `json:"reason"`
	State     ServiceState `json:"state"`
}

type serviceRegistration struct {
	Executable  string `json:"executable"`
	SHA256      string `json:"sha256"`
	RestartedAt string `json:"restarted_at,omitempty"`
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
	executable, err := filepath.Abs(executable)
	if err != nil {
		return "", err
	}
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
		stopped := exec.Command("launchctl", "bootout", domain, path).Run() == nil
		if !stopped {
			stopped = exec.Command("launchctl", "bootout", domain+"/com.agent-manager.client").Run() == nil
		}
		if stopped {
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
		if output, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", windowsServiceSettingsScript).CombinedOutput(); err != nil {
			return "", fmt.Errorf("scheduled task settings failed: %s", output)
		}
		if output, err := exec.Command("schtasks", "/Run", "/TN", "AgentManagerClient").CombinedOutput(); err != nil {
			return "", fmt.Errorf("schtasks run failed: %s", output)
		}
	}
	if err := writeServiceRegistration(home, executable); err != nil {
		return "", err
	}
	return path, nil
}

const windowsServiceSettingsScript = `$ErrorActionPreference = 'Stop'; $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; Set-ScheduledTask -TaskName 'AgentManagerClient' -Settings $settings | Out-Null`

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
	if err := os.Remove(serviceRegistrationPath(home)); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// StopServiceForUpdate stops the running sidecar without removing its service
// definition. The updated desktop app can then reconcile and restart it.
func StopServiceForUpdate(home string) (ServiceState, error) {
	state := ServiceStatus(home)
	if !state.Installed || !state.Running {
		return state, nil
	}
	path, _, err := ServiceDefinition(home, "", runtime.GOOS)
	if err != nil {
		return state, err
	}
	switch runtime.GOOS {
	case "darwin":
		domain := fmt.Sprintf("gui/%d", os.Getuid())
		output, stopErr := exec.Command("launchctl", "bootout", domain, path).CombinedOutput()
		if stopErr != nil {
			output, stopErr = exec.Command("launchctl", "bootout", domain+"/com.agent-manager.client").CombinedOutput()
		}
		if stopErr != nil {
			return state, fmt.Errorf("launchctl bootout failed: %s", strings.TrimSpace(string(output)))
		}
	case "linux":
		if output, stopErr := exec.Command("systemctl", "--user", "stop", "agent-manager-client.service").CombinedOutput(); stopErr != nil {
			return state, fmt.Errorf("systemctl stop failed: %s", strings.TrimSpace(string(output)))
		}
	case "windows":
		if output, stopErr := exec.Command("schtasks", "/End", "/TN", "AgentManagerClient").CombinedOutput(); stopErr != nil {
			return state, fmt.Errorf("schtasks stop failed: %s", strings.TrimSpace(string(output)))
		}
	}
	_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
	stopped := ServiceStatus(home)
	if stopped.Running {
		return stopped, fmt.Errorf("后台服务未能停止")
	}
	return stopped, nil
}

func ReconcileService(home, executable string, force bool) (ServiceReconcileResult, error) {
	config, err := LoadConfig(home)
	if err != nil {
		return ServiceReconcileResult{}, err
	}
	if strings.TrimSpace(config.Server) == "" || strings.TrimSpace(config.Token) == "" {
		return ServiceReconcileResult{Reason: "not_configured", State: ServiceStatus(home)}, nil
	}
	release, err := acquireServiceReconcileLock(home)
	if err != nil {
		return ServiceReconcileResult{}, err
	}
	defer release()
	state := ServiceStatus(home)
	result := ServiceReconcileResult{State: state}
	executable, err = filepath.Abs(executable)
	if err != nil {
		return result, err
	}
	matches, err := serviceRegistrationMatches(home, executable)
	if err != nil {
		return result, err
	}
	recent, err := serviceRecentlyRestarted(home, 10*time.Second)
	if err != nil {
		return result, err
	}
	restart, reason := serviceReconcileDecision(state, matches, force, recent)
	result.Reason = reason
	if !restart {
		return result, nil
	}
	if _, err := InstallService(home, executable); err != nil {
		return result, err
	}
	result.Restarted = true
	result.State = waitForServiceRunning(home, 5*time.Second)
	if !result.State.Running {
		return result, fmt.Errorf("后台服务重启后未进入运行状态: %s", result.State.Detail)
	}
	// A new or recovered binary gets one full validation pass. Routine desktop
	// launches already run an immediate light patrol when the daemon starts, so
	// they should not force an expensive full scan every time.
	if reason != "forced" {
		if err := RequestFullScan(home); err != nil {
			return result, fmt.Errorf("后台服务已重启，但无法请求完整巡检: %w", err)
		}
	}
	return result, nil
}

func serviceReconcileDecision(state ServiceState, matches, force, recentlyRestarted bool) (bool, string) {
	if !state.Installed {
		return true, "not_installed"
	}
	if !state.Running {
		return true, "not_running"
	}
	if !matches {
		return true, "binary_changed"
	}
	if force && !recentlyRestarted {
		return true, "forced"
	}
	if force {
		return false, "recently_restarted"
	}
	return false, "already_current"
}

func waitForServiceRunning(home string, timeout time.Duration) ServiceState {
	deadline := time.Now().Add(timeout)
	state := ServiceStatus(home)
	for !state.Running && time.Now().Before(deadline) {
		time.Sleep(100 * time.Millisecond)
		state = ServiceStatus(home)
	}
	return state
}

func acquireServiceReconcileLock(home string) (func(), error) {
	root := filepath.Join(home, ".agent-manager")
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(root, "service-reconcile.lock")
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err == nil {
			_, _ = fmt.Fprintf(file, "%d\n", os.Getpid())
			_ = file.Close()
			return func() { _ = os.Remove(path) }, nil
		}
		if !os.IsExist(err) {
			return nil, err
		}
		if info, statErr := os.Stat(path); statErr == nil && time.Since(info.ModTime()) > 30*time.Second {
			_ = os.Remove(path)
			continue
		}
		time.Sleep(100 * time.Millisecond)
	}
	return nil, fmt.Errorf("后台服务正在由另一个客户端实例重启")
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
		output, err = exec.Command(
			"powershell", "-NoProfile", "-NonInteractive", "-Command",
			"(Get-ScheduledTask -TaskName 'AgentManagerClient').State",
		).CombinedOutput()
	}
	state.Running = serviceCommandIsRunning(runtime.GOOS, output, err)
	if state.Running && runtime.GOOS == "darwin" && !darwinServiceDefinitionMatches(output, path) {
		state.Running = false
		state.Detail = "已加载的后台服务不属于当前客户端安装，正在等待修复"
		return state
	}
	if err != nil || !state.Running {
		state.Detail = strings.TrimSpace(string(output))
	}
	return state
}

func darwinServiceDefinitionMatches(output []byte, expectedPath string) bool {
	expectedPath = canonicalServiceDefinitionPath(expectedPath)
	for _, line := range strings.Split(string(output), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "path = ") {
			continue
		}
		loadedPath := canonicalServiceDefinitionPath(strings.TrimSpace(strings.TrimPrefix(line, "path = ")))
		return loadedPath == expectedPath
	}
	return false
}

func canonicalServiceDefinitionPath(path string) string {
	path = filepath.Clean(path)
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return filepath.Clean(resolved)
	}
	return path
}

func serviceCommandIsRunning(goos string, output []byte, commandErr error) bool {
	if commandErr != nil {
		return false
	}
	detail := strings.TrimSpace(string(output))
	switch goos {
	case "darwin":
		return strings.Contains(detail, "state = running")
	case "linux":
		return detail == "active"
	case "windows":
		return strings.EqualFold(detail, "running")
	default:
		return false
	}
}

func serviceRegistrationPath(home string) string {
	return filepath.Join(home, ".agent-manager", "service.json")
}

func executableSHA256(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func writeServiceRegistration(home, executable string) error {
	digest, err := executableSHA256(executable)
	if err != nil {
		return err
	}
	registration := serviceRegistration{
		Executable:  executable,
		SHA256:      digest,
		RestartedAt: time.Now().UTC().Format(time.RFC3339Nano),
	}
	body, err := json.MarshalIndent(registration, "", "  ")
	if err != nil {
		return err
	}
	path := serviceRegistrationPath(home)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, append(body, '\n'), 0o600)
}

func serviceRecentlyRestarted(home string, within time.Duration) (bool, error) {
	body, err := os.ReadFile(serviceRegistrationPath(home))
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var registration serviceRegistration
	if json.Unmarshal(body, &registration) != nil || registration.RestartedAt == "" {
		return false, nil
	}
	restartedAt, err := time.Parse(time.RFC3339Nano, registration.RestartedAt)
	if err != nil {
		return false, nil
	}
	return time.Since(restartedAt) >= 0 && time.Since(restartedAt) <= within, nil
}

func serviceRegistrationMatches(home, executable string) (bool, error) {
	body, err := os.ReadFile(serviceRegistrationPath(home))
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var registration serviceRegistration
	if err := json.Unmarshal(body, &registration); err != nil {
		return false, nil
	}
	digest, err := executableSHA256(executable)
	if err != nil {
		return false, err
	}
	return registration.Executable == executable && registration.SHA256 == digest, nil
}
