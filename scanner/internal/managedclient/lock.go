package managedclient

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

var ErrAlreadyRunning = errors.New("Agent Manager Client 已在运行")

func AcquireRunLock(home string) (func(), error) {
	root := filepath.Join(home, ".agent-manager")
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(root, "client.lock")
	for attempt := 0; attempt < 2; attempt++ {
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err == nil {
			_, _ = fmt.Fprintf(file, "%d\n", os.Getpid())
			_ = file.Close()
			stop := make(chan struct{})
			go func() {
				ticker := time.NewTicker(time.Minute)
				defer ticker.Stop()
				for {
					select {
					case <-ticker.C:
						now := time.Now()
						_ = os.Chtimes(path, now, now)
					case <-stop:
						return
					}
				}
			}()
			return func() { close(stop); _ = os.Remove(path) }, nil
		}
		info, statErr := os.Stat(path)
		if statErr == nil && time.Since(info.ModTime()) > 10*time.Minute {
			_ = os.Remove(path)
			continue
		}
		return nil, ErrAlreadyRunning
	}
	return nil, fmt.Errorf("无法获取客户端运行锁")
}

func RequestFullScan(home string) error {
	path := filepath.Join(home, ".agent-manager", "run-now")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, []byte("full"), 0o600)
}

func WaitForRun(home string, interval time.Duration, idle func()) bool {
	return WaitForRunOrChange(home, interval, idle, nil)
}

func WaitForRunOrChange(home string, interval time.Duration, idle func(), changes <-chan struct{}) bool {
	deadline := time.NewTimer(interval)
	ticker := time.NewTicker(time.Second)
	defer deadline.Stop()
	defer ticker.Stop()
	trigger := filepath.Join(home, ".agent-manager", "run-now")
	for {
		select {
		case <-changes:
			return true
		case <-deadline.C:
			return false
		case <-ticker.C:
			mode, err := os.ReadFile(trigger)
			if err == nil && os.Remove(trigger) == nil {
				return string(mode) == "full"
			}
			if idle != nil {
				idle()
			}
		}
	}
}
