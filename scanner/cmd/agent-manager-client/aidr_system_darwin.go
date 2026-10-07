//go:build darwin

package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"skill-manager/scanner/internal/aidr/enforcement"
	"skill-manager/scanner/internal/aidr/upload"
)

// Set only by the development packaging target. Release builds never ad-hoc sign.
var systemDevelopment = "false"
var systemNativeDigest string

const systemStatusLimit = 1 << 20

const systemRoot = "/Library/Application Support/AgentManagerRuntime/system"
const systemEntitlement = `<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>com.apple.developer.endpoint-security.client</key><true/></dict></plist>`

type systemRequest struct {
	UID        int    `json:"uid"`
	Created    int64  `json:"created"`
	Server     string `json:"server"`
	Device     string `json:"device"`
	Token      string `json:"token"`
	PublicKey  string `json:"public_key"`
	Binary     string `json:"binary"`
	Native     string `json:"native"`
	BinaryHash string `json:"binary_hash"`
	NativeHash string `json:"native_hash"`
}
type systemStatus struct {
	Network       *enforcement.NetworkHealth `json:"network_health,omitempty"`
	Mode          string                     `json:"mode,omitempty"`
	TargetMode    string                     `json:"target_mode,omitempty"`
	PolicyVersion string                     `json:"policy_version,omitempty"`
	Observed      string                     `json:"observed_at,omitempty"`
	State         string                     `json:"state"`
	Code          string                     `json:"code,omitempty"`
	Development   bool                       `json:"development"`
	Device        string                     `json:"device,omitempty"`
	Server        string                     `json:"server,omitempty"`
	Started       string                     `json:"started_at,omitempty"`
	Health        string                     `json:"health_at,omitempty"`
	Uploaded      string                     `json:"uploaded_at,omitempty"`
	UploadCode    string                     `json:"upload_code,omitempty"`
	Pending       *int                       `json:"pending_uploads"`
	Events        int                        `json:"event_count"`
	Recent        []enforcement.Record       `json:"recent"`
}

func systemSocket(uid int) string {
	return fmt.Sprintf("/private/var/run/agent-manager-system-%d.sock", uid)
}
func systemStatusPath(uid int) string {
	return filepath.Join(systemRoot, "status", strconv.Itoa(uid)+".json")
}
func systemHash(b []byte) string    { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func systemError(code string) error { return errors.New("aidr_system_" + code) }

func systemRead(path string, owner int, max int64) ([]byte, error) {
	fd, e := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if e != nil {
		return nil, e
	}
	f := os.NewFile(uintptr(fd), path)
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return nil, e
	}
	s, ok := st.Sys().(*syscall.Stat_t)
	if !ok || !st.Mode().IsRegular() || int(s.Uid) != owner || st.Mode().Perm()&0022 != 0 || st.Size() > max {
		return nil, systemError("file_invalid")
	}
	return io.ReadAll(io.LimitReader(f, max+1))
}
func systemAtomic(path string, b []byte, mode os.FileMode) error {
	f, e := os.CreateTemp(filepath.Dir(path), ".system-*")
	if e != nil {
		return e
	}
	defer os.Remove(f.Name())
	if e = f.Chmod(mode); e == nil {
		_, e = f.Write(b)
	}
	if e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e == nil {
		e = closeErr
	}
	if e != nil {
		return e
	}
	return os.Rename(f.Name(), path)
}
func systemJSON(path string, v any, mode os.FileMode) error {
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	return systemAtomic(path, b, mode)
}
func systemCall(uid int, action string) (systemStatus, error) {
	var status systemStatus
	c, e := net.DialTimeout("unix", systemSocket(uid), time.Second)
	if e != nil {
		return status, e
	}
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(20 * time.Second))
	if _, e = io.WriteString(c, action+"\n"); e != nil {
		return status, e
	}
	e = json.NewDecoder(io.LimitReader(c, systemStatusLimit)).Decode(&status)
	return status, e
}
func systemLocalStatus(uid int) systemStatus {
	s, e := systemCall(uid, "status")
	if e == nil {
		return s
	}
	s = systemStatus{State: "stopped", Development: systemDevelopment == "true"}
	b, e := systemRead(systemStatusPath(uid), uid, systemStatusLimit)
	if e == nil && json.Unmarshal(b, &s) == nil && (s.State == "collecting" || s.State == "starting" || s.State == "draining") {
		s.State = "failed"
		s.Code = "aidr_system_process_lost"
	}
	return s
}

func aidrSystem(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-system", flag.ContinueOnError)
	action := fs.String("action", "status", "prepare, install-start, run, status or stop")
	home := fs.String("home", "", "managed user home")
	native := fs.String("native", "", "bundled native collector")
	request := fs.String("request", "", "private installation request")
	uid := fs.Int("uid", os.Getuid(), "collection owner")
	config := fs.String("config", "", "root-owned collection configuration")
	if e := fs.Parse(args); e != nil {
		return e
	}
	if fs.NArg() != 0 {
		return systemError("request_invalid")
	}
	switch *action {
	case "status":
		return json.NewEncoder(out).Encode(systemLocalStatus(os.Getuid()))
	case "stop":
		s, e := systemCall(os.Getuid(), "stop")
		if e != nil {
			s = systemLocalStatus(os.Getuid())
			if s.State != "stopped" && s.State != "failed" {
				return systemError("stop_failed")
			}
		}
		return json.NewEncoder(out).Encode(s)
	case "prepare":
		if os.Geteuid() == 0 {
			return systemError("desktop_must_be_unprivileged")
		}
		cfg, p, e := desktopBinding(*home)
		if e != nil {
			return e
		}
		c, e := upload.New(upload.Options{Server: cfg.Server, ClientID: p.Device, Token: cfg.Token})
		if e != nil {
			return e
		}
		defer c.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		b, result := c.RuntimeGet(ctx, "bootstrap")
		if result.Code != "" {
			return errors.New(result.Code)
		}
		var bootstrap struct {
			PublicKey string `json:"public_key"`
		}
		if json.Unmarshal(b, &bootstrap) != nil {
			return systemError("bootstrap_invalid")
		}
		key, e := base64.StdEncoding.DecodeString(bootstrap.PublicKey)
		if e != nil || len(key) != 65 || key[0] != 4 {
			return systemError("bootstrap_invalid")
		}
		binary, e := os.Executable()
		if e != nil {
			return e
		}
		binary, e = filepath.EvalSymlinks(binary)
		if e != nil {
			return e
		}
		nativePath, e := filepath.EvalSymlinks(*native)
		if e != nil {
			return systemError("component_missing")
		}
		binaryBytes, e := os.ReadFile(binary)
		if e != nil {
			return e
		}
		nativeBytes, e := os.ReadFile(nativePath)
		if e != nil {
			return e
		}
		r := systemRequest{UID: os.Getuid(), Created: time.Now().Unix(), Server: cfg.Server, Device: p.Device, Token: cfg.Token, PublicKey: bootstrap.PublicKey, Binary: binary, Native: nativePath, BinaryHash: systemHash(binaryBytes), NativeHash: systemHash(nativeBytes)}
		if systemNativeDigest == "" || r.NativeHash != systemNativeDigest {
			return systemError("component_changed")
		}
		if e = os.MkdirAll(p.Root, 0700); e != nil {
			return e
		}
		f, e := os.CreateTemp(p.Root, "system-request-*.json")
		if e != nil {
			return e
		}
		name := f.Name()
		f.Close()
		if e = systemJSON(name, r, 0600); e != nil {
			os.Remove(name)
			return e
		}
		return json.NewEncoder(out).Encode(map[string]string{"request": name})
	case "install-start":
		if os.Geteuid() != 0 {
			return systemError("root_required")
		}
		return systemInstallStart(*request, *uid, out)
	case "run":
		if os.Geteuid() != 0 {
			return systemError("root_required")
		}
		return systemRun(*config, *uid)
	default:
		return systemError("request_invalid")
	}
}

func systemRootDir(path string, mode os.FileMode) error {
	if !strings.HasPrefix(path, systemRoot) {
		return systemError("path_invalid")
	}
	// Validate existing parents before creating anything beneath them.
	var parents []string
	for p := path; p != "/"; p = filepath.Dir(p) {
		parents = append(parents, p)
	}
	for i := len(parents) - 1; i >= 0; i-- {
		p := parents[i]
		if _, err := os.Lstat(p); os.IsNotExist(err) {
			permission := os.FileMode(0755)
			if p == path {
				permission = mode
			}
			if err = os.Mkdir(p, permission); err != nil {
				return err
			}
		}
		info, e := os.Lstat(p)
		if e != nil {
			return e
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		if !ok || !info.IsDir() || st.Uid != 0 || info.Mode().Perm()&0022 != 0 {
			return systemError("root_path_invalid")
		}
	}
	return nil
}
func systemInstallStart(path string, uid int, out io.Writer) error {
	if uid <= 0 {
		return systemError("request_invalid")
	}
	b, e := systemRead(path, uid, 16384)
	if e != nil {
		return e
	}
	var r systemRequest
	if json.Unmarshal(b, &r) != nil || r.UID != uid || time.Now().Unix()-r.Created > 180 || r.Created > time.Now().Unix()+5 {
		return systemError("request_invalid")
	}
	self, e := os.Executable()
	if e != nil {
		return e
	}
	self, e = filepath.EvalSymlinks(self)
	if e != nil {
		return e
	}
	selfBytes, e := os.ReadFile(self)
	if e != nil || r.Binary != self || r.BinaryHash != systemHash(selfBytes) || systemNativeDigest == "" || r.NativeHash != systemNativeDigest {
		return systemError("component_changed")
	}
	info, e := os.Stat(path)
	if e != nil || info.Mode().Perm() != 0600 {
		return systemError("request_invalid")
	}
	if e = systemRootDir(systemRoot, 0755); e != nil {
		return e
	}
	lock, e := os.OpenFile(filepath.Join(systemRoot, "install.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if e != nil {
		return e
	}
	defer lock.Close()
	if e = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); e != nil {
		return systemError("busy")
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
	if s, e := systemCall(uid, "status"); e == nil {
		return json.NewEncoder(out).Encode(s)
	}
	binDir := filepath.Join(systemRoot, "bin")
	if e = systemRootDir(binDir, 0755); e != nil {
		return e
	}
	development := systemDevelopment == "true"
	if development {
		sip, e := exec.Command("/usr/bin/csrutil", "status").Output()
		if e != nil || !strings.Contains(string(sip), "System Integrity Protection status: disabled.") {
			return systemError("development_requires_sip_disabled")
		}
	}
	// Installation identity is the source content plus signing mode. A normal start
	// verifies the installed files and leaves the signature (and FDA identity) intact.
	manifestPath := filepath.Join(systemRoot, "components.json")
	desired := map[string]string{"binary": r.BinaryHash, "native": r.NativeHash, "development": strconv.FormatBool(development)}
	old := map[string]string{}
	if raw, e := os.ReadFile(manifestPath); e == nil {
		_ = json.Unmarshal(raw, &old)
	}
	for _, component := range []struct{ name, source, digest string }{{"agent-manager-client", r.Binary, r.BinaryHash}, {"aidr-enforcer", r.Native, r.NativeHash}} {
		dest := filepath.Join(binDir, component.name)
		key := "binary"
		if component.name == "aidr-enforcer" {
			key = "native"
		}
		unchanged := old[key] == component.digest && old["development"] == desired["development"]
		if unchanged {
			raw, err := systemRead(dest, 0, 200<<20)
			unchanged = err == nil && systemHash(raw) == old[key+"_installed"]
		}
		if !unchanged {
			sourceOwner := uid
			if st, e := os.Stat(component.source); e == nil {
				if s, ok := st.Sys().(*syscall.Stat_t); ok && s.Uid == 0 {
					sourceOwner = 0
				}
			}
			raw, e := systemRead(component.source, sourceOwner, 200<<20)
			if e != nil || systemHash(raw) != component.digest {
				return systemError("component_changed")
			}
			staged := dest + ".installing"
			if e = systemAtomic(staged, raw, 0755); e != nil {
				return e
			}
			if development && key == "native" {
				ent := filepath.Join(systemRoot, "entitlements.plist")
				if e = systemAtomic(ent, []byte(systemEntitlement), 0600); e != nil {
					return e
				}
				if e = exec.Command("/usr/bin/codesign", "--force", "--sign", "-", "--entitlements", ent, staged).Run(); e != nil {
					return systemError("sign_failed")
				}
			} else if development {
				if e = exec.Command("/usr/bin/codesign", "--force", "--sign", "-", staged).Run(); e != nil {
					return systemError("sign_failed")
				}
			}
			if e = systemVerifyComponent(staged, key == "native", development); e != nil {
				os.Remove(staged)
				return e
			}
			if e = os.Rename(staged, dest); e != nil {
				return e
			}
		}
		if e = systemVerifyComponent(dest, key == "native", development); e != nil {
			return e
		}
		raw, e := os.ReadFile(dest)
		if e != nil {
			return e
		}
		desired[key+"_installed"] = systemHash(raw)
	}
	if e = systemJSON(manifestPath, desired, 0600); e != nil {
		return e
	}
	if e = systemRootDir(filepath.Join(systemRoot, "state"), 0700); e != nil {
		return e
	}
	binding := systemHash([]byte(r.Server + "\x00" + r.Device))
	state := filepath.Join(systemRoot, "state", strconv.Itoa(uid)+"-"+binding[:24])
	if e = systemRootDir(state, 0700); e != nil {
		return e
	}
	key, e := base64.StdEncoding.DecodeString(r.PublicKey)
	if e != nil || len(key) != 65 || key[0] != 4 {
		return systemError("bootstrap_invalid")
	}
	keyPath := filepath.Join(state, "public-key.bin")
	if previous, e := os.ReadFile(keyPath); e == nil && !bytes.Equal(previous, key) {
		return systemError("key_changed")
	}
	if e = systemAtomic(keyPath, key, 0600); e != nil {
		return e
	}
	r.Native = filepath.Join(binDir, "aidr-enforcer")
	r.Binary = filepath.Join(binDir, "agent-manager-client")
	config := filepath.Join(state, "connection.json")
	if e = systemJSON(config, r, 0600); e != nil {
		return e
	}
	if e = systemRootDir(filepath.Join(systemRoot, "status"), 0755); e != nil {
		return e
	}
	cmd := exec.Command(r.Binary, "aidr-system", "--action", "run", "--uid", strconv.Itoa(uid), "--config", config)
	cmd.Env = []string{"PATH=/usr/bin:/bin:/usr/sbin:/sbin", "LANG=C"}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if e = cmd.Start(); e != nil {
		return systemError("launch_failed")
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	for i := 0; i < 100; i++ {
		if s, e := systemCall(uid, "status"); e == nil {
			return json.NewEncoder(out).Encode(s)
		}
		select {
		case <-done:
			if raw, e := systemRead(systemStatusPath(uid), uid, systemStatusLimit); e == nil {
				var s systemStatus
				if json.Unmarshal(raw, &s) == nil && s.State == "failed" {
					return json.NewEncoder(out).Encode(s)
				}
			}
			return systemError("launch_failed")
		case <-time.After(50 * time.Millisecond):
		}
	}
	_ = cmd.Process.Kill()
	<-done
	return systemError("launch_timeout")
}

func systemVerifyComponent(path string, native, development bool) error {
	if exec.Command("/usr/bin/codesign", "--verify", "--strict", path).Run() != nil {
		return systemError("signature_invalid")
	}
	if native {
		b, e := exec.Command("/usr/bin/codesign", "-d", "--entitlements", ":-", path).Output()
		if e != nil || !hasESEntitlement(b) {
			return systemError("entitlement_required")
		}
	}
	if !development {
		if exec.Command("/usr/bin/codesign", "--verify", "-R=anchor apple generic and certificate leaf[field.1.2.840.113635.100.6.1.13] exists", path).Run() != nil {
			return systemError("developer_id_required")
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		self, e := os.Executable()
		if e != nil {
			return systemError("signature_invalid")
		}
		productTeam, _, ok := systemSignature(ctx, self, "")
		team, _, signed := systemSignature(ctx, path, "")
		if !ok || !signed || team != productTeam {
			return systemError("signature_invalid")
		}
	}
	return nil
}

func systemRun(config string, uid int) error {
	if uid <= 0 || rootFile(config, false) != nil {
		return systemError("config_invalid")
	}
	b, e := systemRead(config, 0, 16384)
	if e != nil {
		return e
	}
	var r systemRequest
	if json.Unmarshal(b, &r) != nil || r.UID != uid {
		return systemError("config_invalid")
	}
	path := systemSocket(uid)
	// Only this root-owned parent can replace the endpoint; stale sockets carry no PID authority.
	if _, e := systemCall(uid, "status"); e == nil {
		return systemError("busy")
	}
	_ = os.Remove(path)
	listener, e := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if e != nil {
		return e
	}
	defer listener.Close()
	defer os.Remove(path)
	if e = os.Chown(path, uid, -1); e != nil {
		return e
	}
	if e = os.Chmod(path, 0600); e != nil {
		return e
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var mu sync.Mutex
	status := systemStatus{State: "starting", Device: r.Device, Server: r.Server, Development: systemDevelopment == "true", Started: time.Now().UTC().Format(time.RFC3339), Recent: []enforcement.Record{}}
	status.Observed = status.Started
	snapshot := func() systemStatus {
		mu.Lock()
		defer mu.Unlock()
		v := status
		v.Recent = append([]enforcement.Record{}, status.Recent...)
		if v.State == "collecting" {
			at, _ := time.Parse(time.RFC3339Nano, v.Health)
			if time.Since(at) > 5*time.Second {
				v.State = "degraded"
				v.Code = "aidr_system_heartbeat_stale"
			}
		}
		return v
	}
	done := make(chan struct{})
	if e = systemJSON(systemStatusPath(uid), snapshot(), 0600); e != nil {
		return e
	}
	if e = os.Chown(systemStatusPath(uid), uid, -1); e != nil {
		return e
	}
	go func() {
		for {
			conn, e := listener.AcceptUnix()
			if e != nil {
				return
			}
			go func(c *net.UnixConn) {
				defer c.Close()
				_ = c.SetDeadline(time.Now().Add(20 * time.Second))
				line, e := bufio.NewReader(io.LimitReader(c, 16)).ReadString('\n')
				if e != nil {
					return
				}
				action := strings.TrimSpace(line)
				if action == "stop" {
					mu.Lock()
					if status.State != "failed" && status.State != "stopped" {
						status.State = "draining"
					}
					mu.Unlock()
					cancel()
					select {
					case <-done:
					case <-time.After(18 * time.Second):
					}
				} else if action != "status" {
					return
				}
				_ = json.NewEncoder(c).Encode(snapshot())
			}(conn)
		}
	}()
	// Credentials remain in the root-only configuration/environment, never process arguments.
	_ = os.Setenv("AGENT_MANAGER_AIDR_TOKEN", r.Token)
	var err error
	for {
		err = aidrEnforceRun(ctx, []string{"--state-dir", filepath.Dir(config), "--native", r.Native, "--public-key", filepath.Join(filepath.Dir(config), "public-key.bin"), "--server", r.Server, "--client-id", r.Device, "--duration", "0"}, io.Discard, func(v systemObservation) {
			mu.Lock()
			defer mu.Unlock()
			if v.Mode != "" {
				status.TargetMode = v.Mode
			}
			if v.Record != nil {
				status.Observed = time.Now().UTC().Format(time.RFC3339Nano)
				event := *v.Record
				if event.Kind == "health" {
					status.Network = event.NetworkHealth
					status.Health = time.Now().UTC().Format(time.RFC3339Nano)
					if (event.Code == "aidr_enforcement_collection_only" || event.Code == "aidr_enforcement_active") && status.State != "draining" {
						status.State = "collecting"
						status.Mode = "audit"
						if event.Code == "aidr_enforcement_active" {
							status.Mode = "intercept"
						}
					}
					if event.Code == "aidr_enforcement_stopped" {
						status.State = "draining"
					}
				}
				if event.Kind == "process" || event.Kind == "file" || event.Kind == "network" {
					status.Events++
					status.Recent = append([]enforcement.Record{event}, status.Recent...)
					if len(status.Recent) > 12 {
						status.Recent = status.Recent[:12]
					}
				}
				if event.Kind == "policy" && event.Result == "rejected" {
					status.Code = event.Code
				}
				if event.Kind == "policy" && event.Result == "applied" {
					status.Code = ""
				}
			}
			if v.Pending != nil {
				n := *v.Pending
				status.Pending = &n
			}
			if v.Uploaded {
				status.Uploaded = time.Now().UTC().Format(time.RFC3339)
			}
			if v.PolicyVersion != "" {
				status.PolicyVersion = v.PolicyVersion
			}
			if v.Record == nil && v.PolicyVersion == "" && v.Mode == "" {
				status.UploadCode = v.Code
			}
		})
		if err == nil || err.Error() != "aidr_system_mode_changed" || ctx.Err() != nil {
			break
		}
		mu.Lock()
		status.State, status.Mode, status.PolicyVersion = "starting", "", ""
		status.Code = "aidr_system_mode_switching"
		mu.Unlock()
	}
	mu.Lock()
	status.State = "stopped"
	status.Observed = time.Now().UTC().Format(time.RFC3339Nano)
	if err != nil {
		status.State = "failed"
		status.Code = systemSafeError(err)
	}
	mu.Unlock()
	final := snapshot()
	if e = systemJSON(systemStatusPath(uid), final, 0600); e == nil {
		e = os.Chown(systemStatusPath(uid), uid, -1)
	}
	close(done)
	// Let the pending stop response complete before closing the control endpoint.
	time.Sleep(150 * time.Millisecond)
	return e
}
func systemSafeError(e error) string {
	code := e.Error()
	if len(code) < 140 && (strings.HasPrefix(code, "aidr_") || strings.HasPrefix(code, "aidr.")) && !strings.ContainsAny(code, " /\n\t") {
		return code
	}
	return "aidr_system_runtime_failed"
}

func systemRuntimeChannel(paths desktopPaths) map[string]any {
	s := systemLocalStatus(os.Getuid())
	if s.Device != paths.Device || systemHash([]byte(s.Server + "\x00" + s.Device))[:32] != filepath.Base(paths.State) || s.Observed == "" {
		return nil
	}
	state, code := s.State, s.Code
	if state == "collecting" {
		state, code = "running", "aidr_enforcement_collection_only"
		if s.Mode == "intercept" {
			code = "aidr_enforcement_active"
		}
	}
	if state == "degraded" {
		state = "unknown"
	}
	if code == "" {
		code = "aidr_system_" + state
	}
	code = strings.ReplaceAll(code, ".", "_")
	v := map[string]any{"state": state, "code": code, "reported_at": s.Observed, "enabled": s.State == "collecting" || s.State == "starting"}
	if s.Mode != "" {
		v["mode"] = s.Mode
	}
	if s.PolicyVersion != "" {
		v["policy_version"] = s.PolicyVersion
	}
	if s.Pending != nil {
		v["queued_records"] = *s.Pending
	}
	if s.Uploaded != "" {
		v["last_ack_at"] = s.Uploaded
	}
	if s.UploadCode != "" && validRuntimeCode(s.UploadCode) {
		v["transport_code"] = s.UploadCode
	}
	return v
}
