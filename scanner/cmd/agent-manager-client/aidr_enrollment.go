package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/catalog"
	"skill-manager/scanner/internal/managedclient"
)

func desktopEnrollmentHosts(p desktopPreferences, cfg managedclient.Config, paths desktopPaths) []string {
	if p.Enrollment == nil || p.Enrollment.Server != cfg.Server || p.Enrollment.Device != paths.Device {
		return []string{}
	}
	return append([]string{}, p.Enrollment.Hosts...)
}

func clearDesktopHookEnrollment(p *desktopPreferences, cfg managedclient.Config, paths desktopPaths, agent string) {
	if p.Enrollment == nil {
		return
	}
	kept := []string{}
	for _, host := range desktopEnrollmentHosts(*p, cfg, paths) {
		if host != agent {
			kept = append(kept, host)
		}
	}
	p.Enrollment = &desktopHookEnrollment{Server: cfg.Server, Device: paths.Device, Hosts: kept}
}

func enrollDesktopHook(ctx context.Context, args []string, home, agent string, prefs desktopPreferences, cfg managedclient.Config, paths desktopPaths, out io.Writer) error {
	if !catalog.Hook(agent) {
		return errors.New("aidr_plugin_host_unsupported")
	}
	if prefs.ManagedServer != cfg.Server || prefs.ManagedDevice != paths.Device {
		return errors.New("aidr_desktop_managed_binding_changed")
	}
	p := prefs.RuntimePolicy
	if p == nil || p.Target.AllowUserEnrollment == nil {
		return errors.New("aidr_enrollment_policy_required")
	}
	if !p.Target.Valid() || !p.Target.CollectHooks() || p.Target.AccessMode != "ordinary" || prefs.AccessMode == "managed" || (!*p.Target.AllowUserEnrollment && !slices.Contains(p.Target.Hosts, agent)) {
		return errors.New("aidr_enrollment_policy_blocked")
	}
	product, _ := catalog.Get(agent)
	if product.EnrollmentLogSource != "" && (!p.Target.CollectLogs() || (!*p.Target.AllowUserEnrollment && !slices.Contains(p.Target.LogSources, product.EnrollmentLogSource))) {
		return errors.New("aidr_enrollment_logs_blocked")
	}
	// Use the same installer and mutation lock as platform tasks. No local
	// scope change is made until the server delivers the effective policy.
	installArgs := append([]string{}, args...)
	for i := range installArgs {
		if strings.HasPrefix(installArgs[i], "--action=") {
			installArgs[i] = "--action=connect"
		}
		if installArgs[i] == "--action" && i+1 < len(installArgs) {
			installArgs[i+1] = "connect"
		}
	}
	var result bytes.Buffer
	if err := aidrDesktopContext(ctx, installArgs, &result); err != nil {
		return err
	}
	latest, err := loadDesktopPreferences(home)
	if err != nil {
		return err
	}
	hosts := desktopEnrollmentHosts(latest, cfg, paths)
	if !slices.Contains(hosts, agent) {
		hosts = append(hosts, agent)
	}
	latest.Enrollment = &desktopHookEnrollment{Server: cfg.Server, Device: paths.Device, Hosts: hosts}
	if err = writeDesktopJSON(filepath.Join(paths.Root, "preferences.json"), latest); err != nil {
		return err
	}
	var response map[string]any
	if err = json.Unmarshal(result.Bytes(), &response); err != nil {
		return err
	}
	response["code"] = "aidr_enrollment_pending"
	response["enrollment_sync_code"] = submitDesktopHookEnrollment(ctx, home, cfg, paths)
	return json.NewEncoder(out).Encode(response)
}

// Persist enrollment first, then notify the platform through its authenticated
// heartbeat contract. Only the normal platform task may apply collection scope.
func submitDesktopHookEnrollment(ctx context.Context, home string, cfg managedclient.Config, paths desktopPaths) string {
	request, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	_, err := managedclient.NewAPI(cfg.Server, cfg.Token, 3*time.Second).Heartbeat(request,
		managedclient.Inventory{ClientID: paths.Device, ClientVersion: managedclient.Version}, home)
	if err != nil {
		return "aidr_enrollment_sync_retrying"
	}
	return "aidr_enrollment_submitted"
}
