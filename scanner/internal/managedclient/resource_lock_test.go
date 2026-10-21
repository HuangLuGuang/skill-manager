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

func TestResourceLocksPathsAndAliases(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, "skills")
	a, b := filepath.Join(root, "a"), filepath.Join(root, "b")
	if err := os.MkdirAll(a, 0700); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(home, "alias")
	if err := os.Symlink(a, alias); err != nil {
		t.Fatal(err)
	}
	_, release, err := withFileLocks(context.Background(), home, a)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	for _, path := range []string{a, alias, filepath.Join(alias, "missing"), root} {
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Millisecond)
		_, unlock, err := withFileLocks(ctx, home, path)
		cancel()
		if unlock != nil {
			unlock()
		}
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("conflicting %s: %v", path, err)
		}
	}
	_, other, err := withFileLocks(context.Background(), home, b)
	if err != nil {
		t.Fatal("independent sibling blocked", err)
	}
	other()
	if _, err := AcquireMutationLock(home); !errors.Is(err, ErrSkillActionBusy) {
		t.Fatalf("global barrier: %v", err)
	}
	release()
	release()
	_, next, err := withFileLocks(context.Background(), home, alias)
	if err != nil {
		t.Fatal(err)
	}
	defer next()
	release()
	if unlock, err := tryFileLocks(home, fileLockPaths([]string{a})); err == nil {
		unlock()
		t.Fatal("old cleanup unlocked new owner")
	}
}

func TestResourceConflictIdentifiesPhysicalPath(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, "skill")
	_, release, err := withFileLocks(context.Background(), home, path)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	_, err = tryFileLocks(home, fileLockPaths([]string{path}))
	var conflict *fileLockConflict
	if !errors.As(err, &conflict) || conflict.Resource != lockPath(path) || conflict.Mode != "exclusive" {
		t.Fatalf("wrong resource evidence: %#v %v", conflict, err)
	}
}

func TestAIDRLockIsReentrantAndIndependentOfSkillFiles(t *testing.T) {
	home := t.TempDir()
	ctx, release, err := AIDRMutationLock(context.Background(), home)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	_, nested, err := AIDRMutationLock(ctx, home)
	if err != nil {
		t.Fatal(err)
	}
	nested()
	if release, err := acquireClientLock(home, "aidr-mutation.lock"); err == nil {
		release()
		t.Fatal("nested call released outer AIDR lock")
	}
	_, files, err := withFileLocks(context.Background(), home, filepath.Join(home, "skill"))
	if err != nil {
		t.Fatal(err)
	}
	files()
}

func TestResourceLocksOppositeOrderAndCancellation(t *testing.T) {
	home := t.TempDir()
	a, b := filepath.Join(home, "a"), filepath.Join(home, "b")
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan error, 2)
	for _, paths := range [][]string{{a, b}, {b, a}} {
		go func(paths []string) {
			_, release, err := withFileLocks(ctx, home, paths...)
			if err == nil {
				time.Sleep(20 * time.Millisecond)
				release()
			}
			done <- err
		}(paths)
	}
	for i := 0; i < 2; i++ {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
}

func TestResourceLockProcessHelper(t *testing.T) {
	if os.Getenv("RESOURCE_LOCK_HELPER") != "1" {
		return
	}
	home := os.Getenv("RESOURCE_LOCK_HOME")
	if _, _, err := withFileLocks(context.Background(), home, filepath.Join(home, "skill")); err != nil {
		t.Fatal(err)
	}
	if _, err := submissionLock(context.Background(), home, "pending:test"); err != nil {
		t.Fatal(err)
	}
	fmt.Println("locked")
	for {
		time.Sleep(time.Second)
	}
}

func TestResourceLocksRecoverAfterProcessKill(t *testing.T) {
	home := t.TempDir()
	binary, _ := os.Executable()
	cmd := exec.Command(binary, "-test.run=^TestResourceLockProcessHelper$")
	cmd.Env = append(os.Environ(), "RESOURCE_LOCK_HELPER=1", "RESOURCE_LOCK_HOME="+home)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
	ready := make(chan string, 1)
	go func() { line, _ := bufio.NewReader(stdout).ReadString('\n'); ready <- line }()
	select {
	case line := <-ready:
		if line != "locked\n" {
			t.Fatal(line)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("helper timeout")
	}
	if unlock, err := tryFileLocks(home, fileLockPaths([]string{filepath.Join(home, "skill")})); err == nil {
		unlock()
		t.Fatal("cross-process lock bypassed")
	}
	if unlock, err := trySubmissionLock(home, "pending:test"); err == nil {
		unlock()
		t.Fatal("submission lock bypassed")
	}
	_ = cmd.Process.Kill()
	_ = cmd.Wait()
	_, release, err := withFileLocks(context.Background(), home, filepath.Join(home, "skill"))
	if err != nil {
		t.Fatal(err)
	}
	release()
	upload, err := trySubmissionLock(home, "pending:test")
	if err != nil {
		t.Fatal(err)
	}
	upload()
}
