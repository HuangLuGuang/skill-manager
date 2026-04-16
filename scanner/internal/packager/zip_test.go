package packager

import (
	"archive/zip"
	"os"
	"path/filepath"
	"testing"

	"skill-manager/scanner/internal/manifest"
)

func TestCreateZip(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "---\nname: demo\n---\n")
	mustWrite(t, filepath.Join(root, "scripts", "run.py"), "print('ok')\n")
	m, err := manifest.Build(root, manifest.Options{MaxFileBytes: 1024, MaxTotalBytes: 4096, MaxFiles: 10})
	if err != nil {
		t.Fatal(err)
	}

	zipPath := filepath.Join(t.TempDir(), "skill.zip")
	if err := CreateZip(root, m, zipPath); err != nil {
		t.Fatal(err)
	}

	reader, err := zip.OpenReader(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	names := map[string]bool{}
	for _, file := range reader.File {
		names[file.Name] = true
	}
	if !names["SKILL.md"] || !names["scripts/run.py"] {
		t.Fatalf("zip missing expected files: %#v", names)
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
