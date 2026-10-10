//go:build darwin

package runtimeobservation

import (
	"context"
	"errors"
	"io"
	"os"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

func prepareOutputFile(file *os.File) (uintptr, error) {
	descriptor := file.Fd()
	return descriptor, syscall.SetNonblock(int(descriptor), true)
}
func writeOutputFile(ctx context.Context, _ *os.File, descriptor uintptr, data []byte) error {
	return writeOutputUntil(ctx, descriptor, data, time.Now().Add(30*time.Second))
}

// Keep only the current record while waiting for the native reader. The deadline
// bounds a stalled consumer; cancellation remains responsive even with a full pipe.
func writeOutputUntil(ctx context.Context, descriptor uintptr, data []byte, deadline time.Time) error {
	for len(data) > 0 {
		if err := ctx.Err(); err != nil {
			return err
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return errors.New("runtime_observation_output_backpressure_timeout")
		}
		n, err := syscall.Write(int(descriptor), data)
		if n > 0 {
			data = data[n:]
		}
		if err == syscall.EINTR {
			continue
		}
		if err == syscall.EAGAIN {
			waitMS := min(100, max(1, int(remaining.Milliseconds())))
			_, pollErr := unix.Poll([]unix.PollFd{{Fd: int32(descriptor), Events: unix.POLLOUT}}, waitMS)
			if pollErr != nil && pollErr != syscall.EINTR {
				return pollErr
			}
			continue
		}
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
	}
	return nil
}
