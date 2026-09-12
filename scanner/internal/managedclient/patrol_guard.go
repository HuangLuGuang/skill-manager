package managedclient

import (
	"context"
	"os"
	"path/filepath"
)

type patrolSnapshotKey struct{}

type patrolSnapshot struct {
	paths  map[string]bool
	states map[string]installTargetState
}

func withPatrolSnapshot(ctx context.Context, installs []Installation) (context.Context, error) {
	if ctx.Value(patrolSnapshotKey{}) != nil {
		return ctx, nil
	}
	snapshot := patrolSnapshot{paths: map[string]bool{}, states: map[string]installTargetState{}}
	for _, install := range installs {
		path := filepath.Clean(install.TargetPath)
		snapshot.paths[path] = true
		if resolved, err := filepath.EvalSymlinks(path); err == nil {
			snapshot.paths[filepath.Clean(resolved)] = true
		}
	}
	for path := range snapshot.paths {
		state, err := inspectInstallTarget(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return ctx, err
		}
		snapshot.states[path] = state
	}
	return context.WithValue(ctx, patrolSnapshotKey{}, snapshot), nil
}

func checkPatrolSnapshot(ctx context.Context, path string) error {
	snapshot, ok := ctx.Value(patrolSnapshotKey{}).(patrolSnapshot)
	path = filepath.Clean(path)
	if !ok || !snapshot.paths[path] {
		return nil
	}
	return checkInstallTarget(path, snapshot.states)
}
