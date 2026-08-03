package managedclient

import (
	"context"
	"testing"
	"time"
)

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
