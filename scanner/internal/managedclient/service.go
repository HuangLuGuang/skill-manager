package managedclient

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"
)

const windowsServiceTaskName = "AgentManagerClient"

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

type windowsScheduledTask struct {
	Installed  bool   `json:"installed"`
	State      string `json:"state"`
	Execute    string `json:"execute"`
	Arguments  string `json:"arguments"`
	LastResult int64  `json:"last_result"`
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
	default:
		return "", "", fmt.Errorf("service installation is not supported on %s", goos)
	}
}

func InstallService(home, executable string) (string, error) {
	executable, err := filepath.Abs(executable)
	if err != nil {
		return "", err
	}
	if runtime.GOOS == "windows" {
		if err := os.MkdirAll(filepath.Join(home, ".agent-manager", "logs"), 0o700); err != nil {
			return "", err
		}
		if err := installWindowsService(home, executable); err != nil {
			return "", err
		}
		if err := writeServiceRegistration(home, executable); err != nil {
			return "", err
		}
		// Legacy releases launched the Unicode install path through a
		// UTF-8 batch file. cmd.exe decoded that file with the active OEM code
		// page, so Chinese product or user directories exited with code 1.
		_ = os.Remove(windowsLegacyServicePath(home))
		return windowsServiceTaskName, nil
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
	}
	if err := writeServiceRegistration(home, executable); err != nil {
		return "", err
	}
	return path, nil
}

func windowsLegacyServicePath(home string) string {
	return filepath.Join(home, ".agent-manager", "agent-manager-client.cmd")
}

func powershellLiteral(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}

func windowsServiceArguments(home string) string {
	return `run --home "` + strings.ReplaceAll(home, `"`, "") + `"`
}

func windowsServiceRegistrationScript(taskName, executable, home, username string, start bool) string {
	startCommand := ""
	if start {
		startCommand = fmt.Sprintf("Start-ScheduledTask -TaskName %s;", powershellLiteral(taskName))
	}
	return fmt.Sprintf(
		`[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; `+
			`Stop-ScheduledTask -TaskName %s -ErrorAction SilentlyContinue; `+
			`$action = New-ScheduledTaskAction -Execute %s -Argument %s; `+
			`$trigger = New-ScheduledTaskTrigger -AtLogOn -User %s; `+
			`$principal = New-ScheduledTaskPrincipal -UserId %s -LogonType Interactive -RunLevel Limited; `+
			`$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; `+
			`$task = Register-ScheduledTask -TaskName %s -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force; %s`,
		powershellLiteral(taskName),
		powershellLiteral(executable),
		powershellLiteral(windowsServiceArguments(home)),
		powershellLiteral(username),
		powershellLiteral(username),
		powershellLiteral(taskName),
		startCommand,
	)
}

func encodePowerShellCommand(script string) string {
	units := utf16.Encode([]rune(script))
	body := make([]byte, len(units)*2)
	for index, unit := range units {
		binary.LittleEndian.PutUint16(body[index*2:], unit)
	}
	return base64.StdEncoding.EncodeToString(body)
}

func runElevatedPowerShell(script string) ([]byte, error) {
	encoded := encodePowerShellCommand(script)
	launcher := fmt.Sprintf(
		`[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; `+
			`try { $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -ArgumentList @('-NoProfile','-NonInteractive','-EncodedCommand',%s) -Wait -PassThru; exit $process.ExitCode } `+
			`catch { [Console]::Error.WriteLine('windows_service_elevation_cancelled'); exit 1 }`,
		powershellLiteral(encoded),
	)
	return exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", launcher).CombinedOutput()
}

func runWindowsPowerShellWithElevation(script, failureCode string) error {
	if _, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", script).CombinedOutput(); err == nil {
		return nil
	}
	output, err := runElevatedPowerShell(script)
	if err == nil {
		return nil
	}
	detail := strings.TrimSpace(string(output))
	if strings.Contains(detail, "windows_service_elevation_cancelled") {
		return fmt.Errorf("windows_service_elevation_cancelled")
	}
	return errors.New(failureCode)
}

func installWindowsService(home, executable string) error {
	if strings.ContainsAny(home+executable, "\r\n") {
		return fmt.Errorf("windows_service_path_invalid")
	}
	current, err := user.Current()
	if err != nil || strings.TrimSpace(current.Username) == "" {
		return fmt.Errorf("windows_service_user_unavailable")
	}
	register := windowsServiceRegistrationScript(windowsServiceTaskName, executable, home, current.Username, false)
	if err := runWindowsPowerShellWithElevation(register, "windows_service_registration_failed"); err != nil {
		return err
	}
	_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
	start := fmt.Sprintf(
		`[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; Start-ScheduledTask -TaskName %s`,
		powershellLiteral(windowsServiceTaskName),
	)
	if err := runWindowsPowerShellWithElevation(start, "windows_service_start_failed"); err != nil {
		return err
	}
	return nil
}

func queryWindowsService() (windowsScheduledTask, error) {
	script := fmt.Sprintf(
		`[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; `+
			`$task = Get-ScheduledTask -TaskName %s -ErrorAction SilentlyContinue; `+
			`if ($null -eq $task) { [pscustomobject]@{installed=$false;state='';execute='';arguments='';last_result=0} | ConvertTo-Json -Compress; exit 0 }; `+
			`$action = @($task.Actions)[0]; $lastResult = 0; try { $lastResult = [int64](Get-ScheduledTaskInfo -TaskName %s).LastTaskResult } catch {}; `+
			`[pscustomobject]@{installed=$true;state=[string]$task.State;execute=[string]$action.Execute;arguments=[string]$action.Arguments;last_result=$lastResult} | ConvertTo-Json -Compress`,
		powershellLiteral(windowsServiceTaskName), powershellLiteral(windowsServiceTaskName),
	)
	output, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", script).CombinedOutput()
	if err != nil {
		return windowsScheduledTask{}, fmt.Errorf("windows_service_status_failed: %s", strings.TrimSpace(string(output)))
	}
	var task windowsScheduledTask
	text := strings.TrimPrefix(strings.TrimSpace(string(output)), "\ufeff")
	if err := json.Unmarshal([]byte(text), &task); err != nil {
		return windowsScheduledTask{}, fmt.Errorf("windows_service_status_invalid: %w", err)
	}
	return task, nil
}

func windowsServiceActionMatches(home, executable string) (bool, error) {
	task, err := queryWindowsService()
	if err != nil || !task.Installed {
		return false, err
	}
	return strings.EqualFold(filepath.Clean(task.Execute), filepath.Clean(executable)) &&
		task.Arguments == windowsServiceArguments(home), nil
}

func removeWindowsService() error {
	script := fmt.Sprintf(
		`[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; `+
			`Unregister-ScheduledTask -TaskName %s -Confirm:$false -ErrorAction SilentlyContinue`,
		powershellLiteral(windowsServiceTaskName),
	)
	return runWindowsPowerShellWithElevation(script, "windows_service_removal_failed")
}

func UninstallService(home string) error {
	path := windowsLegacyServicePath(home)
	if runtime.GOOS != "windows" {
		var err error
		path, _, err = ServiceDefinition(home, "", runtime.GOOS)
		if err != nil {
			return err
		}
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
		output, stopErr := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", fmt.Sprintf(
			`Stop-ScheduledTask -TaskName %s -ErrorAction Stop`, powershellLiteral(windowsServiceTaskName),
		)).CombinedOutput()
		if stopErr == nil {
			_ = os.Remove(filepath.Join(home, ".agent-manager", "client.lock"))
		} else if ServiceStatus(home).Running {
			return fmt.Errorf("windows_service_stop_failed: %s", strings.TrimSpace(string(output)))
		}
		if err := removeWindowsService(); err != nil {
			return err
		}
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
	switch runtime.GOOS {
	case "darwin":
		path, _, err := ServiceDefinition(home, "", runtime.GOOS)
		if err != nil {
			return state, err
		}
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
		if output, stopErr := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", fmt.Sprintf(
			`Stop-ScheduledTask -TaskName %s -ErrorAction Stop`, powershellLiteral(windowsServiceTaskName),
		)).CombinedOutput(); stopErr != nil {
			return state, fmt.Errorf("windows_service_stop_failed: %s", strings.TrimSpace(string(output)))
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
	if runtime.GOOS == "windows" {
		task, err := queryWindowsService()
		if err != nil {
			return ServiceState{Detail: err.Error()}
		}
		state := ServiceState{Installed: task.Installed, Running: task.Installed && strings.EqualFold(task.State, "Running")}
		if task.Installed && !state.Running {
			state.Detail = fmt.Sprintf("%s; last_result=%d", task.State, task.LastResult)
		}
		return state
	}
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
	matches := registration.Executable == executable && registration.SHA256 == digest
	if !matches || runtime.GOOS != "windows" {
		return matches, nil
	}
	return windowsServiceActionMatches(home, executable)
}
