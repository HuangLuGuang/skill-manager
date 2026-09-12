package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestLegacyPatrolKeepsEditsMadeDuringPlatformComparison(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInstall(Installation{AgentType: "codex", SkillID: "sample", SkillName: skill.Name, TargetPath: skill.Path, Manifest: releaseManifest{ContentSignature: skill.Signature}}); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/compare") {
			if err := os.WriteFile(filepath.Join(skill.Path, "SKILL.md"), []byte("edited while waiting"), 0600); err != nil {
				t.Error(err)
			}
			json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{AgentType: "codex", Name: skill.Name, LocalPath: skill.Path, LocalSignature: skill.Signature, Reason: "skill_not_approved"}}})
			return
		}
		w.Write([]byte(`{"ok":true}`))
	}))
	defer server.Close()
	err := patrol(context.Background(), home, inventory, Policy{Mode: "block"}, NewAPI(server.URL, "test", time.Second), store, true, true)
	if err == nil || err.Error() != "skill_content_changed" {
		t.Fatalf("expected content conflict, got %v", err)
	}
	content, err := os.ReadFile(filepath.Join(skill.Path, "SKILL.md"))
	if err != nil || string(content) != "edited while waiting" {
		t.Fatalf("edit lost: %q %v", content, err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 0 {
		t.Fatalf("unexpected quarantine: %v %v", items, err)
	}
}

func TestPatrolSnapshotKeepsMissingAndRepointedTargetsBound(t *testing.T) {
	home := t.TempDir()
	link := filepath.Join(home, "skill")
	ctx, err := withPatrolSnapshot(context.Background(), []Installation{{TargetPath: link}})
	if err != nil {
		t.Fatal(err)
	}
	writeSkill(t, link, "new-skill")
	if err := checkPatrolSnapshot(ctx, link); err == nil {
		t.Fatal("new target accepted")
	}
	other := filepath.Join(home, "other")
	if err := os.Rename(link, other); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(other, link); err != nil {
		t.Fatal(err)
	}
	ctx, err = withPatrolSnapshot(context.Background(), []Installation{{TargetPath: link}})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(link); err != nil {
		t.Fatal(err)
	}
	writeSkill(t, link, "new-skill")
	if err := checkPatrolSnapshot(ctx, link); err == nil {
		t.Fatal("replaced link accepted")
	}
}
