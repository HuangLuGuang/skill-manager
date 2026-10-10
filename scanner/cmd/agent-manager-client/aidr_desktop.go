package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

type desktopHost struct {
	Binary string `json:"binary"`
	Home   string `json:"home"`
}
type desktopPreferences struct {
	Enrollment          *desktopHookEnrollment `json:"hook_enrollment,omitempty"`
	HookMode            string                 `json:"hook_mode,omitempty"`
	Enabled             bool                   `json:"enabled"`
	Hosts               map[string]desktopHost `json:"hosts"`
	PublicKey           string                 `json:"public_key,omitempty"`
	ManagedTask         int64                  `json:"managed_task,omitempty"`
	ManagedServer       string                 `json:"managed_server,omitempty"`
	ManagedDevice       string                 `json:"managed_device,omitempty"`
	RuntimePolicy       *desktopRuntimePolicy  `json:"runtime_policy,omitempty"`
	AccessMode          string                 `json:"access_mode,omitempty"`
	AuthorizationTask   int64                  `json:"authorization_task,omitempty"`
	AuthorizationAgent  string                 `json:"authorization_agent,omitempty"`
	AuthorizationAction string                 `json:"authorization_action,omitempty"`
}
type desktopHookEnrollment struct {
	Server string   `json:"server"`
	Device string   `json:"device"`
	Hosts  []string `json:"hosts"`
}
type desktopRuntimePolicy struct {
	Target     managedclient.RuntimeGovernancePolicy `json:"target"`
	Version    string                                `json:"version"`
	ReceivedAt string                                `json:"received_at"`
	AppliedAt  string                                `json:"applied_at,omitempty"`
	CheckedAt  string                                `json:"checked_at"`
	Code       string                                `json:"code"`
}
type desktopPaths struct {
	Root       string `json:"root"`
	State      string `json:"state"`
	Socket     string `json:"socket"`
	Binary     string `json:"binary"`
	Connection string `json:"connection"`
	Status     string `json:"status"`
	Device     string `json:"device"`
}

func readDesktopJSON(path string, target any) error {
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return errors.New("aidr_desktop_config_unreadable")
	}
	f, err := os.Open(path)
	if err != nil {
		return errors.New("aidr_desktop_config_unreadable")
	}
	defer f.Close()
	body, err := io.ReadAll(io.LimitReader(f, 65537))
	if err != nil || len(body) > 65536 || json.Unmarshal(body, target) != nil {
		return errors.New("aidr_desktop_config_invalid")
	}
	return nil
}
func writeDesktopJSON(path string, value any) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".aidr-write-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, err = f.Write(data); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}
func loadDesktopPreferences(home string) (desktopPreferences, error) {
	p := desktopPreferences{Hosts: map[string]desktopHost{}, HookMode: "audit"}
	path := filepath.Join(home, ".agent-manager", "aidr", "preferences.json")
	if _, e := os.Lstat(path); os.IsNotExist(e) {
		return p, nil
	}
	p.HookMode = ""
	e := readDesktopJSON(path, &p)
	// Migrate the pre-mode preference once, preserving its historical behavior.
	if e == nil && p.HookMode == "" {
		p.HookMode = "audit"
		if p.PublicKey != "" {
			p.HookMode = "intercept"
		}
	}
	if e == nil && p.HookMode != "audit" && p.HookMode != "intercept" {
		e = errors.New("aidr_hook_mode_invalid")
	}
	if p.Hosts == nil {
		p.Hosts = map[string]desktopHost{}
	}
	return p, e
}
func desktopBinding(home string) (managedclient.Config, desktopPaths, error) {
	var p desktopPaths
	if !filepath.IsAbs(home) {
		return managedclient.Config{}, p, errors.New("aidr_desktop_home_invalid")
	}
	var private managedclient.Config
	if _, e := os.Lstat(filepath.Join(home, ".agent-manager", "config.json")); os.IsNotExist(e) {
		return private, p, errors.New("aidr_desktop_not_configured")
	}
	if e := readDesktopJSON(filepath.Join(home, ".agent-manager", "config.json"), &private); e != nil {
		return private, p, e
	}
	cfg, e := managedclient.LoadConfig(home)
	if e != nil {
		return cfg, p, errors.New("aidr_desktop_config_unreadable")
	}
	if cfg.Server == "" || cfg.Token == "" {
		return cfg, p, errors.New("aidr_desktop_not_configured")
	}
	hostname, _ := os.Hostname()
	p.Device = managedclient.DeviceID(hostname, home)
	p.Root = filepath.Join(home, ".agent-manager", "aidr")
	if info, e := os.Lstat(p.Root); e == nil {
		real, e := filepath.EvalSymlinks(p.Root)
		if e != nil || real != p.Root || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
			return cfg, p, errors.New("aidr_desktop_config_invalid")
		}
	} else if !os.IsNotExist(e) {
		return cfg, p, errors.New("aidr_desktop_config_unreadable")
	}
	sum := sha256.Sum256([]byte(cfg.Server + "\x00" + p.Device))
	p.State = filepath.Join(p.Root, "queues", hex.EncodeToString(sum[:16]))
	p.Socket = filepath.Join(p.Root, "hook.sock")
	p.Connection = filepath.Join(p.Root, "bridge.json")
	p.Status = filepath.Join(p.State, "receiver-status.json")
	p.Binary = filepath.Join(p.Root, "runtime", "agent-manager-client")
	if runtime.GOOS == "windows" {
		p.Binary += ".exe"
	}
	if len(p.Socket) > 100 {
		return cfg, p, errors.New("aidr_desktop_socket_path_long")
	}
	return cfg, p, nil
}
func desktopFindHost(agent, home string) desktopHost {
	result := desktopHost{Home: filepath.Join(home, "."+agent)}
	candidates := []string{}
	if agent == "claude" {
		candidates = append(candidates, filepath.Join(home, ".local", "bin", "claude"))
	}
	if agent == "codex" && runtime.GOOS == "darwin" {
		candidates = append(candidates, "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
	}
	if p, e := exec.LookPath(agent); e == nil {
		candidates = append(candidates, p)
	}
	for _, p := range candidates {
		if s, e := os.Stat(p); e == nil && s.Mode().IsRegular() {
			result.Binary = p
			break
		}
	}
	return result
}

func aidrDesktop(args []string, out io.Writer) error {
	return aidrDesktopContext(context.Background(), args, out)
}

// A platform target can delegate ordinary plugin installation to this user.
// Receiver state and collection scope remain controlled by that target.
func localPluginInstallationAllowed(p desktopPreferences, action string) bool {
	if action != "connect" && action != "upgrade" && action != "disconnect" {
		return false
	}
	return p.RuntimePolicy != nil && p.RuntimePolicy.Target.Valid() &&
		(p.RuntimePolicy.Target.Installation == "manual" || (p.RuntimePolicy.Target.AllowUserEnrollment != nil && *p.RuntimePolicy.Target.AllowUserEnrollment)) && p.RuntimePolicy.Target.AccessMode == "ordinary" && p.AccessMode != "managed"
}
func aidrDesktopContext(parent context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-desktop", flag.ContinueOnError)
	home := fs.String("home", envOr("AGENT_MANAGER_CLIENT_HOME", userHome()), "client home")
	action := fs.String("action", "status", "status, inspect, connect, enable or disable")
	agent := fs.String("agent", "", "Hook product ID from the capability catalog")
	source := fs.String("source-dir", "", "bundled plugin resources")
	hostBinary := fs.String("host-bin", "", "explicit native executable")
	hostHome := fs.String("host-config-dir", "", "explicit user host configuration")
	localOnly := fs.Bool("local-only", false, "inspect local plugin configuration without starting the host")
	managedTask := fs.Int64("managed-task-id", 0, "claimed platform task identity")
	resultCode := fs.String("result-code", "", "bounded authorization outcome")
	policyVersion := fs.String("policy-version", "", "authorization target revision")
	if e := fs.Parse(args); e != nil {
		return e
	}
	if fs.NArg() != 0 {
		return errors.New("aidr_desktop_config_invalid")
	}
	if *localOnly && *action != "inspect" {
		return errors.New("aidr_desktop_config_invalid")
	}
	if runtime.GOOS != "darwin" && runtime.GOOS != "linux" {
		return errors.New("aidr_desktop_platform_unsupported")
	}
	var release func()
	if *action != "diagnose" && *action != "status" && *action != "channels-status" && *action != "system-check" && *action != "inspect" {
		var err error
		parent, release, err = managedclient.AIDRMutationLock(parent, *home)
		if err != nil {
			return errors.New("aidr_desktop_action_busy")
		}
		defer release()
	}
	prefs, e := loadDesktopPreferences(*home)
	if e != nil {
		return e
	}
	cfg, paths, e := desktopBinding(*home)
	if e != nil {
		return e
	}
	if *action == "enroll" {
		return enrollDesktopHook(parent, args, *home, *agent, prefs, cfg, paths, out)
	}
	if *action != "diagnose" && *action != "status" && *action != "channels-status" && *action != "system-check" && *action != "inspect" && *action != "prepare" && *action != "authorize-plan" && *action != "apply-managed" && *action != "managed-removed" && *action != "authorization-result" && *action != "retry-logs" {
		if prefs.ManagedTask > 0 && *managedTask == 0 {
			if prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device {
				return errors.New("aidr_desktop_managed_binding_changed")
			}
			if !localPluginInstallationAllowed(prefs, *action) {
				return errors.New("aidr_desktop_platform_managed")
			}
		}
		if *managedTask > 0 {
			if prefs.ManagedTask > *managedTask && prefs.ManagedServer == cfg.Server && prefs.ManagedDevice == paths.Device {
				return errors.New("aidr_desktop_task_superseded")
			}
			prefs.ManagedTask, prefs.ManagedServer, prefs.ManagedDevice = *managedTask, cfg.Server, paths.Device
		}
	}
	if (*action == "status" || *action == "channels-status" || *action == "system-check") && prefs.ManagedTask > 0 && (prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device) {
		return errors.New("aidr_desktop_managed_binding_changed")
	}
	switch *action {
	case "diagnose":
		binary, _ := os.Executable()
		return json.NewEncoder(out).Encode(hooks.DiagnoseReceiver(parent, paths.Socket, paths.State, cfg.Server, paths.Device, binary))
	case "system-check":
		return json.NewEncoder(out).Encode(systemPreflight(parent))
	case "channels-status":
		return json.NewEncoder(out).Encode(map[string]any{"channels": aidrRuntimeSnapshot(*home)["channels"], "runtime_policy": prefs.RuntimePolicy, "user_hook_hosts": desktopEnrollmentHosts(prefs, cfg, paths)})
	case "retry-logs":
		if e := requestLogRetry(paths); e != nil {
			return e
		}
		return json.NewEncoder(out).Encode(map[string]any{"code": "aidr_log_retry_requested"})
	case "status":
		if prefs.ManagedTask > 0 && (prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device) {
			return errors.New("aidr_desktop_managed_binding_changed")
		}
		pending, err := hooks.PendingUploads(parent, paths.State)
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]any{"enabled": prefs.Enabled, "receiver_required": prefs.Enabled || pending > 0, "pending_upload_records": pending, "paths": paths, "server": cfg.Server, "managed_task": strconv.FormatInt(prefs.ManagedTask, 10), "runtime_policy": prefs.RuntimePolicy})
	case "enable", "disable":
		prefs.Enabled = *action == "enable"
		if e = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); e != nil {
			return e
		}
		if e = writeDesktopConnection(paths, prefs); e != nil {
			return e
		}
		return json.NewEncoder(out).Encode(map[string]any{"enabled": prefs.Enabled})
	case "prepare":
		if e = installDesktopBinary(paths.Binary); e != nil {
			return e
		}
		if e = writeDesktopConnection(paths, prefs); e != nil {
			return e
		}
		return json.NewEncoder(out).Encode(map[string]any{"paths": paths})
	case "authorize-plan", "apply-managed":
		return desktopManagedAction(parent, *home, *agent, *action, prefs, cfg, paths, out)
	case "authorization-result":
		return recordManagedAuthorization(prefs, cfg, paths, *policyVersion, *resultCode, out)
	case "managed-removed":
		if prefs.RuntimePolicy == nil || prefs.ManagedDevice != paths.Device || prefs.ManagedServer != cfg.Server {
			return errors.New("aidr_desktop_task_superseded")
		}
		configured, err := hooks.SystemManagedConfigured(*agent)
		if err != nil {
			return err
		}
		if configured {
			return errors.New("aidr_managed_remove_unverified")
		}
		return recordManagedRemoval(prefs, paths, *agent, out)
	case "inspect", "connect", "upgrade", "disconnect":
	default:
		return errors.New("aidr_desktop_action_invalid")
	}
	if hooks.SettingsAdapter(*agent) {
		if prefs.AccessMode == "managed" || (prefs.RuntimePolicy != nil && prefs.RuntimePolicy.Target.AccessMode == "managed") {
			return errors.New("aidr_plugin_host_unsupported")
		}
		var status hooks.PluginStatus
		if *action == "inspect" {
			status, e = hooks.InspectSettingsHooks(*agent, *home, paths.Binary, paths.Connection)
		} else {
			if *action != "disconnect" {
				if e = installDesktopBinary(paths.Binary); e != nil {
					return e
				}
			}
			status, e = hooks.MergeSettingsHooks(*agent, *home, paths.Binary, paths.Connection, *action == "disconnect")
			if e == nil && *action == "disconnect" {
				clearDesktopHookEnrollment(&prefs, cfg, paths, *agent)
			}
			if e == nil && *action != "disconnect" && prefs.ManagedTask == 0 {
				prefs.Enabled = true
			}
			if e == nil {
				e = writeDesktopConnection(paths, prefs)
			}
			if e == nil {
				e = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs)
			}
		}
		if e != nil {
			return e
		}
		result := map[string]any{"plugin": status, "hook_trust": "unknown", "access_mode": "ordinary", "enabled": prefs.Enabled, "code": status.SourceCode}
		if e = writeDesktopJSON(filepath.Join(paths.Root, "observed-"+*agent+".json"), result); e != nil {
			return e
		}
		return json.NewEncoder(out).Encode(result)
	}
	if *action == "disconnect" && (prefs.AccessMode == "managed" || (prefs.RuntimePolicy != nil && prefs.RuntimePolicy.Target.AccessMode == "managed")) {
		return errors.New("aidr_desktop_platform_managed")
	}
	if (*action == "connect" || *action == "upgrade") && prefs.RuntimePolicy != nil && prefs.RuntimePolicy.Target.AccessMode == "managed" {
		if *managedTask > 0 {
			prefs.AuthorizationTask = *managedTask
			prefs.AuthorizationAgent, prefs.AuthorizationAction = *agent, *action
			if e = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); e != nil {
				return e
			}
		}
		return errors.New("aidr_desktop_managed_authorization_required")
	}
	if *agent != "claude" && *agent != "codex" {
		return errors.New("aidr_plugin_host_unsupported")
	}
	host, ok := prefs.Hosts[*agent]
	if !ok {
		host = desktopFindHost(*agent, *home)
	}
	if *hostBinary != "" {
		host.Binary = *hostBinary
	}
	if *hostHome != "" {
		host.Home = *hostHome
	}
	if !filepath.IsAbs(host.Binary) {
		return errors.New("aidr_desktop_host_missing")
	}
	ctx, cancel := context.WithTimeout(parent, time.Minute)
	defer cancel()
	var status hooks.PluginStatus
	if *localOnly {
		status, e = hooks.InspectLocalPlugin(ctx, *agent, host.Home, paths.Socket)
	} else {
		status, e = hooks.InspectPlugin(ctx, *agent, host.Binary, host.Home, paths.Socket)
	}
	if e != nil {
		return e
	}
	if *action == "inspect" {
		trust := "unknown"
		mode := "ordinary"
		if prefs.RuntimePolicy != nil {
			mode = prefs.RuntimePolicy.Target.AccessMode
		}
		if mode == "managed" {
			configured, e := hooks.SystemManagedConfigured(*agent)
			if e != nil {
				return e
			}
			status.Installed = &configured
			enabled := configured && prefs.AccessMode == "managed" && prefs.Enabled
			status.Enabled = &enabled
			status.SourceCode = "aidr_managed_configuration_missing"
			if configured {
				status.SourceCode = "aidr_managed_configuration_present"
				status.PluginVersion, e = hooks.SystemManagedVersion(*agent)
				if e != nil {
					status.SourceCode = stableAIDRCode(e)
				}
			}
			if *agent == "codex" && configured && !*localOnly {
				trust = hooks.NativeCodexManagedTrust(ctx, host.Binary, host.Home)
			}
		}
		if mode == "ordinary" && *agent == "codex" && status.Installed != nil && *status.Installed && !*localOnly {
			trust = hooks.NativeCodexTrust(ctx, host.Binary, host.Home)
		}
		result := map[string]any{"host": host, "plugin": status, "hook_trust": trust, "access_mode": mode}
		if configured, e := hooks.SystemManagedConfigured(*agent); e == nil {
			result["managed_installed"] = configured
		}
		if e = writeDesktopJSON(filepath.Join(paths.Root, "observed-"+*agent+".json"), result); e != nil {
			return e
		}
		return json.NewEncoder(out).Encode(result)
	}
	if *action == "disconnect" {
		status, e = hooks.UninstallPlugin(ctx, *agent, host.Binary, host.Home, paths.Connection)
		if e != nil {
			return e
		}
		clearDesktopHookEnrollment(&prefs, cfg, paths, *agent)
		if e = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); e != nil {
			return e
		}
		result := map[string]any{"host": host, "plugin": status, "hook_trust": "unknown", "access_mode": "ordinary", "enabled": prefs.Enabled, "code": "aidr_plugin_not_installed"}
		if e = writeDesktopJSON(filepath.Join(paths.Root, "observed-"+*agent+".json"), result); e != nil {
			return e
		}
		return json.NewEncoder(out).Encode(result)
	}
	if status.VersionStatus != "interface_compatible" {
		return errors.New("aidr_plugin_interface_unavailable")
	}
	if status.Installed == nil {
		return errors.New("aidr_plugin_source_unreadable")
	}
	if *status.Installed && !hooks.PluginBridgeMatches(status, paths.Connection) {
		return errors.New("aidr_desktop_manual_migration_required")
	}
	if *source == "" {
		if e = os.MkdirAll(paths.Root, 0700); e != nil {
			return e
		}
		*source, e = hooks.BundledSource(paths.Root)
		if e != nil {
			return e
		}
	}
	if !filepath.IsAbs(*source) {
		return errors.New("aidr_plugin_package_invalid")
	}
	if e = installDesktopBinary(paths.Binary); e != nil {
		return e
	}
	if e = writeDesktopConnection(paths, prefs); e != nil {
		return e
	}
	// Package content and paths select an immutable release directory.
	var content []byte
	for _, a := range []string{"claude", "codex"} {
		for _, rel := range []string{"." + a + "-plugin/plugin.json", "hooks/hooks.json", "scripts/bridge.sh"} {
			b, e := os.ReadFile(filepath.Join(*source, "aidr-"+a, rel))
			if e != nil {
				return errors.New("aidr_plugin_package_unreadable")
			}
			content = append(content, b...)
		}
	}
	content = append(content, []byte(paths.Binary+"\x00"+paths.Connection)...)
	sum := sha256.Sum256(content)
	market := filepath.Join(paths.Root, "market-"+hex.EncodeToString(sum[:16]))
	if _, e = os.Lstat(market); os.IsNotExist(e) {
		if _, e = hooks.BuildConnectedMarketplace(*source, market, paths.Binary, paths.Connection); e != nil {
			return e
		}
	} else if e != nil {
		return e
	}
	if e = hooks.VerifyMarketplace(market); e != nil {
		return e
	}
	if *action == "upgrade" || (*status.Installed && status.PluginVersion != hooks.BundledPluginVersion) {
		status, e = hooks.UpdatePlugin(ctx, *agent, host.Binary, host.Home, market)
	} else {
		status, e = hooks.InstallPlugin(ctx, *agent, host.Binary, host.Home, market)
	}
	if e != nil {
		return e
	}
	if !hooks.PluginBridgeMatches(status, paths.Connection) {
		return errors.New("aidr_desktop_bridge_not_applied")
	}
	prefs.Hosts[*agent] = host
	if prefs.ManagedTask == 0 && *action == "connect" {
		prefs.Enabled = true
	}
	if e = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); e != nil {
		return e
	}
	result := map[string]any{"host": host, "plugin": status, "hook_trust": "unknown", "enabled": prefs.Enabled, "code": "aidr_desktop_connected"}
	if e = writeDesktopJSON(filepath.Join(paths.Root, "observed-"+*agent+".json"), result); e != nil {
		return e
	}
	return json.NewEncoder(out).Encode(result)
}

// Called only after checking that the system-owned hooks are absent. Update
// their observation immediately rather than reusing the pre-removal report.
func recordManagedRemoval(prefs desktopPreferences, paths desktopPaths, agent string, out io.Writer) error {
	observedPath := filepath.Join(paths.Root, "observed-"+agent+".json")
	var observed struct {
		Host             desktopHost        `json:"host"`
		Plugin           hooks.PluginStatus `json:"plugin"`
		Trust            string             `json:"hook_trust"`
		AccessMode       string             `json:"access_mode"`
		ManagedInstalled bool               `json:"managed_installed"`
	}
	observedPresent := false
	if _, err := os.Lstat(observedPath); err == nil {
		if err = readDesktopJSON(observedPath, &observed); err != nil {
			return err
		}
		observedPresent = true
	} else if !os.IsNotExist(err) {
		return errors.New("aidr_desktop_config_unreadable")
	}
	if prefs.AccessMode == "managed" {
		prefs.Enabled = false
		prefs.RuntimePolicy.Code = "aidr_desktop_managed_authorization_required"
		prefs.RuntimePolicy.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	if prefs.RuntimePolicy.Target.AccessMode == "managed" {
		absent := false
		observed.Plugin.Agent = agent
		observed.Plugin.Installed, observed.Plugin.Enabled = &absent, &absent
		observed.Plugin.SourceCode = "aidr_managed_configuration_missing"
		observed.Plugin.ReportedAt = time.Now().UTC().Format(time.RFC3339Nano)
		observed.Plugin.ConfigurationDigest, observed.Plugin.FilesDigest, observed.Plugin.ScopeDigest = "", "", ""
		observed.Plugin.Drift = nil
		if observed.Plugin.VersionStatus == "" {
			observed.Plugin.VersionStatus = "unverified"
		}
		observed.Trust, observed.AccessMode = "unknown", "managed"
	}
	if observedPresent || prefs.RuntimePolicy.Target.AccessMode == "managed" {
		if err := writeDesktopJSON(observedPath, observed); err != nil {
			return err
		}
	}
	if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		return err
	}
	if err := writeDesktopConnection(paths, prefs); err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(map[string]string{"code": "aidr_managed_configuration_removed"})
}

func writeDesktopConnection(paths desktopPaths, prefs desktopPreferences) error {
	mode := prefs.AccessMode
	if mode == "" {
		mode = "ordinary"
	}
	if mode != "ordinary" && mode != "managed" {
		return errors.New("aidr_desktop_config_invalid")
	}
	controlMode := "audit"
	if prefs.HookMode == "intercept" {
		controlMode = "plugin_pre_tool"
	}
	value := map[string]any{"socket": paths.Socket, "active": prefs.Enabled, "access_mode": mode, "control_mode": controlMode, "gap_file": filepath.Join(paths.State, "bridge-gap.json")}
	if prefs.RuntimePolicy != nil {
		value["agents"] = prefs.RuntimePolicy.Target.Hosts
	}
	return writeDesktopJSON(paths.Connection, value)
}
func installDesktopBinary(target string) error {
	source, e := os.Executable()
	if e != nil {
		return errors.New("aidr_desktop_binary_missing")
	}
	real, e := filepath.EvalSymlinks(source)
	if e != nil {
		return errors.New("aidr_desktop_binary_missing")
	}
	if real == target {
		return nil
	}
	if e = os.MkdirAll(filepath.Dir(target), 0700); e != nil {
		return e
	}
	in, e := os.Open(real)
	if e != nil {
		return e
	}
	defer in.Close()
	f, e := os.CreateTemp(filepath.Dir(target), ".client-")
	if e != nil {
		return e
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, e = io.Copy(f, in); e != nil {
		return e
	}
	if e = f.Chmod(0700); e != nil {
		return e
	}
	if e = f.Sync(); e != nil {
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	return os.Rename(f.Name(), target)
}
