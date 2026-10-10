//go:build darwin

package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestSystemCandidateNeverExecutesScript(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "codex")
	marker := filepath.Join(dir, "executed")
	if err := os.WriteFile(path, []byte("#!/bin/sh\ntouch "+marker), 0700); err != nil {
		t.Fatal(err)
	}
	item, ok := inspectSystemCandidate(context.Background(), path, "common_path")
	if !ok || item.Availability != "not_native" {
		t.Fatalf("unexpected candidate: %+v", item)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("discovery executed customer code")
	}
}

func TestSystemCandidateResolvesLinksAndDetectsChanges(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "codex")
	link := filepath.Join(dir, "alias")
	if err := os.WriteFile(path, []byte("first"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	a, ok := inspectSystemCandidate(context.Background(), link, "common_path")
	real, _ := filepath.EvalSymlinks(path)
	if !ok || a.Path != real {
		t.Fatalf("unresolved candidate: %+v", a)
	}
	if err := os.WriteFile(path, []byte("replacement program"), 0700); err != nil {
		t.Fatal(err)
	}
	b, _ := inspectSystemCandidate(context.Background(), link, "common_path")
	if a.ID == b.ID {
		t.Fatal("changed program kept identity")
	}
}

func TestSystemCandidateDoesNotDiscoverUnrelatedBinaries(t *testing.T) {
	if _, ok := inspectSystemCandidate(context.Background(), "/usr/bin/true", "running"); ok {
		t.Fatal("unrelated process discovered")
	}
	item, ok := inspectSystemCandidate(context.Background(), "/usr/bin/true", "custom")
	if !ok || item.Product != "custom" || item.Availability != "available" {
		t.Fatalf("explicit signed program unavailable: %+v", item)
	}
}
