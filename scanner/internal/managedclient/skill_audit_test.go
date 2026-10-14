package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestSkillAuditManagedAliasScope(t *testing.T) {
	home, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(RuntimeRoot(home), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	release := filepath.Join(ManagedSkillsRoot(home), "skill-1", "versions", "v1", "release")
	if err := os.MkdirAll(release, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(release, "SKILL.md"), []byte("hello"), 0644); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(home, "skills", "sample")
	os.MkdirAll(filepath.Dir(alias), 0755)
	if err := os.Symlink(release, alias); err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(alias, "SKILL.md")
	if _, err := ResolveAuditSkillPath(home, source); err == nil {
		t.Fatal("unregistered alias accepted")
	}
	if err := store.SaveInstall(Installation{AgentType: "workbuddy", SkillID: "skill-1", SkillName: "sample", TargetPath: alias, Manifest: releaseManifest{VersionID: "v1"}}); err != nil {
		t.Fatal(err)
	}
	got, err := ResolveAuditSkillPath(home, source)
	if err != nil || got != filepath.Join(release, "SKILL.md") {
		t.Fatalf("managed alias: %s %v", got, err)
	}
	policy := agentlog.DefaultSkillAuditPolicy()
	observer := agentlog.NewSkillObserver()
	observer.ResolvePath = func(path string) (string, error) { return ResolveAuditSkillPath(home, path) }
	use := &agentlog.SkillUse{Behavior: "file_access", Path: filepath.ToSlash(source), Basis: "literal_cat"}
	observer.Observe(context.Background(), use, &agentlog.AuditPolicy{SkillAudit: &policy})
	if use.Digest == "" || use.Path != filepath.ToSlash(source) {
		t.Fatalf("observation: %+v", use)
	}
	outside := filepath.Join(home, "outside")
	os.MkdirAll(outside, 0755)
	os.WriteFile(filepath.Join(outside, "SKILL.md"), []byte("other"), 0644)
	os.Remove(alias)
	os.Symlink(outside, alias)
	if _, err := ResolveAuditSkillPath(home, source); err == nil {
		t.Fatal("redirected installation accepted")
	}
	os.Remove(alias)
	os.Symlink(release, alias)
	os.Remove(filepath.Join(release, "SKILL.md"))
	os.Symlink(filepath.Join(outside, "SKILL.md"), filepath.Join(release, "SKILL.md"))
	if _, err := ResolveAuditSkillPath(home, source); err == nil {
		t.Fatal("file symlink accepted")
	}
}

func TestSkillObservationFreshPolicyReceiptAndRoot(t *testing.T) {
	home, _ := filepath.EvalSymlinks(t.TempDir())
	root := filepath.Join(home, "skills")
	os.MkdirAll(filepath.Join(root, "sample"), 0755)
	source := filepath.Join(root, "sample", "SKILL.md")
	os.WriteFile(source, []byte("hello"), 0644)
	policy := agentlog.DefaultSkillAuditPolicy()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/clients/device/tasks/42/skill-observation" {
			t.Errorf("unexpected request %s", r.URL.Path)
		}
		json.NewEncoder(w).Encode(map[string]any{"skill": agentlog.SkillUse{Behavior: "file_access", Path: filepath.ToSlash(source), Basis: "literal_cat"}, "local_agent_id": "local", "agent_type": "workbuddy", "audit_policy": policy, "audit_policy_version": "7"})
	}))
	defer server.Close()
	api := API{server: server.URL, http: server.Client()}
	inventory := Inventory{ClientID: "device", Agents: []Agent{{LocalAgentID: "local", AgentType: "workbuddy", SkillsPath: root}}}
	task := Task{ID: 42, Payload: map[string]any{}}
	if err := executeSkillObservation(context.Background(), home, inventory, api, task); err != nil {
		t.Fatal(err)
	}
	receipt := task.Payload["skill_observation"].(map[string]any)
	skill := receipt["skill"].(agentlog.SkillUse)
	if skill.Digest == "" || skill.ContentStatus != "computed" || receipt["policy_version"] != "7" {
		t.Fatalf("receipt: %#v", receipt)
	}
	inventory.Agents[0].SkillsPath = filepath.Join(home, "other")
	if err := executeSkillObservation(context.Background(), home, inventory, api, task); err == nil {
		t.Fatal("outside source root accepted")
	}
}
