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

func TestBuildIgnoresConfiguredFileAndDirectoryNames(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "---\nname: demo\n---\n")
	mustWrite(t, filepath.Join(root, ".DS_Store"), "macOS metadata")
	mustWrite(t, filepath.Join(root, "nested", ".DS_Store"), "nested metadata")
	mustWrite(t, filepath.Join(root, "build", "generated.txt"), "generated")

	m, err := Build(root, Options{
		IgnoreDirs: map[string]bool{".DS_Store": true, "build": true},
		MaxFiles:   1,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(m.Files) != 1 || m.Files[0].Path != "SKILL.md" {
		t.Fatalf("ignored metadata changed the manifest: %#v", m.Files)
	}
}

func TestContentSignatureNormalizesLegacyZipMojibakePaths(t *testing.T) {
	normalRoot := t.TempDir()
	mojibakeRoot := t.TempDir()
	mustWrite(t, filepath.Join(normalRoot, "SKILL.md"), "---\nname: demo\n---\n")
	mustWrite(t, filepath.Join(mojibakeRoot, "SKILL.md"), "---\nname: demo\n---\n")
	mustWrite(t, filepath.Join(normalRoot, "references", "常用查询模板.md"), "select 1")
	mustWrite(t, filepath.Join(mojibakeRoot, "references", "σ╕╕τö¿µƒÑΦ»óµ¿íµ¥┐.md"), "select 1")

	normal, err := Build(normalRoot, Options{})
	if err != nil {
		t.Fatal(err)
	}
	mojibake, err := Build(mojibakeRoot, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if ContentSignature(normal.Files) != ContentSignature(mojibake.Files) {
		t.Fatalf("legacy ZIP path encoding changed the content signature: %#v %#v", normal.Files, mojibake.Files)
	}
	if mojibake.Files[1].Path != "references/σ╕╕τö¿µƒÑΦ»óµ¿íµ¥┐.md" {
		t.Fatalf("canonical signature path replaced the physical package path: %#v", mojibake.Files)
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
