package hooks

import (
	"context"
	"path/filepath"
	"strconv"
	"time"

	"golang.org/x/sys/windows"
)

func processIdentity(ctx context.Context, pid int) (string, string) {
	if ctx.Err() != nil {
		return "", ""
	}
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return "", ""
	}
	defer windows.CloseHandle(h)
	var created, exited, kernel, user windows.Filetime
	if windows.GetProcessTimes(h, &created, &exited, &kernel, &user) != nil {
		return "", ""
	}
	var buf [32768]uint16
	n := uint32(len(buf))
	if windows.QueryFullProcessImageName(h, 0, &buf[0], &n) != nil {
		return "", ""
	}
	return strconv.FormatInt(created.Nanoseconds(), 10), windows.UTF16ToString(buf[:n])
}

func DiagnoseReceiver(ctx context.Context, socket, queue, server, device, expectedBinary string) ReceiverDiagnostic {
	d := ReceiverDiagnostic{Ownership: "unavailable", Socket: socket, Queue: queue, ExpectedServer: diagnosticServer(server), Device: device, Code: "aidr_hook_receiver_unavailable"}
	d.AuditGap, _ = ReadBridgeGap(filepath.Join(queue, "bridge-gap.json"))
	c, err := dialHookEndpoint(ctx, socket)
	if err != nil {
		return d
	}
	defer c.Close()
	d.Ownership = "external_unverified"
	if _, err := authenticatedPeer(c); err != nil {
		d.Code = "aidr_hook_peer_rejected"
		return d
	}
	pid, err := pipePeerPID(c)
	if err != nil {
		d.Code = "aidr_receiver_identity_unavailable"
		return d
	}
	d.PID = int(pid)
	d.ProcessStartedAt, d.Executable = processIdentity(ctx, d.PID)
	c.SetDeadline(time.Now().Add(2 * time.Second))
	var reply IPCResponse
	if writeFrame(c, IPCRequest{Version: 1, Method: "GetHealth"}) != nil || readFrame(c, &reply) != nil {
		return d
	}
	start, binary := processIdentity(ctx, d.PID)
	digest := executableDigest(expectedBinary)
	if d.ProcessStartedAt == "" || start != d.ProcessStartedAt || binary != d.Executable || digest == "" || executableDigest(binary) != digest || reply.Version != 1 || reply.Code != "aidr_hook_healthy" || reply.Receiver == nil || reply.Receiver.PID != d.PID || reply.Receiver.Socket != socket || reply.Receiver.StartedAt == "" || reply.State == nil || reply.State.ReceiverInstance == "" {
		d.Code = "aidr_receiver_identity_unavailable"
		return d
	}
	d.Receiver = reply.Receiver
	if reply.Receiver.Queue != queue || reply.Receiver.Server != d.ExpectedServer || reply.State.Device != device {
		d.Code = "aidr_receiver_binding_mismatch"
		return d
	}
	d.Ownership, d.Code, d.State = "external_verified", reply.Code, reply.State
	return d
}
