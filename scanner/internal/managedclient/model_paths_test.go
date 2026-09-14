package managedclient

import (
	"os"
	"path/filepath"
	"testing"
)

func TestModelCustomRootWriteReadbackRestoreAndChangedRootConflict(t *testing.T) {
	home, root := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CODEX_HOME", root)
	before := []byte("model = \"previous\"\n")
	path := filepath.Join(root, "config.toml")
	if err := os.WriteFile(path, before, 0o600); err != nil {
		t.Fatal(err)
	}
	change, err := ApplyModelConfigRevision(home, "http://localhost:8001", "codex", "codex", "next", "test-key", "")
	if err != nil {
		t.Fatal(err)
	}
	state := InspectModelConfig(home, "codex")
	actual, _ := filepath.EvalSymlinks(path)
	if state.ConfigPath != actual || state.Model != "next" {
		t.Fatalf("wrong custom configuration: %+v", state)
	}
	t.Setenv("CODEX_HOME", t.TempDir())
	if err := RestoreModelConfig(home, change.ID); err == nil {
		t.Fatal("restore must reject changed configuration target")
	}
	t.Setenv("CODEX_HOME", root)
	if err := RestoreModelConfig(home, change.ID); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != string(before) {
		t.Fatal("original external configuration not restored")
	}
}

func TestModelExplicitHomeDoesNotFollowWorkingAgentEnvironment(t *testing.T) {
	testHome := t.TempDir()
	t.Setenv("CODEX_HOME", "/do-not-touch/working-agent")
	if err := ApplyModelConfig(testHome, "http://localhost:8001", "codex", "codex", "model", "test-key"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(testHome, ".codex", "config.toml")); err != nil {
		t.Fatal(err)
	}
}

func TestDesktopWindowsConfigurationDirectories(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"Claude-session", "Claude-3p-session"} {
		if err := os.Mkdir(filepath.Join(root, name), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	path, err := desktopWindowsPath(root, "Claude-3p/configLibrary/_meta.json")
	if err != nil || path != filepath.Join(root, "Claude-3p-session", "configLibrary", "_meta.json") {
		t.Fatalf("wrong 3p directory: %s %v", path, err)
	}
	if err := os.Mkdir(filepath.Join(root, "Claude-other"), 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := desktopWindowsPath(root, "Claude/claude_desktop_config.json"); err == nil {
		t.Fatal("ambiguous directories must not select an arbitrary installation")
	}
}
