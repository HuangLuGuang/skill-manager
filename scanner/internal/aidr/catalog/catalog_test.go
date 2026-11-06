package catalog

import (
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

func TestRelativeLogRootsUsesPlatformOverride(t *testing.T) {
	p := Product{Roots: []string{"default"}, RootsByOS: map[string][]string{runtime.GOOS: {"native/path"}}}
	if !reflect.DeepEqual(RelativeLogRoots(p), []string{"native/path"}) {
		t.Fatal(RelativeLogRoots(p))
	}
	delete(p.RootsByOS, runtime.GOOS)
	if !reflect.DeepEqual(RelativeLogRoots(p), p.Roots) {
		t.Fatal(RelativeLogRoots(p))
	}
}

func TestWindowsProductRootsAndCapabilities(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("native Windows paths")
	}
	home := t.TempDir()
	want := map[string]string{"claude": ".claude/projects", "codex": ".codex/sessions", "workbuddy": ".workbuddy/projects", "codebuddy": "AppData/Local/CodeBuddyExtension/Data", "trae": "AppData/Roaming/Trae/logs", "trae-cn": "AppData/Roaming/Trae CN/logs", "qwenwork": ".qwenworkcn/projects", "zcode": ".zcode/cli/db", "qoder-cli": ".qoder/projects"}
	for id, relative := range want {
		p, _ := Get(id)
		roots := LogRoots(id, home)
		if !SupportedOS(p) || !SupportedLogOS(p) || len(roots) == 0 || roots[0] != filepath.Join(home, relative) {
			t.Fatal(id, roots)
		}
		if id != "qoder-cli" && (!SupportedHookOS(p) || !p.Block || !p.Approval) {
			t.Fatal("missing Hook control", id)
		}
	}
	p, _ := Get("qoder-hooks")
	if !SupportedHookOS(p) || !p.Block || !p.Approval {
		t.Fatal(p)
	}
}
