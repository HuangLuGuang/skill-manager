package runtimeobservation

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"path/filepath"
	"strings"
	"time"
)

type WatchOptions struct {
	SocketPath                    string
	ReconnectDelay, HealthTimeout time.Duration
}

type Output struct {
	Protocol       int    `json:"protocol"`
	Type           string `json:"type"`
	Transport      string `json:"transport"`
	ObserverHealth string `json:"observer_health"`
	Reason         string `json:"reason,omitempty"`
	Reset          bool   `json:"reset"`
	Frame          *Frame `json:"frame,omitempty"`
}

func Watch(ctx context.Context, out io.Writer, options WatchOptions) error {
	if options.SocketPath == "" {
		return fmt.Errorf("runtime_observation_socket_required")
	}
	if !filepath.IsAbs(options.SocketPath) {
		return fmt.Errorf("runtime_observation_socket_path_absolute")
	}
	if options.ReconnectDelay <= 0 {
		options.ReconnectDelay = time.Second
	}
	if options.HealthTimeout <= 0 {
		options.HealthTimeout = 5 * time.Second
	}
	emitter, err := newEmitter(ctx, out)
	if err != nil {
		return err
	}
	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		if err := emitter.emit(Output{Protocol: ProtocolVersion, Type: "client_status", Transport: "connecting", ObserverHealth: "unknown", Reset: true, Reason: "new_transport_connection"}); err != nil {
			return err
		}
		conn, err := dialVerified(options.SocketPath)
		if err != nil {
			if errors.Is(err, ErrUnsupported) {
				return err
			}
			reason := stableReason(err)
			if encodeErr := emitter.emit(Output{Protocol: ProtocolVersion, Type: "client_status", Transport: "offline", ObserverHealth: "unknown", Reset: true, Reason: reason}); encodeErr != nil {
				return encodeErr
			}
			if reason == "unsafe_socket" || reason == "untrusted_peer" {
				return fmt.Errorf("runtime_observation_%s", reason)
			}
			if !wait(ctx, options.ReconnectDelay) {
				return nil
			}
			continue
		}
		err = consume(ctx, conn, emitter, options.HealthTimeout)
		conn.Close()
		if errors.Is(err, ErrOutputFailure) {
			return err
		}
		if encodeErr := emitter.emit(Output{Protocol: ProtocolVersion, Type: "client_status", Transport: "offline", ObserverHealth: "unknown", Reset: true, Reason: stableReason(err)}); encodeErr != nil {
			return encodeErr
		}
		if !wait(ctx, options.ReconnectDelay) {
			return nil
		}
	}
}

func consume(ctx context.Context, conn net.Conn, emitter *outputEmitter, timeout time.Duration) error {
	reader := bufio.NewReaderSize(conn, MaxFrameBytes+1)
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-done:
		}
	}()
	seenHello := false
	healthDeadline := time.Now().Add(timeout)
	var lastSequence uint64
	var session string
	for {
		if err := conn.SetReadDeadline(healthDeadline); err != nil {
			return err
		}
		line, err := reader.ReadSlice('\n')
		if err != nil {
			var netError net.Error
			if errors.As(err, &netError) && netError.Timeout() {
				if !seenHello {
					return fmt.Errorf("runtime_observation_hello_timeout")
				}
				if encodeErr := emitter.emit(Output{Protocol: ProtocolVersion, Type: "client_status", Transport: "connected", ObserverHealth: "stale", Reason: "observer_health_timeout"}); encodeErr != nil {
					return encodeErr
				}
				healthDeadline = time.Now().Add(timeout)
				continue
			}
			if errors.Is(err, bufio.ErrBufferFull) {
				return fmt.Errorf("runtime_observation_frame_size")
			}
			return err
		}
		frame, err := DecodeFrame(line[:len(line)-1])
		if err != nil {
			return err
		}
		if !seenHello {
			if frame.Type != "hello" || frame.StreamStart != "late_join" || frame.AttributionBaseline != "unknown" {
				return fmt.Errorf("runtime_observation_invalid_hello")
			}
			seenHello, lastSequence, session = true, frame.Sequence, frame.MonitorSession
		} else {
			if frame.Sequence <= lastSequence {
				return fmt.Errorf("runtime_observation_sequence")
			}
			lastSequence = frame.Sequence
			if session == "" {
				session = frame.MonitorSession
			} else if frame.MonitorSession != "" && frame.MonitorSession != session {
				return fmt.Errorf("runtime_observation_session_changed")
			}
		}
		if encodeErr := emitter.emit(Output{Protocol: ProtocolVersion, Type: "server_frame", Transport: "connected", ObserverHealth: frame.ObserverHealth, Frame: &frame}); encodeErr != nil {
			return encodeErr
		}
		if frame.Type == "status" && frame.ObserverHealth == "healthy" {
			healthDeadline = time.Now().Add(timeout)
		}
	}
}
func wait(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
func stableReason(err error) string {
	if err == nil || errors.Is(err, io.EOF) {
		return "helper_disconnected"
	}
	var op *net.OpError
	if errors.As(err, &op) {
		return "helper_unavailable"
	}
	text := err.Error()
	switch {
	case strings.Contains(text, "unsafe_socket"):
		return "unsafe_socket"
	case strings.Contains(text, "untrusted_peer"):
		return "untrusted_peer"
	case strings.Contains(text, "frame_size"):
		return "frame_too_large"
	case strings.Contains(text, "protocol") || strings.Contains(text, "sequence") || strings.Contains(text, "session_changed") || strings.Contains(text, "invalid_hello"):
		return "protocol_error"
	default:
		return "runtime_observation_error"
	}
}
