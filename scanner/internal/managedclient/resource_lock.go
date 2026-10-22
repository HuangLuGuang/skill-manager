package managedclient

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type fileLockScope struct {
	home  string
	paths []string
}
type fileLockScopeKey struct{}

type fileLockConflict struct {
	Resource string
	Mode     string
}

func (e *fileLockConflict) Error() string { return ErrSkillActionBusy.Error() }
func (e *fileLockConflict) Unwrap() error { return ErrSkillActionBusy }

// Resolve existing ancestors as well as the leaf, so missing restore targets
// and aliases through symlinked parents share the same lock identity.
func lockPath(path string) string {
	path, _ = filepath.Abs(path)
	tail := []string{}
	for {
		if resolved, err := filepath.EvalSymlinks(path); err == nil {
			path = resolved
			break
		}
		parent := filepath.Dir(path)
		if parent == path {
			break
		}
		tail = append(tail, filepath.Base(path))
		path = parent
	}
	for i := len(tail) - 1; i >= 0; i-- {
		path = filepath.Join(path, tail[i])
	}
	if runtime.GOOS == "windows" {
		path = strings.ToLower(path)
	}
	return filepath.Clean(path)
}

func fileLockPaths(paths []string) []string {
	set := map[string]bool{}
	for _, path := range paths {
		if path == "" {
			continue
		}
		// Lock both the directory entry and its resolved contents.
		absolute, _ := filepath.Abs(path)
		entry := filepath.Join(lockPath(filepath.Dir(absolute)), filepath.Base(absolute))
		if runtime.GOOS == "windows" {
			entry = strings.ToLower(entry)
		}
		set[entry] = true
		set[lockPath(path)] = true
	}
	result := make([]string, 0, len(set))
	for path := range set {
		result = append(result, path)
	}
	sort.Strings(result)
	return result
}

func pathCovered(path string, roots []string) bool {
	for _, root := range roots {
		rel, err := filepath.Rel(root, path)
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return true
		}
	}
	return false
}

// Ancestors are shared locks; the resources themselves are exclusive. This
// permits sibling operations while preventing a parent removal during a copy.
func withFileLocks(ctx context.Context, home string, paths ...string) (context.Context, func(), error) {
	if err := ctx.Err(); err != nil {
		return ctx, nil, err
	}
	if ctx.Value(mutationLockContextKey{}) == canonicalExistingPath(home) {
		return ctx, func() {}, nil
	}
	roots := fileLockPaths(paths)
	if scope, ok := ctx.Value(fileLockScopeKey{}).(fileLockScope); ok && scope.home == lockPath(home) {
		additional := []string{}
		for _, root := range roots {
			if !pathCovered(root, scope.paths) {
				additional = append(additional, root)
			}
		}
		if len(additional) == 0 {
			return ctx, func() {}, nil
		}
		// Nested cleanup never waits while holding a different resource set.
		release, err := tryFileLocks(home, additional)
		if err != nil {
			return ctx, nil, err
		}
		if strings.Join(fileLockPaths(paths), "\x00") != strings.Join(roots, "\x00") {
			release()
			return ctx, nil, ErrSkillActionBusy
		}
		all := append(append([]string{}, scope.paths...), additional...)
		return context.WithValue(ctx, fileLockScopeKey{}, fileLockScope{scope.home, all}), release, nil
	}
	wait, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	var conflict error = ErrSkillActionBusy
	for {
		if err := ctx.Err(); err != nil {
			return ctx, nil, err
		}
		release, err := tryFileLocks(home, roots)
		if err == nil {
			current := fileLockPaths(paths)
			if strings.Join(current, "\x00") == strings.Join(roots, "\x00") {
				return context.WithValue(ctx, fileLockScopeKey{}, fileLockScope{lockPath(home), roots}), release, nil
			}
			release()
			roots = current
		} else if !errors.Is(err, ErrSkillActionBusy) {
			return ctx, nil, err
		} else {
			conflict = err
		}
		select {
		case <-wait.Done():
			if ctx.Err() != nil {
				return ctx, nil, ctx.Err()
			}
			return ctx, nil, conflict
		case <-time.After(25 * time.Millisecond):
		}
	}
}

func tryFileLocks(home string, roots []string) (func(), error) {
	directory := filepath.Join(home, ".agent-manager", "file-locks")
	if err := os.MkdirAll(directory, 0700); err != nil {
		return nil, err
	}
	files := []*os.File{}
	var once sync.Once
	release := func() {
		once.Do(func() {
			for i := len(files) - 1; i >= 0; i-- {
				_ = unlockClientFile(files[i])
				_ = files[i].Close()
			}
		})
	}
	acquire := func(path, resource string, shared bool) error {
		mode := "exclusive"
		if shared {
			mode = "shared"
		}
		file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
		if err != nil {
			return err
		}
		if shared {
			err = lockClientFileShared(file)
		} else {
			err = lockClientFile(file)
		}
		if err != nil {
			file.Close()
			if errors.Is(err, ErrAlreadyRunning) {
				return &fileLockConflict{Resource: resource, Mode: mode}
			}
			return err
		}
		files = append(files, file)
		if shared && filepath.Base(path) == "mutation.lock" {
			buf := make([]byte, 128)
			n, _ := file.ReadAt(buf, 0)
			if pid, e := strconv.Atoi(strings.TrimSpace(string(buf[:n]))); e == nil && pid > 0 && clientProcessAlive(pid) {
				return &fileLockConflict{Resource: resource, Mode: mode}
			}
		}
		return nil
	}
	// The existing lock remains an exclusive barrier for global/legacy operations.
	barrier := filepath.Join(home, ".agent-manager", "mutation.lock")
	if err := acquire(barrier, barrier, true); err != nil {
		release()
		return nil, err
	}
	modes := map[string]bool{}
	for _, root := range roots {
		modes[root] = false
		for parent := filepath.Dir(root); ; parent = filepath.Dir(parent) {
			if _, ok := modes[parent]; !ok {
				modes[parent] = true
			}
			if filepath.Dir(parent) == parent {
				break
			}
		}
	}
	keys := make([]string, 0, len(modes))
	for key := range modes {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		sum := sha256.Sum256([]byte(key))
		if err := acquire(filepath.Join(directory, fmt.Sprintf("%x.lock", sum)), key, modes[key]); err != nil {
			release()
			return nil, err
		}
	}
	return release, nil
}

// Upload coordination is separate from file locks: it never blocks another
// Skill's local filesystem operation and is released by the OS after a crash.
func submissionLock(ctx context.Context, home, identity string) (func(), error) {
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		release, err := trySubmissionLock(home, identity)
		if err == nil {
			return release, nil
		}
		if !errors.Is(err, ErrAlreadyRunning) {
			return nil, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(25 * time.Millisecond):
		}
	}
}

func trySubmissionLock(home, identity string) (func(), error) {
	sum := sha256.Sum256([]byte(identity))
	return acquireClientLock(home, fmt.Sprintf("submission-%x.lock", sum))
}
