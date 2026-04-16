package precheck

import (
	"os"
	"path/filepath"
	"testing"

	"skill-manager/scanner/internal/manifest"
)

func TestRunFindsSuspiciousPatterns(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "---\nname: bad\n---\n")
	mustWrite(t, filepath.Join(root, "analyze.py"), "import os\napi_key = os.getenv('API_KEY')\nresult = eval('1+1')\n")

	m, err := manifest.Build(root, manifest.Options{MaxFileBytes: 1024, MaxTotalBytes: 4096, MaxFiles: 10})
	if err != nil {
		t.Fatal(err)
	}
	findings := Run(root, m)
	if len(findings) < 2 {
		t.Fatalf("expected at least 2 findings, got %d", len(findings))
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
