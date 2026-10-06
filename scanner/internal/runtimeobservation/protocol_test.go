package runtimeobservation

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net"
	"strings"
	"testing"
	"time"
)

type shortWriter struct{}

func (shortWriter) Write(data []byte) (int, error) { return len(data) - 1, nil }

func mustEmitter(t *testing.T, writer *bytes.Buffer) *outputEmitter {
	t.Helper()
	value, err := newEmitter(context.Background(), writer)
	if err != nil {
		t.Fatal(err)
	}
	return value
}

func TestDecodeFrameRejectsVersionAndOversize(t *testing.T) {
	if _, err := DecodeFrame([]byte(`{"protocol":2,"type":"hello"}`)); err == nil {
		t.Fatal("accepted version")
	}
	if _, err := DecodeFrame(bytes.Repeat([]byte("x"), MaxFrameBytes+1)); err == nil {
		t.Fatal("accepted oversize")
	}
}

func TestEmitterRejectsShortWrite(t *testing.T) {
	emitter, err := newEmitter(context.Background(), shortWriter{})
	if err != nil {
		t.Fatal(err)
	}
	err = emitter.emit(Output{Protocol: ProtocolVersion, Type: "client_status"})
	if !errors.Is(err, ErrOutputFailure) {
		t.Fatalf("error=%v", err)
	}
}

func TestConsumeRequiresHelloAndIncreasingSequence(t *testing.T) {
	server, client := net.Pipe()
	defer server.Close()
	defer client.Close()
	var output bytes.Buffer
	done := make(chan error, 1)
	go func() { done <- consume(context.Background(), client, mustEmitter(t, &output), time.Second) }()
	frames := []string{
		`{"protocol":1,"type":"hello","sequence":4,"monitor_session":"s","stream_start":"late_join","attribution_baseline":"unknown"}`,
		`{"protocol":1,"type":"status","sequence":5,"monitor_session":"s","observer_health":"healthy"}`,
		`{"protocol":1,"type":"event","sequence":5,"monitor_session":"s"}`,
	}
	for _, frame := range frames {
		_, _ = server.Write([]byte(frame + "\n"))
	}
	if err := <-done; err == nil || !strings.Contains(err.Error(), "sequence") {
		t.Fatalf("error=%v", err)
	}
	if !strings.Contains(output.String(), `"transport":"connected"`) {
		t.Fatal(output.String())
	}
}

func TestConsumeRejectsSessionChange(t *testing.T) {
	server, client := net.Pipe()
	defer server.Close()
	defer client.Close()
	done := make(chan error, 1)
	go func() { done <- consume(context.Background(), client, mustEmitter(t, &bytes.Buffer{}), time.Second) }()
	_, _ = server.Write([]byte(`{"protocol":1,"type":"hello","sequence":1,"monitor_session":"a","stream_start":"late_join","attribution_baseline":"unknown"}` + "\n"))
	_, _ = server.Write([]byte(`{"protocol":1,"type":"status","sequence":2,"monitor_session":"b"}` + "\n"))
	if err := <-done; err == nil || !strings.Contains(err.Error(), "session_changed") {
		t.Fatalf("error=%v", err)
	}
}

func TestConsumeCancellationClosesRead(t *testing.T) {
	server, client := net.Pipe()
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- consume(ctx, client, mustEmitter(t, &bytes.Buffer{}), time.Hour) }()
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("consume leaked")
	}
}

func TestBusinessEventsDoNotMaskMissingHeartbeat(t *testing.T) {
	server, client := net.Pipe()
	var output bytes.Buffer
	done := make(chan error, 1)
	go func() {
		done <- consume(context.Background(), client, mustEmitter(t, &output), 30*time.Millisecond)
	}()
	_, _ = server.Write([]byte(`{"protocol":1,"type":"hello","sequence":1,"monitor_session":"s","stream_start":"late_join","attribution_baseline":"unknown"}` + "\n"))
	for sequence := 2; sequence < 12; sequence++ {
		_, _ = fmt.Fprintf(server, "{\"protocol\":1,\"type\":\"event\",\"sequence\":%d,\"monitor_session\":\"s\"}\n", sequence)
		time.Sleep(5 * time.Millisecond)
	}
	_ = server.Close()
	<-done
	if !strings.Contains(output.String(), "observer_health_timeout") {
		t.Fatal(output.String())
	}
}
