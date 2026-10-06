//go:build darwin

package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"skill-manager/scanner/internal/aidr/enforcement"
	"skill-manager/scanner/internal/aidr/upload"
)

type nativeDiagnostics struct {
	mu   sync.Mutex
	data []byte
}

func (d *nativeDiagnostics) Write(p []byte) (int, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	n := len(p)
	if len(p) > 4096-len(d.data) {
		p = p[:4096-len(d.data)]
	}
	d.data = append(d.data, p...)
	return n, nil
}

func (d *nativeDiagnostics) code() string {
	d.mu.Lock()
	defer d.mu.Unlock()
	for _, line := range strings.Split(string(d.data), "\n") {
		code := strings.SplitN(line, ":", 2)[0]
		switch code {
		case "aidr_enforcement_es_unavailable", "aidr_enforcement_fda_required", "aidr_enforcement_entitlement_required", "aidr_enforcement_root_required", "aidr_enforcement_subscription_failed", "aidr_enforcement_state_invalid", "aidr_enforcement_key_invalid":
			return code
		}
	}
	return "aidr_enforcement_native_exit"
}

func rootFile(path string, directory bool) error {
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return errors.New("aidr_enforcement_path_invalid")
	}
	i, err := os.Lstat(path)
	if err != nil {
		return err
	}
	st, ok := i.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != 0 || i.Mode().Perm()&0022 != 0 || (directory && (!i.IsDir() || i.Mode().Perm()&0077 != 0)) || (!directory && !i.Mode().IsRegular()) {
		return errors.New("aidr_enforcement_root_ownership_required")
	}
	// A root-owned executable inside a user-replaceable directory is not a
	// trusted launch path. Root-owned sticky temporary parents are safe for
	// root-owned entries; every intervening directory must also be root-owned.
	for parent := filepath.Dir(path); ; parent = filepath.Dir(parent) {
		info, err := os.Lstat(parent)
		if err != nil {
			return err
		}
		owner, ok := info.Sys().(*syscall.Stat_t)
		if !ok || !info.IsDir() || owner.Uid != 0 || (info.Mode().Perm()&0022 != 0 && info.Mode()&os.ModeSticky == 0) {
			return errors.New("aidr_enforcement_root_ownership_required")
		}
		if parent == "/" {
			break
		}
	}
	return nil
}

func aidrEnforce(args []string, out io.Writer) error {
	return aidrEnforceRun(context.Background(), args, out, nil)
}

type systemObservation struct {
	Mode          string
	PolicyVersion string
	Record        *enforcement.Record
	Pending       *int
	Uploaded      bool
	Code          string
}

func aidrEnforceRun(parent context.Context, args []string, out io.Writer, observe func(systemObservation)) error {
	notify := func(v systemObservation) {
		if observe != nil {
			observe(v)
		}
	}
	fs := flag.NewFlagSet("aidr-enforce", flag.ContinueOnError)
	state := fs.String("state-dir", "", "absolute root-owned private runtime state directory")
	native := fs.String("native", "", "root-owned signed macOS enforcer executable")
	keyFile := fs.String("public-key", "", "root-owned pinned P-256 public key in X9.63 binary format")
	server := fs.String("server", "", "platform URL")
	device := fs.String("client-id", "", "registered device identity")
	tokenEnv := fs.String("token-env", "AGENT_MANAGER_AIDR_TOKEN", "device credential environment variable")
	collectionOnly := fs.Bool("collection-only", false, "collect signed Agent process evidence without file control or process response")
	duration := fs.Duration("duration", 10*time.Minute, "bounded foreground enforcement duration, at most 24h")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 || os.Geteuid() != 0 || *duration < time.Second || *duration > 24*time.Hour {
		return errors.New("aidr_enforcement_config_invalid")
	}
	for _, p := range []string{*state, *native, *keyFile} {
		if !filepath.IsAbs(p) {
			return errors.New("aidr_enforcement_path_invalid")
		}
	}
	if err := rootFile(*state, true); err != nil {
		return err
	}
	if err := rootFile(*native, false); err != nil {
		return err
	}
	if err := rootFile(*keyFile, false); err != nil {
		return err
	}
	key, err := os.ReadFile(*keyFile)
	if err != nil || len(key) != 65 {
		return errors.New("aidr_enforcement_key_invalid")
	}
	c, err := upload.New(upload.Options{Server: *server, ClientID: *device, Token: os.Getenv(*tokenEnv)})
	if err != nil {
		return err
	}
	defer c.Close()
	if observe != nil {
		data, result := c.RuntimeGet(parent, "bootstrap")
		if result.Code != "" {
			return errors.New(result.Code)
		}
		var boot struct {
			Mode string `json:"mode"`
		}
		if json.Unmarshal(data, &boot) != nil || (boot.Mode != "audit" && boot.Mode != "intercept") {
			return errors.New("aidr_system_mode_invalid")
		}
		*collectionOnly = boot.Mode == "audit"
		notify(systemObservation{Mode: boot.Mode})
	}
	if *collectionOnly {
		if err := nativeCollectionCapabilitiesContext(parent, *native); err != nil {
			return err
		}
	}
	s, err := enforcement.OpenStore(*state, 100000)
	if err != nil {
		return err
	}
	defer s.Close()
	ctx, stop := signal.NotifyContext(parent, os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, *duration)
	defer cancel()
	if err = c.Bind(ctx, s.Guard); err != nil {
		return err
	}
	if observe != nil {
		data, result := c.RuntimeGet(ctx, "snapshot")
		if result.Code != "" {
			return errors.New(result.Code)
		}
		raw, e := upload.DecodeRuntimeSnapshot(data)
		if e != nil {
			return e
		}
		next, e := enforcement.Verify(raw, key, *device, time.Now())
		if e != nil {
			return e
		}
		cacheName := "policy.json"
		if *collectionOnly {
			cacheName = "collection-policy.json"
		}
		cache := filepath.Join(*state, cacheName)
		if previous, e := os.ReadFile(cache); e == nil {
			payload, e := enforcement.VerifyPayload(previous, key)
			if e != nil {
				return e
			}
			var current enforcement.Policy
			if e = json.Unmarshal(payload, &current); e != nil {
				return e
			}
			if e = enforcement.CanReplace(current, next, previous, raw); e != nil {
				return e
			}
		} else if !os.IsNotExist(e) {
			return e
		}
		if e = systemAtomic(cache, raw, 0600); e != nil {
			return e
		}
	}
	nativeArgs := []string{*keyFile, *device, *state, strconv.Itoa(int((*duration + time.Second - 1) / time.Second))}
	if *collectionOnly {
		nativeArgs = append(nativeArgs, "--collection-only")
	}
	cmd := exec.Command(*native, nativeArgs...)
	cmd.Env = []string{"PATH=/usr/bin:/bin", "LANG=C"}
	diagnostics := &nativeDiagnostics{}
	cmd.Stderr = diagnostics
	input, err := cmd.StdinPipe()
	if err != nil {
		return err
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	if err = cmd.Start(); err != nil {
		return err
	}
	var killOnce sync.Once
	kill := func() { killOnce.Do(func() { input.Close(); _ = cmd.Process.Signal(syscall.SIGTERM) }) }
	defer kill()
	go func() { <-ctx.Done(); kill() }()
	readDone := make(chan error, 1)
	go func() {
		scanner := bufio.NewScanner(output)
		scanner.Buffer(make([]byte, 16384), 16385)
		var health enforcement.Record
		var lastSequence uint64
		for scanner.Scan() {
			record, e := enforcement.ParseRecord(scanner.Bytes())
			if e == nil {
				e = s.Append(context.Background(), record)
				lastSequence, _ = strconv.ParseUint(record.Sequence, 10, 64)
				if record.Kind == "health" {
					health = record
				}
				if e == nil {
					notify(systemObservation{Record: &record})
				}
			}
			if e != nil {
				readDone <- e
				cancel()
				return
			}
		}
		readErr := scanner.Err()
		if readErr == nil && ctx.Err() == nil {
			readErr = errors.New("aidr_enforcement_native_exit")
			// EOF means this native monitor cannot emit another sequence. The
			// supervisor records the observed exit using its last health identity;
			// it does not manufacture a process identity when startup failed.
			if health.Monitor != "" && lastSequence < ^uint64(0) {
				health.Sequence = strconv.FormatUint(lastSequence+1, 10)
				health.Time = strconv.FormatInt(time.Now().UnixNano(), 10)
				health.Code = "aidr_enforcement_native_exit"
				if e := s.Append(context.Background(), health); e != nil {
					readErr = e
				}
			}
		}
		readDone <- readErr
		cancel()
	}()
	write := func(kind string, raw []byte) error {
		line, e := json.Marshal(struct {
			Type     string          `json:"type"`
			Envelope json.RawMessage `json:"envelope"`
		}{kind, json.RawMessage(raw)})
		if e != nil {
			return e
		}
		_, e = input.Write(append(line, '\n'))
		return e
	}
	var runErr error
	transportCode := ""
	reportTransport := func(code string) {
		notify(systemObservation{Code: code})
		_ = s.Guard.SetUploadCode(context.Background(), code)
		if code != transportCode {
			transportCode = code
			reason := "aidr_enforcement_transport_failed"
			if code == "" {
				reason = "aidr_enforcement_transport_restored"
			}
			raw, _ := json.Marshal(map[string]string{"code": reason})
			_ = write("health", raw)
		}
	}
	var policyAt, commandsAt time.Time
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
loop:
	for {
		if ctx.Err() != nil {
			break
		}
		if !time.Now().Before(policyAt) {
			if observe != nil {
				bootstrap, result := c.RuntimeGet(ctx, "bootstrap")
				if result.Code == "" {
					var value struct {
						Version string `json:"runtime_policy_version"`
						Mode    string `json:"mode"`
					}
					if json.Unmarshal(bootstrap, &value) == nil && validRuntimePolicyVersion(value.Version) {
						if value.Mode != "audit" && value.Mode != "intercept" {
							runErr = errors.New("aidr_system_mode_invalid")
							break
						}
						if (value.Mode == "audit") != *collectionOnly {
							runErr = errors.New("aidr_system_mode_changed")
							break
						}
						notify(systemObservation{PolicyVersion: value.Version})
					}
				}
				if result.Code == "aidr.system_collection_disabled" || result.Code == "aidr.system_policy_required" || result.Code == "aidr_upload_auth_rejected" {
					runErr = errors.New(result.Code)
					break
				}
			}
			data, result := c.RuntimeGet(ctx, "snapshot")
			policyAt = time.Now().Add(10 * time.Second)
			if result.Code == "" {
				raw, e := upload.DecodeRuntimeSnapshot(data)
				if e != nil {
					reportTransport("aidr_enforcement_snapshot_invalid")
				}
				if raw != nil {
					// The native trust boundary independently verifies the pinned
					// signature and retains its old policy on rejection.
					kind := "policy"
					if *collectionOnly {
						kind = "attribution"
					}
					if e = write(kind, raw); e != nil {
						runErr = e
						break
					}
				}
			} else {
				reportTransport(result.Code)
			}
		}
		// Send durable observations before requesting commands, so the platform
		// has the exact target identity cited by an administrator.
		for i := 0; i < 8; i++ {
			result, e := c.SendRuntime(ctx, s)
			if e != nil {
				runErr = e
				break loop
			}
			if result.Code != "" {
				reportTransport(result.Code)
				break
			}
			if result.Uploaded {
				reportTransport("")
			}
			if pending, e := s.Pending(context.Background()); e == nil {
				notify(systemObservation{Pending: &pending, Uploaded: result.Uploaded, Code: result.Code})
			}
			if !result.Uploaded {
				break
			}
		}
		if !*collectionOnly && !time.Now().Before(commandsAt) {
			data, result := c.RuntimeGet(ctx, "commands")
			commandsAt = time.Now().Add(2 * time.Second)
			if result.Code == "" {
				commands, e := upload.DecodeRuntimeCommands(data)
				if e != nil {
					reportTransport("aidr_enforcement_commands_invalid")
				}
				for _, raw := range commands {
					if e = write("terminate", raw); e != nil {
						runErr = e
						break loop
					}
				}
			} else {
				reportTransport(result.Code)
			}
		}
		select {
		case <-ctx.Done():
			break loop
		case <-ticker.C:
		}
	}
	cancel()
	kill()
	var readErr error
	select {
	case readErr = <-readDone:
	case <-time.After(5 * time.Second):
		_ = cmd.Process.Kill()
		readErr = errors.New("aidr_enforcement_shutdown_timeout")
	}
	waitErr := cmd.Wait()
	// Final native stop evidence remains durable even when the platform is down.
	flush, flushCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer flushCancel()
	drain, drainErr := c.DrainRuntime(flush, s, 8)
	if pending, e := s.Pending(context.Background()); e == nil {
		drain.Pending = &pending
	}
	notify(systemObservation{Pending: drain.Pending, Uploaded: drain.Batches > 0, Code: drain.Code})
	if runErr != nil && !errors.Is(runErr, context.Canceled) && ctx.Err() == nil {
		return runErr
	}
	if readErr != nil {
		if readErr.Error() == "aidr_enforcement_native_exit" {
			return errors.New(diagnostics.code())
		}
		return readErr
	}
	if waitErr != nil && ctx.Err() == nil {
		return errors.New(diagnostics.code())
	}
	if runErr != nil && !errors.Is(runErr, context.Canceled) {
		return runErr
	}
	if drainErr != nil {
		return drainErr
	}
	return json.NewEncoder(out).Encode(struct {
		Code string `json:"code"`
		upload.RuntimeDrainResult
	}{Code: "aidr_enforcement_stopped", RuntimeDrainResult: drain})
}
