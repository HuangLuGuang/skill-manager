//go:build darwin

package runtimeobservation

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func fullOutputPipe(t *testing.T) (*os.File, *os.File, uintptr, int) {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { r.Close(); w.Close() })
	fd, err := prepareOutputFile(w)
	if err != nil {
		t.Fatal(err)
	}
	total := 0
	for {
		n, err := unix.Write(int(fd), bytes.Repeat([]byte{'p'}, 4096))
		if n > 0 {
			total += n
		}
		if err == unix.EAGAIN {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
	}
	return r, w, fd, total
}

func TestOutputBackpressureResumesPartialRecord(t *testing.T) {
	r, w, fd, filled := fullOutputPipe(t)
	if _, err := io.ReadFull(r, make([]byte, 512)); err != nil {
		t.Fatal(err)
	}
	record := []byte(`{"payload":"` + strings.Repeat("x", 1280) + "\"}\n")
	result := make(chan error, 1)
	go func() { result <- writeOutputFile(context.Background(), w, fd, record) }()
	select {
	case err := <-result:
		t.Fatalf("returned before consumer resumed: %v", err)
	case <-time.After(200 * time.Millisecond):
	}
	got := make([]byte, filled-512+len(record))
	if _, err := io.ReadFull(r, got); err != nil {
		t.Fatal(err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got[filled-512:], record) {
		t.Fatal("record truncated, duplicated, or reordered")
	}
}

func TestOutputBackpressureCancellation(t *testing.T) {
	_, w, _, _ := fullOutputPipe(t)
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	started := time.Now()
	err := Watch(ctx, w, WatchOptions{SocketPath: "/unused"})
	if !errors.Is(err, ErrOutputFailure) || !strings.Contains(err.Error(), "context deadline exceeded") || time.Since(started) > time.Second {
		t.Fatalf("err=%v elapsed=%s", err, time.Since(started))
	}
}

func TestOutputBackpressureDeadline(t *testing.T) {
	_, _, fd, _ := fullOutputPipe(t)
	started := time.Now()
	err := writeOutputUntil(context.Background(), fd, []byte("record\n"), started.Add(150*time.Millisecond))
	if err == nil || err.Error() != "runtime_observation_output_backpressure_timeout" || time.Since(started) > time.Second {
		t.Fatalf("err=%v elapsed=%s", err, time.Since(started))
	}
}

func TestOutputClosedReaderFails(t *testing.T) {
	r, w, fd, _ := fullOutputPipe(t)
	r.Close()
	if err := writeOutputFile(context.Background(), w, fd, []byte("record\n")); err != unix.EPIPE {
		t.Fatalf("error=%v", err)
	}
}
