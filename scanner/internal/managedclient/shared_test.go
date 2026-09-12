package managedclient

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestSharedReadersAreScopedToEachSkill(t *testing.T) {
	home := t.TempDir()
	shared, private, alias := filepath.Join(home, "shared"), filepath.Join(home, "private"), filepath.Join(home, "alias")
	writeSkill(t, filepath.Join(shared, "common"), "common")
	writeSkill(t, filepath.Join(private, "mine"), "mine")
	if err := os.Symlink(shared, alias); err != nil {
		t.Fatal(err)
	}
	inventory := Inventory{Agents: []Agent{
		{AgentType: "codex", SkillsPath: private, Capabilities: map[string]any{"skill_roots": []string{private, shared}}, Skills: []Skill{{Path: filepath.Join(private, "mine")}, {Path: filepath.Join(shared, "common")}}},
		{AgentType: "hermes", SkillsPath: alias, Capabilities: map[string]any{}, Skills: []Skill{{Path: filepath.Join(alias, "common")}}},
	}}
	annotateDiscoverySharing(&inventory, Config{})
	paths := inventory.Agents[0].Capabilities["shared_skill_readers_by_path"].(map[string][]string)
	if len(paths[filepath.Join(private, "mine")]) != 0 {
		t.Fatal("private Skill labeled shared", paths)
	}
	if !reflect.DeepEqual(paths[filepath.Join(shared, "common")], []string{"codex", "hermes"}) {
		t.Fatal("shared readers missing", paths)
	}
	roots := inventory.Agents[1].Capabilities["shared_skill_readers_by_root"].(map[string][]string)
	if !reflect.DeepEqual(roots[alias], []string{"codex", "hermes"}) {
		t.Fatal("recovery root lost shared readers", roots)
	}
}

func TestSharedAliasesQuarantineOnceEvenAfterSourceDisappears(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	alias := filepath.Join(home, "alias-skills")
	if err := os.Symlink(filepath.Dir(skill.Path), alias); err != nil {
		t.Fatal(err)
	}
	other := skill
	other.Path = filepath.Join(alias, filepath.Base(skill.Path))
	inventory.Agents = append(inventory.Agents, Agent{AgentType: "hermes", SkillsPath: alias, SkillManagementSupported: true, Skills: []Skill{other}})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{}`)) }))
	defer server.Close()
	policy := Policy{Classification: DefaultClassificationPolicy()}
	policy.Classification.Rules["unverified"] = "quarantine"
	if err := patrolClassified(context.Background(), home, inventory, policy, NewAPI(server.URL, "test", time.Second), store, false); err != nil {
		t.Fatal("same content handled again after its real path disappeared", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 {
		t.Fatal("duplicate quarantine", items, err)
	}
	if err := checkObservedContent(Skill{Path: items[0].QuarantinePath, Signature: skill.Signature}); err != nil {
		t.Fatal(err)
	}
}
