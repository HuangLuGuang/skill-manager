package managedclient

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestClientLockProcessHelper(t *testing.T) {
	if os.Getenv("CLIENT_LOCK_HELPER") != "1" {
		return
	}
	_, err := acquireClientLock(os.Getenv("CLIENT_LOCK_HOME"), os.Getenv("CLIENT_LOCK_NAME"))
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("locked")
	for {
		time.Sleep(time.Second)
	}
}

func TestClientLocksRecoverImmediatelyAfterProcessDeath(t *testing.T) {
	for _, name := range []string{"client.lock", "mutation.lock", "service-reconcile.lock"} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			binary, _ := os.Executable()
			cmd := exec.Command(binary, "-test.run=^TestClientLockProcessHelper$")
			cmd.Env = append(os.Environ(), "CLIENT_LOCK_HELPER=1", "CLIENT_LOCK_HOME="+home, "CLIENT_LOCK_NAME="+name)
			stdout, err := cmd.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			if err = cmd.Start(); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
			ready := make(chan string, 1)
			go func() { line, _ := bufio.NewReader(stdout).ReadString('\n'); ready <- line }()
			select {
			case line := <-ready:
				if line != "locked\n" {
					t.Fatal(line)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("lock helper did not start")
			}
			path := filepath.Join(RuntimeRoot(home), name)
			old := time.Now().Add(-24 * time.Hour)
			if err = os.Chtimes(path, old, old); err != nil {
				t.Fatal(err)
			}
			if _, err = acquireClientLock(home, name); !errors.Is(err, ErrAlreadyRunning) {
				t.Fatalf("live old lock stolen: %v", err)
			}
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
			release, err := acquireClientLock(home, name)
			if err != nil {
				t.Fatalf("crashed owner left lock blocked: %v", err)
			}
			release()
			if _, err = os.Stat(path); err != nil {
				t.Fatal("lock inode removed", err)
			}
			next, err := acquireClientLock(home, name)
			if err != nil {
				t.Fatal(err)
			}
			defer next()
			release() // An old owner's repeated cleanup cannot unlock the new owner.
			if _, err = acquireClientLock(home, name); !errors.Is(err, ErrAlreadyRunning) {
				t.Fatal("old cleanup unlocked new owner", err)
			}
		})
	}
}

func TestLegacyClientLockRespectsLivePID(t *testing.T) {
	home := t.TempDir()
	_ = os.MkdirAll(RuntimeRoot(home), 0700)
	path := filepath.Join(RuntimeRoot(home), "client.lock")
	_ = os.WriteFile(path, []byte(fmt.Sprintf("%d\n", os.Getpid())), 0600)
	old := time.Now().Add(-24 * time.Hour)
	_ = os.Chtimes(path, old, old)
	if _, err := AcquireRunLock(home); !errors.Is(err, ErrAlreadyRunning) {
		t.Fatal("legacy owner bypassed", err)
	}
}

func TestRunLockPreventsConcurrentClient(t *testing.T) {
	home := t.TempDir()
	release, err := AcquireRunLock(home)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	if _, err := AcquireRunLock(home); err == nil {
		t.Fatal("second client acquired the same run lock")
	}
}

func TestWaitForRunStopsWhenServiceContextIsCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	started := time.Now()
	if WaitForRunOrChangeContext(ctx, t.TempDir(), time.Minute, nil, nil) {
		t.Fatal("cancelled service wait requested a full scan")
	}
	if time.Since(started) > time.Second {
		t.Fatal("cancelled service did not stop promptly")
	}
}

func TestFullScanRequestWakesBackgroundRun(t *testing.T) {
	home := t.TempDir()
	if err := RequestFullScan(home); err != nil {
		t.Fatal(err)
	}
	if !WaitForRun(home, 3*time.Second, nil) {
		t.Fatal("full scan request was downgraded to a light patrol")
	}
}
