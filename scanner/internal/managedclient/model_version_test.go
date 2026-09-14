package managedclient

import (
	"os"
	"path/filepath"
	"testing"
)

func TestHermesVersionUsesInstalledMetadataWithoutExecutingCLI(t *testing.T) {
	root := t.TempDir()
	binary := filepath.Join(root, "venv", "bin", "hermes")
	metadata := filepath.Join(root, "hermes_cli", "__init__.py")
	for _, file := range []string{binary, metadata} {
		if err := os.MkdirAll(filepath.Dir(file), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(binary, []byte("this file cannot execute"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(metadata, []byte("__version__ = \"0.17.0\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := discoverModelVersion(t.TempDir(), "hermes", binary); got != "0.17.0" {
		t.Fatalf("installed version not discovered: %q", got)
	}
	if err := os.WriteFile(metadata, []byte("__version__ = \"0.18.0\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := discoverModelVersion(t.TempDir(), "hermes", binary); got != "0.18.0" {
		t.Fatalf("package upgrade was hidden by executable cache: %q", got)
	}
}
