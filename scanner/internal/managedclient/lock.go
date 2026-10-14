package managedclient

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

var ErrAlreadyRunning = errors.New("Agent Manager Client 已在运行")
var ErrSkillActionBusy = errors.New("skill_action_busy")

type mutationLockContextKey struct{}

// Synchronous repair calls made by patrol share its already-held file lock.
func withMutationLock(ctx context.Context, home string) (context.Context, func(), error) {
	key := canonicalExistingPath(home)
	if ctx.Value(mutationLockContextKey{}) == key {
		return ctx, func() {}, nil
	}
	release, err := AcquireMutationLock(home)
	if err != nil {
		return ctx, nil, err
	}
	return context.WithValue(ctx, mutationLockContextKey{}, key), release, nil
}

func AcquireRunLock(home string) (func(), error) {
	return acquireClientLock(home, "client.lock")
}

func AcquireMutationLock(home string) (func(), error) {
	release, err := acquireClientLock(home, "mutation.lock")
	if errors.Is(err, ErrAlreadyRunning) {
		return nil, ErrSkillActionBusy
	}
	return release, err
}

// AcquireMutationLockWithTimeout gives short interactive operations a chance to
// run after a background mutation finishes, while preserving the same exclusive
// file-operation boundary.
func AcquireMutationLockWithTimeout(home string, timeout time.Duration) (func(), error) {
	deadline := time.Now().Add(timeout)
	for {
		release, err := AcquireMutationLock(home)
		if !errors.Is(err, ErrSkillActionBusy) || timeout <= 0 {
			return release, err
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return nil, ErrSkillActionBusy
		}
		pause := 100 * time.Millisecond
		if remaining < pause {
			pause = remaining
		}
		time.Sleep(pause)
	}
}

func acquireClientLock(home, name string) (func(), error) {
	root := filepath.Join(home, ".agent-manager")
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(root, name)
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err = lockClientFile(file); err != nil {
		file.Close()
		return nil, err
	}
	var once sync.Once
	// Keep the inode: unlinking a locked file lets another process lock a new one.
	release := func() { once.Do(func() { _ = unlockClientFile(file); _ = file.Close() }) }
	buf := make([]byte, 128)
	n, _ := file.ReadAt(buf, 0)
	// Older clients only wrote a PID and never took an OS lock. Wait for that
	// owner to exit before migrating; timestamps cannot prove process death.
	if pid, e := strconv.Atoi(strings.TrimSpace(string(buf[:n]))); e == nil && pid > 0 && clientProcessAlive(pid) {
		release()
		return nil, ErrAlreadyRunning
	}
	if err = file.Truncate(0); err == nil {
		_, err = file.WriteAt([]byte(fmt.Sprintf("v2 %d\n", os.Getpid())), 0)
	}
	if err != nil {
		release()
		return nil, err
	}
	return release, nil
}

func RequestFullScan(home string) error {
	path := filepath.Join(home, ".agent-manager", "run-now")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, []byte("full"), 0o600)
}

func RequestWorkerWake(home string) error {
	path := filepath.Join(home, ".agent-manager", "worker-wake")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return atomicWriteFile(path, []byte("wake"), 0o600)
}

func WaitForRun(home string, interval time.Duration, idle func()) bool {
	return WaitForRunOrChange(home, interval, idle, nil)
}

func WaitForRunOrChange(home string, interval time.Duration, idle func(), changes <-chan struct{}) bool {
	return WaitForRunOrChangeContext(context.Background(), home, interval, idle, changes)
}

func WaitForRunOrChangeContext(ctx context.Context, home string, interval time.Duration, idle func(), changes <-chan struct{}) bool {
	deadline := time.NewTimer(interval)
	ticker := time.NewTicker(time.Second)
	defer deadline.Stop()
	defer ticker.Stop()
	trigger := filepath.Join(home, ".agent-manager", "run-now")
	for {
		select {
		case <-ctx.Done():
			return false
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
