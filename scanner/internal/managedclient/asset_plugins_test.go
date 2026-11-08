package managedclient

import (
	"os"
	"path/filepath"
	"testing"
)

func TestComponentPathPreservesPackageBoundary(t *testing.T) {
	root := t.TempDir()
	inside := filepath.Join(root, "plugin.json")
	if err := os.WriteFile(inside, []byte(`{}`), 0600); err != nil {
		t.Fatal(err)
	}
	c := &assetCollector{result: &AssetInventory{}}
	resolved, err := filepath.EvalSymlinks(inside)
	if err != nil {
		t.Fatal(err)
	}
	if got := c.componentPath(root, "plugin.json"); got != resolved {
		t.Fatalf("existing component: %q", got)
	}
	if got := c.componentPath(root, ".absent/plugin.json"); got != "" || len(c.result.Issues) != 0 {
		t.Fatalf("missing candidate must remain silent: %q, %v", got, c.result.Issues)
	}
	outside := t.TempDir()
	if got := c.componentPath(root, outside); got != "" || len(c.result.Issues) != 1 || c.result.Issues[0].Code != "outside_package" {
		t.Fatalf("package escape accepted: %q, %v", got, c.result.Issues)
	}
	t.Run("symlink", func(t *testing.T) {
		if err := os.Symlink(outside, filepath.Join(root, "linked")); err != nil {
			t.Skipf("symlink unavailable: %v", err)
		}
		if got := c.componentPath(root, "linked"); got != "" {
			t.Fatalf("symlink escaped package: %q", got)
		}
	})
}

func BenchmarkMissingPluginManifest(b *testing.B) {
	root := b.TempDir()
	c := &assetCollector{result: &AssetInventory{}}
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		for _, candidate := range pluginManifests {
			c.componentPath(root, candidate.path)
		}
	}
}
