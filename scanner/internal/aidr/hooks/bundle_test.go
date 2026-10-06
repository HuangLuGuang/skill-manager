package hooks

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestBundledSourceMatchesDeclaredResourcesAndRejectsTampering(t *testing.T) {
	var files map[string]string
	if e := json.Unmarshal(bundledPlugins, &files); e != nil {
		t.Fatal(e)
	}
	if len(files) != 6 {
		t.Fatal("unexpected packaged resource count")
	}
	for name, expected := range files {
		body, e := os.ReadFile(filepath.Join("../../../../client/aidr-plugins", name))
		if e != nil || string(body) != expected {
			t.Fatalf("embedded resource differs from desktop declaration: %s", name)
		}
	}
	root := t.TempDir()
	first, e := BundledSource(root)
	if e != nil {
		t.Fatal(e)
	}
	again, e := BundledSource(root)
	if e != nil || first != again {
		t.Fatal("repeat changed source", e)
	}
	if e := os.WriteFile(filepath.Join(first, "aidr-claude/scripts/bridge.sh"), []byte("tampered"), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e := BundledSource(root); e == nil {
		t.Fatal("modified bundle accepted")
	}
}
