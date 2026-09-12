package managedclient

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestRemovalTaskUsesContentBindingAndKeepsRecovery(t *testing.T) {
	for _, legacy := range []bool{false, true} {
		t.Run(map[bool]string{false: "content_bound", true: "legacy_install_manifest"}[legacy], func(t *testing.T) {
			home, store, inventory, skill := observedFixture(t)
			if err := store.SaveInstall(Installation{AgentType: "codex", SkillID: "family", SkillName: skill.Name, TargetPath: skill.Path, Manifest: releaseManifest{ContentSignature: skill.Signature}}); err != nil {
				t.Fatal(err)
			}
			task := Task{ID: 74, TaskType: "remove_skill", Payload: map[string]any{"agent_type": "codex", "skill_id": "family", "skill_name": "unrelated-name"}}
			if !legacy {
				task.Payload["path"] = skill.Path
				task.Payload["expected_signature"] = skill.Signature
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{}`)) }))
			defer server.Close()
			api := NewAPI(server.URL, "token", time.Second)
			edit := filepath.Join(skill.Path, "user-edit.txt")
			if err := os.WriteFile(edit, []byte("keep this"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := executeTask(context.Background(), home, inventory, Policy{}, api, store, task); err == nil {
				t.Fatal("stale removal changed edited content")
			}
			if body, err := os.ReadFile(edit); err != nil || string(body) != "keep this" {
				t.Fatal("user edit lost", err)
			}
			if err := os.Remove(edit); err != nil {
				t.Fatal(err)
			}
			for retry := 0; retry < 2; retry++ {
				if err := executeTask(context.Background(), home, inventory, Policy{}, api, store, task); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
				t.Fatal("active copy remains", err)
			}
			copies, err := store.QuarantineItems()
			if err != nil || len(copies) != 1 || copies[0].Status != "uninstalled" {
				t.Fatal("recovery record missing or duplicated", copies, err)
			}
			if err := checkObservedContent(Skill{Path: copies[0].QuarantinePath, Signature: skill.Signature}); err != nil {
				t.Fatal("recovery content changed", err)
			}
		})
	}
}
