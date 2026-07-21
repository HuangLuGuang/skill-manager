package manifest

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBuildManifest(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "---\nname: demo\ndescription: Demo skill\n---\n")
	mustWrite(t, filepath.Join(root, "scripts", "run.py"), "print('ok')\n")

	m, err := Build(root, Options{MaxFileBytes: 1024, MaxTotalBytes: 4096, MaxFiles: 10})
	if err != nil {
		t.Fatal(err)
	}
	if m.Name != "demo" {
		t.Fatalf("unexpected name: %s", m.Name)
	}
	if m.Description != "Demo skill" {
		t.Fatalf("unexpected description: %s", m.Description)
	}
	if len(m.Files) != 2 {
		t.Fatalf("expected 2 files, got %d", len(m.Files))
	}
	if m.Fingerprint == "" || m.Fingerprint[:7] != "sha256:" {
		t.Fatalf("unexpected fingerprint: %s", m.Fingerprint)
	}
}

func TestBuildRejectsLargeFile(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "---\nname: demo\n---\n")
	mustWrite(t, filepath.Join(root, "large.txt"), "123456")

	_, err := Build(root, Options{MaxFileBytes: 3, MaxTotalBytes: 4096, MaxFiles: 10})
	if err == nil {
		t.Fatal("expected large file error")
	}
}

func TestBuildRejectsTooManyFilesWithChineseMessage(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "---\nname: demo\n---\n")
	mustWrite(t, filepath.Join(root, "extra.txt"), "extra")

	_, err := Build(root, Options{MaxFileBytes: 1024, MaxTotalBytes: 4096, MaxFiles: 1})
	if err == nil || !strings.Contains(err.Error(), "当前至少 2 个，最多允许 1 个") {
		t.Fatalf("unexpected file count error: %v", err)
	}
}

func mustWrite(t *testing.T, path string, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}
