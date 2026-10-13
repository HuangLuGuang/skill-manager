package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	products "skill-manager/scanner/internal/aidr/catalog"
	"skill-manager/scanner/internal/aidr/hooks"
	"skill-manager/scanner/internal/aidr/upload"
)

func aidrPluginDoctor(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-plugin-doctor", flag.ContinueOnError)
	agent := fs.String("agent", "", "product Hook adapter ID")
	binary := fs.String("host-bin", "", "absolute native host executable")
	home := fs.String("host-config-dir", "", "optional explicit host configuration directory")
	socket := fs.String("socket", os.Getenv("AIDR_HOOK_SOCKET"), "optional receiver socket")
	previous := fs.String("previous-report", "", "optional absolute path to a previous doctor report; read-only drift comparison")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("aidr_plugin_config_invalid")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()
	status, err := hooks.InspectPlugin(ctx, *agent, *binary, *home, *socket)
	if err != nil {
		return err
	}
	if *previous != "" {
		if !filepath.IsAbs(*previous) {
			return errors.New("aidr_plugin_baseline_invalid")
		}
		f, e := os.Open(*previous)
		if e != nil {
			return errors.New("aidr_plugin_baseline_unreadable")
		}
		info, e := f.Stat()
		if e != nil || !info.Mode().IsRegular() {
			f.Close()
			return errors.New("aidr_plugin_baseline_invalid")
		}
		raw, e := io.ReadAll(io.LimitReader(f, 65537))
		f.Close()
		var before hooks.PluginStatus
		if e != nil || len(raw) > 65536 || json.Unmarshal(raw, &before) != nil || before.Agent != *agent {
			return errors.New("aidr_plugin_baseline_invalid")
		}
		drift := hooks.ComparePluginStatus(before, status)
		status.Drift = &drift
	}
	return json.NewEncoder(out).Encode(status)
}

func aidrPluginInstall(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-plugin-install", flag.ContinueOnError)
	agent := fs.String("agent", "", "product Hook adapter ID")
	binary := fs.String("host-bin", "", "absolute native host executable")
	home := fs.String("host-config-dir", "", "optional explicit host configuration directory")
	market := fs.String("marketplace-path", "", "absolute vetted local marketplace directory")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("aidr_plugin_config_invalid")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	status, err := hooks.InstallPlugin(ctx, *agent, *binary, *home, *market)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(status)
}

func aidrPluginPackage(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-plugin-package", flag.ContinueOnError)
	source := fs.String("source-dir", "", "absolute product plugin source directory")
	destination := fs.String("destination", "", "new absolute marketplace directory")
	binary := fs.String("runtime-bin", "", "stable trusted client binary for a connected package")
	connection := fs.String("connection-file", "", "non-secret stable bridge connection file")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("aidr_plugin_package_invalid")
	}
	hashes, err := hooks.BuildConnectedMarketplace(*source, *destination, *binary, *connection)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(map[string]any{"code": "aidr_plugin_package_created", "files": hashes})
}

func aidrHook(args []string, in io.Reader, out io.Writer) (resultErr error) {
	return aidrHookWithDiagnostics(args, in, out, os.Stderr)
}

func aidrHookWithDiagnostics(args []string, in io.Reader, out, diagnostics io.Writer) (resultErr error) {
	fs := flag.NewFlagSet("aidr-hook", flag.ContinueOnError)
	socket := fs.String("socket", os.Getenv("AIDR_HOOK_SOCKET"), "private receiver Unix socket")
	connection := fs.String("connection-file", "", "private desktop bridge connection, without credentials")
	managedConnection := fs.Bool("managed-connection", false, "use the calling OS user's private desktop connection")
	agent := fs.String("agent", "", "product Hook adapter ID")
	hook := fs.String("event", "", "native lifecycle event name")
	health := fs.Bool("health", false, "read receiver status without submitting an event")
	controlMode, gapFile, failureCode := "unknown", "", "aidr_hook_precheck_failed"
	defer func() {
		var denied *hooks.HostDenied
		if resultErr == nil || *health || errors.As(resultErr, &denied) {
			return
		}
		if failureCode == "aidr_hook_precheck_failed" {
			failureCode = resultErr.Error()
		}
		failureCode = hooks.BridgeFailureCode(failureCode)
		if controlMode == "audit" {
			// A missing audit record is a coverage gap, never an authorization.
			fmt.Fprintln(diagnostics, "aidr_hook_audit_gap", failureCode)
			if err := hooks.WriteBridgeGap(gapFile, *agent, *hook, failureCode); err != nil {
				fmt.Fprintln(diagnostics, "aidr_hook_gap_report_failed")
			}
			resultErr = hooks.WriteHostDecision(out, *agent, *hook, "allow", "")
		} else if hooks.IsPreTool(*agent, *hook) {
			resultErr = hooks.WriteHostDecision(out, *agent, *hook, "deny", failureCode)
		}
	}()
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *managedConnection {
		current, err := user.Current()
		if err != nil || os.Geteuid() == 0 || current.HomeDir == "" {
			return errors.New("aidr_managed_user_unknown")
		}
		*connection = filepath.Join(current.HomeDir, ".agent-manager/aidr/bridge.json")
		if _, err = os.Lstat(*connection); os.IsNotExist(err) {
			return hooks.WriteInactiveHost(out, *agent, *hook)
		}
	}
	if *connection != "" {
		var cfg struct {
			Socket      string    `json:"socket"`
			Active      *bool     `json:"active"`
			AccessMode  string    `json:"access_mode"`
			Agents      *[]string `json:"agents"`
			ControlMode string    `json:"control_mode"`
			GapFile     string    `json:"gap_file"`
		}
		if !filepath.IsAbs(*connection) || hooks.ValidateBridgePrivateFile(*connection) != nil || readDesktopJSON(*connection, &cfg) != nil {
			return errors.New("aidr_desktop_connection_invalid")
		}
		mode := cfg.AccessMode
		if mode == "" {
			mode = "ordinary"
		}
		if mode != "ordinary" && mode != "managed" {
			return errors.New("aidr_desktop_connection_invalid")
		}
		if (mode == "managed") != *managedConnection || (cfg.Active != nil && !*cfg.Active) {
			return hooks.WriteInactiveHost(out, *agent, *hook)
		}
		if cfg.Agents != nil {
			selected := false
			for _, host := range *cfg.Agents {
				if host == *agent {
					selected = true
				}
			}
			if !selected {
				return hooks.WriteInactiveHost(out, *agent, *hook)
			}
		}
		*socket = cfg.Socket
		if cfg.ControlMode != "" && cfg.ControlMode != "audit" && cfg.ControlMode != "plugin_pre_tool" {
			return errors.New("aidr_desktop_connection_invalid")
		}
		if cfg.ControlMode != "" {
			controlMode, gapFile = cfg.ControlMode, cfg.GapFile
		} else {
			// Existing desktop connections predate the mode field. Resolve only
			// against the same private preferences and device-bound socket.
			home := filepath.Dir(filepath.Dir(filepath.Dir(*connection)))
			_, paths, bindErr := desktopBinding(home)
			prefsPath := filepath.Join(paths.Root, "preferences.json")
			prefs, prefsErr := loadDesktopPreferences(home)
			if bindErr == nil && paths.Connection == *connection && paths.Socket == cfg.Socket && hooks.ValidateBridgePrivateFile(prefsPath) == nil && prefsErr == nil {
				controlMode, gapFile = "audit", filepath.Join(paths.State, "bridge-gap.json")
				if prefs.HookMode == "intercept" {
					controlMode = "plugin_pre_tool"
				}
			}
		}
	}
	if fs.NArg() != 0 || !filepath.IsAbs(*socket) {
		return errors.New("aidr_hook_config_invalid")
	}
	req := hooks.IPCRequest{Version: 1, Method: "GetHealth"}
	if !*health {
		if !products.Hook(*agent) {
			return errors.New("aidr_hook_config_invalid")
		}
		raw, err := io.ReadAll(io.LimitReader(in, hooks.MaxRecordBytes+1))
		if err != nil {
			return errors.New("aidr_hook_input_failed")
		}
		if len(raw) > hooks.MaxRecordBytes {
			return errors.New("aidr_hook_record_oversized")
		}
		if !json.Valid(raw) {
			return errors.New("aidr_hook_record_invalid")
		}
		id, err := hooks.NewEventID()
		if err != nil {
			return errors.New("aidr_hook_identity_failed")
		}
		req = hooks.IPCRequest{Version: 1, Method: "SubmitEvent", EventID: id, Agent: *agent, Hook: *hook, Raw: raw}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	var response hooks.IPCResponse
	var err error
	for attempt := 0; attempt < 2; attempt++ {
		response, err = hooks.Exchange(ctx, *socket, req)
		if err == nil {
			break
		}
	}
	if err != nil {
		failureCode = err.Error()
		return err
	}
	// The connected receiver reports the execution mode applied to this event.
	if response.State != nil && (response.State.ControlMode == "plugin_pre_tool" || response.State.ControlMode == "audit") {
		controlMode = response.State.ControlMode
	}
	if response.Code != "aidr_hook_recorded" && response.Code != "aidr_hook_audit_paused" && response.Code != "aidr_hook_healthy" {
		failureCode = response.Code
		return errors.New(response.Code)
	}
	if *health {
		return json.NewEncoder(out).Encode(response)
	}
	if hooks.IsPreTool(*agent, *hook) && controlMode == "plugin_pre_tool" && response.Decision == nil {
		failureCode = "aidr_hook_control_decision_missing"
		return errors.New(failureCode)
	}
	if response.Decision != nil {
		controlMode = "plugin_pre_tool"
		d := *response.Decision
		if d.Decision == "ask" {
			wait, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			wait, end := context.WithTimeout(wait, 40*time.Second)
			defer end()
			ticker := time.NewTicker(250 * time.Millisecond)
			defer ticker.Stop()
			for d.Decision == "ask" {
				select {
				case <-wait.Done():
					cleanup, finish := context.WithTimeout(context.Background(), time.Second)
					hooks.Exchange(cleanup, *socket, hooks.IPCRequest{Version: 1, Method: "CancelApproval", EventID: req.EventID})
					finish()
					return hooks.WriteHostDecision(out, *agent, *hook, "deny", "aidr_hook_approval_timeout")
				case <-ticker.C:
					answer, e := hooks.Exchange(wait, *socket, hooks.IPCRequest{Version: 1, Method: "PollApproval", EventID: req.EventID})
					if e != nil || answer.Code != "aidr_hook_decision" || answer.Decision == nil {
						return hooks.WriteHostDecision(out, *agent, *hook, "deny", "aidr_hook_approval_unavailable")
					}
					d = *answer.Decision
				}
			}
		}
		if d.Decision != "allow" {
			return hooks.WriteHostDecision(out, *agent, *hook, "deny", d.Code)
		}
	}
	// Return the host's non-blocking audit response (Cursor requires allow).
	return hooks.WriteHostDecision(out, *agent, *hook, "allow", "")
}

func aidrHookServe(args []string, out io.Writer) (resultErr error) {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return aidrHookServeContext(ctx, args, out)
}

// The managed daemon calls the receiver directly, sharing its process lifetime.
func aidrHookServeContext(parent context.Context, args []string, out io.Writer) (resultErr error) {
	fs := flag.NewFlagSet("aidr-hook-serve", flag.ContinueOnError)
	state := fs.String("state-dir", "", "dedicated private hook state directory")
	socket := fs.String("socket", os.Getenv("AIDR_HOOK_SOCKET"), "private receiver Unix socket")
	server := fs.String("server", "", "platform URL; HTTPS except loopback")
	device := fs.String("client-id", "", "credential-bound device")
	tokenEnv := fs.String("token-env", "AGENT_MANAGER_AIDR_TOKEN", "environment variable with device credential")
	duration := fs.Duration("duration", 0, "optional bounded run duration")
	capacity := fs.Int("capacity", 10000, "maximum pending hook events (1..100000)")
	publicKey := fs.String("public-key", "", "optional pinned P-256 X9.63 public key file; enables tool control")
	codexHost := fs.String("codex-host-bin", "", "native Codex executable for read-only plugin inspection; defaults to PATH")
	claudeHost := fs.String("claude-host-bin", "", "native Claude executable for read-only plugin inspection; defaults to PATH")
	codexHome := fs.String("codex-config-dir", "", "optional isolated Codex configuration for plugin inspection")
	claudeHome := fs.String("claude-config-dir", "", "optional isolated Claude configuration for plugin inspection")
	managedHome := fs.String("managed-home", "", "desktop home; reuses private device credentials")
	parentStdin := fs.Bool("parent-stdin", false, "managed receiver lifetime follows its private parent pipe")
	statusFile := fs.String("status-file", "", "private receiver telemetry file")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *parentStdin && *managedHome == "" {
		return errors.New("aidr_hook_config_invalid")
	}
	var managedToken string
	if *managedHome != "" {
		cfg, paths, err := desktopBinding(*managedHome)
		if err != nil {
			return err
		}
		prefs, err := loadDesktopPreferences(*managedHome)
		if err != nil {
			return err
		}
		if !prefs.Enabled {
			pending, e := hooks.PendingUploads(context.Background(), paths.State)
			if e != nil {
				return e
			}
			if pending == 0 {
				return errors.New("aidr_desktop_disabled")
			}
		}
		*state, *socket, *server, *device, *statusFile = paths.State, paths.Socket, cfg.Server, paths.Device, paths.Status
		*codexHost, *claudeHost = prefs.Hosts["codex"].Binary, prefs.Hosts["claude"].Binary
		*codexHome, *claudeHome = prefs.Hosts["codex"].Home, prefs.Hosts["claude"].Home
		managedToken = cfg.Token
		if prefs.PublicKey != "" {
			*publicKey = prefs.PublicKey
		}
	}
	if fs.NArg() != 0 || !filepath.IsAbs(*state) || !filepath.IsAbs(*socket) || *duration < 0 {
		return errors.New("aidr_hook_config_invalid")
	}
	if *statusFile != "" && !filepath.IsAbs(*statusFile) {
		return errors.New("aidr_desktop_status_invalid")
	}
	targets := []pluginInspectionTarget{}
	for _, target := range []pluginInspectionTarget{{"codex", *codexHost, *codexHome}, {"claude", *claudeHost, *claudeHome}} {
		if *managedHome != "" && target.binary == "" {
			continue
		}
		if target.home != "" && !filepath.IsAbs(target.home) {
			return errors.New("aidr_plugin_config_invalid")
		}
		if target.binary == "" {
			target.binary, _ = exec.LookPath(target.agent)
		}
		if target.binary == "" {
			continue
		}
		if !filepath.IsAbs(target.binary) {
			return errors.New("aidr_plugin_config_invalid")
		}
		targets = append(targets, target)
	}
	*server = strings.TrimRight(*server, "/")
	token := os.Getenv(*tokenEnv)
	if *managedHome != "" {
		token = managedToken
	}
	c, err := upload.New(upload.Options{Server: *server, ClientID: *device, Token: token})
	if err != nil {
		return err
	}
	defer c.Close()
	s, err := hooks.OpenStore(*state, *server, *device, *capacity)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, s.Close()) }()
	if *publicKey != "" {
		if !filepath.IsAbs(*publicKey) {
			return errors.New("aidr_hook_control_key_invalid")
		}
		f, e := os.Open(*publicKey)
		if e != nil {
			return errors.New("aidr_hook_control_key_invalid")
		}
		key, e := io.ReadAll(io.LimitReader(f, 66))
		f.Close()
		if e != nil || len(key) != 65 {
			return errors.New("aidr_hook_control_key_invalid")
		}
		if err = s.ConfigureControl(context.Background(), key); err != nil {
			return err
		}
	}
	if *managedHome != "" {
		if err = applyManagedHookIntake(context.Background(), *managedHome, *server, *device, managedToken, s); err != nil {
			return err
		}
	}
	if parent.Value(managedHookContextKey{}) == true {
		if err = recoverManagedHookSocket(*socket); err != nil {
			return err
		}
	}
	r, err := hooks.Listen(*socket, s)
	if err != nil {
		return err
	}
	defer r.Close()
	if parent.Value(managedHookContextKey{}) == true {
		identity, e := r.SocketIdentity()
		if e != nil {
			return e
		}
		if e = writeDesktopJSON(*socket+".owner.json", identity); e != nil {
			return e
		}
	}
	if *managedHome != "" {
		identity, e := r.SocketIdentity()
		if e != nil {
			return e
		}
		// A private parent pipe conveys ownership before network/health work.
		// It contains no credential, configuration or event content.
		if e = json.NewEncoder(out).Encode(identity); e != nil {
			return errors.New("aidr_desktop_parent_unavailable")
		}
	}
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	if *parentStdin {
		go func() { _, _ = io.Copy(io.Discard, io.LimitReader(os.Stdin, 1)); cancel() }()
	}
	if *duration > 0 {
		var end context.CancelFunc
		ctx, end = context.WithTimeout(ctx, *duration)
		defer end()
	}
	var mu sync.Mutex
	policyCode, uploadCode, controlCode := "aidr_policy_cached", "", "aidr_hook_audit_only"
	lastReport := ""
	runtimeCode := "aidr_hook_runtime_not_reported"
	pluginCode := "aidr_plugin_not_checked"
	done := make(chan error, 6)
	go func() { done <- r.Serve(ctx) }()
	go func() {
		done <- c.RunHooks(ctx, s, func(p, u, control string) {
			mu.Lock()
			policyCode, uploadCode, controlCode = p, u, control
			mu.Unlock()
		}, func(code string) {
			mu.Lock()
			runtimeCode = code
			if code == "aidr_hook_runtime_received" {
				lastReport = time.Now().UTC().Format(time.RFC3339Nano)
			}
			mu.Unlock()
		})
	}()
	workers := 2
	if *managedHome != "" {
		workers++
		go func() {
			ticker := time.NewTicker(2 * time.Second)
			defer ticker.Stop()
			for {
				if e := applyManagedHookIntake(ctx, *managedHome, *server, *device, managedToken, s); e != nil && ctx.Err() == nil {
					done <- e
					return
				}
				select {
				case <-ctx.Done():
					done <- nil
					return
				case <-ticker.C:
				}
			}
		}()
	}
	if *statusFile != "" {
		workers++
		go func() {
			ticker := time.NewTicker(5 * time.Second)
			defer ticker.Stop()
			for {
				st, e := s.Status(ctx)
				if e == nil {
					mu.Lock()
					telemetry := map[string]any{"state": st, "policy_code": policyCode, "upload_code": uploadCode, "control_code": controlCode, "runtime_code": runtimeCode, "last_report": lastReport, "updated_at": time.Now().UTC().Format(time.RFC3339Nano)}
					mu.Unlock()
					e = writeDesktopJSON(*statusFile, telemetry)
				}
				if e != nil && ctx.Err() == nil {
					done <- errors.New("aidr_desktop_status_failed")
					return
				}
				select {
				case <-ctx.Done():
					done <- nil
					return
				case <-ticker.C:
				}
			}
		}()
	}
	if len(targets) > 0 {
		workers++
		go func() {
			done <- observePlugins(ctx, c, s, targets, func(code string) { mu.Lock(); pluginCode = code; mu.Unlock() })
		}()
	}
	first := <-done
	cancel()
	for i := 1; i < workers; i++ {
		first = errors.Join(first, <-done)
	}
	if first != nil {
		return first
	}
	status, err := s.Status(context.Background())
	if err != nil {
		return err
	}
	mu.Lock()
	defer mu.Unlock()
	return json.NewEncoder(out).Encode(struct {
		State       hooks.StoreStatus `json:"state"`
		PolicyCode  string            `json:"policy_code"`
		UploadCode  string            `json:"upload_code"`
		ControlCode string            `json:"control_code"`
		PluginCode  string            `json:"plugin_code"`
	}{status, policyCode, uploadCode, controlCode, pluginCode})
}

type pluginInspectionTarget struct{ agent, binary, home string }

func observePlugins(ctx context.Context, c *upload.Client, s *hooks.Store, targets []pluginInspectionTarget, observe func(string)) error {
	for {
		for _, target := range targets {
			if ctx.Err() != nil {
				return nil
			}
			status, err := hooks.InspectLocalPlugin(ctx, target.agent, target.home, "")
			if ctx.Err() != nil {
				return nil
			}
			code := "aidr_plugin_inspection_failed"
			if err == nil {
				code, err = c.SendPluginStatus(ctx, s, status)
			}
			if ctx.Err() != nil {
				return nil
			}
			if err != nil {
				code = "aidr_plugin_report_failed"
			}
			observe(code)
		}
		timer := time.NewTimer(60 * time.Second)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-timer.C:
		}
	}
}

// Policy intake changes are committed before any new event can be persisted.
// The upload worker remains independent until the old queue is acknowledged.
func applyManagedHookIntake(ctx context.Context, home, server, device, token string, s *hooks.Store) error {
	cfg, paths, err := desktopBinding(home)
	if err != nil {
		return err
	}
	if cfg.Server != server || paths.Device != device || cfg.Token != token {
		return errors.New("aidr_desktop_managed_binding_changed")
	}
	prefs, err := loadDesktopPreferences(home)
	if err != nil {
		return err
	}
	if prefs.ManagedTask > 0 && (prefs.ManagedServer != server || prefs.ManagedDevice != device) {
		return errors.New("aidr_desktop_managed_binding_changed")
	}
	version := ""
	if prefs.RuntimePolicy != nil {
		version = prefs.RuntimePolicy.Version
		if !validRuntimePolicyVersion(version) {
			return errors.New("aidr_hook_runtime_target_invalid")
		}
	}
	if prefs.HookMode == "intercept" {
		key, e := os.ReadFile(prefs.PublicKey)
		if e != nil {
			return errors.New("aidr_hook_control_key_invalid")
		}
		if !bytes.Equal(key, s.ControlKey()) {
			if e = s.ConfigureControl(ctx, key); e != nil {
				return e
			}
		}
	}
	if err = s.SetControlMode(prefs.HookMode); err != nil {
		return err
	}
	return s.SetRuntimeCollection(ctx, prefs.Enabled, version)
}
