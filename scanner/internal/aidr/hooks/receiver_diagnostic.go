package hooks

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

type ReceiverIdentity struct {
	PID       int    `json:"pid"`
	StartedAt string `json:"started_at"`
	Server    string `json:"server"`
	Socket    string `json:"socket"`
	Queue     string `json:"queue"`
}

type ReceiverDiagnostic struct {
	Ownership        string            `json:"ownership"`
	Socket           string            `json:"socket"`
	Queue            string            `json:"queue"`
	ExpectedServer   string            `json:"expected_server"`
	Device           string            `json:"device"`
	PID              int               `json:"pid,omitempty"`
	UID              uint32            `json:"uid"`
	ProcessStartedAt string            `json:"process_started_at,omitempty"`
	Executable       string            `json:"executable,omitempty"`
	Receiver         *ReceiverIdentity `json:"receiver,omitempty"`
	State            *StoreStatus      `json:"state,omitempty"`
	Code             string            `json:"code"`
	AuditGap         *BridgeGap        `json:"audit_gap,omitempty"`
	AuditGapCode     string            `json:"audit_gap_code,omitempty"`
}

func diagnosticServer(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || (u.Scheme != "https" && u.Scheme != "http") {
		return ""
	}
	u.User, u.RawQuery, u.Fragment, u.RawFragment = nil, "", "", ""
	return u.String()
}
func executableDigest(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return ""
	}
	return hex.EncodeToString(h.Sum(nil))
}
func processIdentity(ctx context.Context, pid int) (string, string) {
	// Fixed fields from the kernel process table; never inspect command arguments.
	start, e := exec.CommandContext(ctx, "/bin/ps", "-p", strconv.Itoa(pid), "-o", "lstart=").Output()
	if e != nil {
		return "", ""
	}
	if runtime.GOOS == "linux" {
		binary, err := os.Readlink(filepath.Join("/proc", strconv.Itoa(pid), "exe"))
		if err != nil {
			return "", ""
		}
		return strings.TrimSpace(string(start)), binary
	}
	binary, e := exec.CommandContext(ctx, "/bin/ps", "-p", strconv.Itoa(pid), "-o", "comm=").Output()
	if e != nil {
		return "", ""
	}
	return strings.TrimSpace(string(start)), strings.TrimSpace(string(binary))
}

// DiagnoseReceiver only connects to the private endpoint and reads health.
// Missing identity or a failed probe never authorizes socket removal.
func DiagnoseReceiver(ctx context.Context, socket, queue, server, device, expectedBinary string) ReceiverDiagnostic {
	d := ReceiverDiagnostic{Ownership: "unavailable", Socket: socket, Queue: queue, ExpectedServer: diagnosticServer(server), Device: device, Code: "aidr_hook_receiver_unavailable"}
	gap, gapErr := ReadBridgeGap(filepath.Join(queue, "bridge-gap.json"))
	d.AuditGap = gap
	if gapErr != nil {
		d.AuditGapCode = "aidr_hook_gap_report_failed"
	}
	dir := filepath.Dir(socket)
	real, err := filepath.EvalSymlinks(dir)
	if err != nil || real != dir {
		d.Code = "aidr_hook_socket_invalid"
		return d
	}
	parent, err := os.Lstat(dir)
	if err != nil || !parent.IsDir() || parent.Mode().Perm()&0077 != 0 || !ownedBy(parent, uint32(os.Geteuid())) {
		d.Code = "aidr_hook_socket_invalid"
		return d
	}
	info, err := os.Lstat(socket)
	if os.IsNotExist(err) {
		return d
	}
	d.Ownership = "external_unverified"
	if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm()&0077 != 0 || !ownedBy(info, uint32(os.Geteuid())) {
		d.Code = "aidr_hook_socket_invalid"
		return d
	}
	c, err := (&net.Dialer{Timeout: time.Second}).DialContext(ctx, "unix", socket)
	if err != nil {
		return d
	}
	defer c.Close()
	d.UID, err = peerUID(c.(*net.UnixConn))
	if err != nil || d.UID != uint32(os.Geteuid()) {
		d.Code = "aidr_hook_peer_rejected"
		return d
	}
	d.PID, err = diagnosticPeerPID(c.(*net.UnixConn))
	if err != nil || d.PID <= 0 {
		d.Code = "aidr_receiver_identity_unavailable"
		return d
	}
	d.ProcessStartedAt, d.Executable = processIdentity(ctx, d.PID)
	c.SetDeadline(time.Now().Add(2 * time.Second))
	var reply IPCResponse
	if writeFrame(c, IPCRequest{Version: 1, Method: "GetHealth"}) != nil || readFrame(c, &reply) != nil || reply.Version != 1 {
		d.Code = "aidr_hook_protocol_invalid"
		return d
	}
	after, _ := os.Lstat(socket)
	startAfter, binaryAfter := processIdentity(ctx, d.PID)
	expectedDigest := executableDigest(expectedBinary)
	if after == nil || !os.SameFile(info, after) || d.ProcessStartedAt == "" || startAfter != d.ProcessStartedAt || binaryAfter != d.Executable || expectedDigest == "" || executableDigest(d.Executable) != expectedDigest || reply.Receiver == nil || reply.Receiver.PID != d.PID || reply.Receiver.Socket != socket || reply.Receiver.StartedAt == "" || reply.State == nil || reply.State.ReceiverInstance == "" || reply.Code != "aidr_hook_healthy" {
		d.Code = "aidr_receiver_identity_unavailable"
		return d
	}
	d.Receiver = reply.Receiver
	if reply.Receiver.Queue != queue || reply.Receiver.Server != d.ExpectedServer || reply.State.Device != device {
		d.Code = "aidr_receiver_binding_mismatch"
		return d
	}
	d.Ownership, d.Code, d.Receiver, d.State = "external_verified", reply.Code, reply.Receiver, reply.State
	return d
}
