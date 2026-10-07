package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os/user"
	"path/filepath"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/managedclient"
)

func aidrManagedInstall(args []string, out io.Writer) error {
	flags := flag.NewFlagSet("aidr-managed-install", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	agent := flags.String("agent", "", "codex or claude")
	action := flags.String("action", "install", "fixed install or remove operation")
	if flags.Parse(args) != nil || flags.NArg() != 0 || (*agent != "codex" && *agent != "claude") || (*action != "install" && *action != "remove") {
		return errors.New("aidr_managed_action_invalid")
	}
	if err := hooks.ApplySystemManaged(*agent, *action); err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(map[string]string{"code": "aidr_managed_configuration_present", "agent": *agent, "action": *action})
}

func desktopManagedAction(ctx context.Context, home, agent, action string, prefs desktopPreferences, cfg managedclient.Config, paths desktopPaths, out io.Writer) error {
	if agent != "codex" && agent != "claude" {
		return errors.New("aidr_plugin_host_unsupported")
	}
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	policy, err := managedclient.NewAPI(cfg.Server, cfg.Token, 10*time.Second).Policy(ctx, paths.Device)
	if err != nil {
		return errors.New("aidr_desktop_policy_unavailable")
	}
	target := policy.Classification.RuntimeGovernance
	if !policy.Classification.RuntimeGovernanceConfigured || target == nil || !target.Valid() || !target.Enabled || target.AccessMode != "managed" || prefs.RuntimePolicy == nil || prefs.RuntimePolicy.Version != policy.Classification.RuntimeGovernanceVersion || prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device {
		return errors.New("aidr_desktop_task_superseded")
	}
	selected := false
	for _, host := range target.Hosts {
		if host == agent {
			selected = true
		}
	}
	if !selected {
		return errors.New("aidr_desktop_task_superseded")
	}
	configured, installedErr := hooks.SystemManagedConfigured(agent)
	if installedErr != nil {
		return installedErr
	}
	installedVersion := ""
	if configured {
		installedVersion, err = hooks.SystemManagedVersion(agent)
		if err != nil {
			return err
		}
	}
	requested := "connect"
	manual := !configured && target.Installation == "manual"
	if configured && installedVersion != hooks.BundledPluginVersion {
		requested = "upgrade"
		manual = target.Updates == "manual"
	}
	if manual && (prefs.AuthorizationTask == 0 || prefs.AuthorizationAgent != agent || prefs.AuthorizationAction != requested) {
		return errors.New("aidr_managed_manual_request_required")
	}
	current, e := user.Current()
	actual, eHome := filepath.EvalSymlinks(home)
	if e != nil || eHome != nil || current == nil || actual != current.HomeDir {
		return errors.New("aidr_managed_user_home_mismatch")
	}
	host, ok := prefs.Hosts[agent]
	if !ok {
		host = desktopFindHost(agent, home)
	}
	if host.Binary == "" {
		return errors.New("aidr_desktop_host_missing")
	}
	layout, err := hooks.SystemManagedLayout(agent)
	if err != nil {
		return err
	}
	if action == "authorize-plan" {
		if err = hooks.ManagedHostReady(ctx, agent, host.Binary, host.Home, false); err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]any{"agent": agent, "policy_version": prefs.RuntimePolicy.Version, "system_config": layout.Config, "system_binary": layout.Binary, "code": "aidr_managed_authorization_required"})
	}
	for _, host := range target.Hosts {
		configured, e := hooks.SystemManagedConfigured(host)
		if e != nil {
			return e
		}
		if !configured {
			return errors.New("aidr_managed_authorization_required")
		}
		native, ok := prefs.Hosts[host]
		if !ok {
			native = desktopFindHost(host, home)
		}
		if err = hooks.ManagedHostReady(ctx, host, native.Binary, native.Home, true); err != nil {
			return err
		}
		version, e := hooks.SystemManagedVersion(host)
		if e != nil {
			return e
		}
		if target.Updates == "automatic" && version != hooks.BundledPluginVersion {
			return errors.New("aidr_desktop_package_update_required")
		}
	}
	prefs.AccessMode = "managed"
	prefs.Enabled = target.Enabled
	prefs.RuntimePolicy.Code = "aidr_desktop_policy_applied"
	prefs.RuntimePolicy.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
	prefs.RuntimePolicy.AppliedAt = prefs.RuntimePolicy.CheckedAt
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		return err
	}
	if err = writeDesktopConnection(paths, prefs); err != nil {
		return err
	}
	// Observe the installed target using native read-only inspection; do not
	// manufacture trust from a privileged installer's successful exit.
	var result bytes.Buffer
	if err = aidrDesktopContext(ctx, []string{"--home", home, "--action", "inspect", "--agent", agent}, &result); err != nil {
		return err
	}
	_, err = io.Copy(out, &result)
	return err
}

func recordManagedAuthorization(prefs desktopPreferences, cfg managedclient.Config, paths desktopPaths, version, result string, out io.Writer) error {
	if result != "aidr_managed_authorization_cancelled" && result != "aidr_managed_authorization_failed" && result != "aidr_managed_authorization_interrupted" {
		return errors.New("aidr_managed_action_invalid")
	}
	if prefs.RuntimePolicy == nil || prefs.RuntimePolicy.Version != version || prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device {
		return errors.New("aidr_desktop_task_superseded")
	}
	prefs.RuntimePolicy.Code = result
	prefs.RuntimePolicy.CheckedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if err := writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), prefs); err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(map[string]string{"code": result})
}
