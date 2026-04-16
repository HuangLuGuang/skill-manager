package discovery

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFindDiscoversSkillsAndSkipsIgnoredDirs(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "safe", "SKILL.md"), "---\nname: safe\n---\n")
	mustWrite(t, filepath.Join(root, "node_modules", "bad", "SKILL.md"), "---\nname: ignored\n---\n")

	skills, err := Find(root, map[string]bool{"node_modules": true})
	if err != nil {
		t.Fatal(err)
	}
	if len(skills) != 1 {
		t.Fatalf("expected 1 skill, got %d", len(skills))
	}
	if filepath.Base(skills[0].Path) != "safe" {
		t.Fatalf("unexpected skill path: %s", skills[0].Path)
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
