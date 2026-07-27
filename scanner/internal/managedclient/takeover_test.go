package managedclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestApplyTakeoverManagesAllowedAndMovesDenied(t *testing.T) {
	home := t.TempDir()
	allowed := filepath.Join(home, ".codex", "skills", "allowed")
	denied := filepath.Join(home, ".codex", "skills", "denied")
	writeSkill(t, allowed, "allowed")
	writeSkill(t, denied, "denied")
	plan := TakeoverPlan{Items: []TakeoverItem{
		{AgentType: "codex", Name: "allowed", Source: allowed, SkillID: "skill-1", ManagedAgentID: "codex-agent", Signature: "abc", Action: "manage"},
		{AgentType: "codex", Name: "denied", Source: denied, Action: "pending", Reason: "skill_not_approved"},
	}}

	backup, err := ApplyTakeover(home, &plan)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(backup, "codex", "allowed", "SKILL.md")); err != nil {
		t.Fatal("allowed skill was not backed up:", err)
	}
	if _, err := os.Stat(filepath.Join(ManagedSkillsRoot(home), "skill-1", "release", "SKILL.md")); err != nil {
		t.Fatal("allowed skill was not stored:", err)
	}
	if _, err := os.Stat(filepath.Join(PendingRoot(home), "codex", "denied", "SKILL.md")); err != nil {
		t.Fatal("denied skill was not moved to pending:", err)
	}
	if _, err := os.Stat(filepath.Join(denied, "SKILL.md")); !os.IsNotExist(err) {
		t.Fatal("denied skill is still visible to the agent")
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := RecordTakeover(home, plan, store); err != nil {
		t.Fatal(err)
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 1 || installs[0].ManagedAgentID != "codex-agent" {
		t.Fatalf("takeover install was not recorded: %#v %v", installs, err)
	}
	if !verifyManagedInstall(home, installs[0]) {
		t.Fatal("newly taken-over Skill was immediately treated as modified")
	}
	pending, err := store.PendingItems()
	if err != nil || len(pending) != 1 || pending[0].OriginalPath != denied || pending[0].Status != "pending" {
		t.Fatalf("pending skill was not recorded: %#v %v", pending, err)
	}
	status, err := store.LocalStatus()
	if err != nil || status.PendingSkills != 1 {
		t.Fatalf("pending skill was not included in local status: %#v %v", status, err)
	}
}

func TestPendingItemsFindsLegacyPendingDirectory(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, ".agent-manager", "pending", "codex", "legacy")
	writeSkill(t, path, "legacy")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	items, err := store.PendingItems()
	if err != nil || len(items) != 1 || items[0].PendingPath != path || items[0].Reason != "legacy_pending" {
		t.Fatalf("legacy pending skill was not discovered: %#v %v", items, err)
	}
}

func TestApplyTakeoverReplacesSymlinkWithoutChangingSharedSource(t *testing.T) {
	home := t.TempDir()
	shared := filepath.Join(home, ".cc-switch", "skills", "shared")
	writeSkill(t, shared, "shared")
	source := filepath.Join(home, ".codex", "skills", "shared")
	if err := os.MkdirAll(filepath.Dir(source), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(shared, source); err != nil {
		t.Fatal(err)
	}
	plan := TakeoverPlan{Items: []TakeoverItem{{
		AgentType: "codex", Name: "shared", Source: source, SourceTarget: shared,
		SkillID: "skill-1", Signature: "abc", Action: "manage",
	}}}
	backup, err := ApplyTakeover(home, &plan)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(shared, "SKILL.md")); err != nil {
		t.Fatal("shared source was changed:", err)
	}
	if target, err := filepath.EvalSymlinks(source); err != nil || target == shared {
		t.Fatalf("agent entry was not replaced with managed storage: %q %v", target, err)
	}
	if _, err := os.Stat(filepath.Join(backup, "codex", "shared", "SKILL.md")); err != nil {
		t.Fatal("symlinked skill was not backed up:", err)
	}
}

func TestApplyTakeoverMaterializesPendingSymlink(t *testing.T) {
	home := t.TempDir()
	shared := filepath.Join(home, ".cc-switch", "skills", "shared")
	writeSkill(t, shared, "shared")
	source := filepath.Join(home, ".codex", "skills", "shared")
	if err := os.MkdirAll(filepath.Dir(source), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(shared, source); err != nil {
		t.Fatal(err)
	}
	plan := TakeoverPlan{Items: []TakeoverItem{{
		AgentType: "codex", Name: "shared", Source: source, Action: "pending", Reason: "skill_not_found",
	}}}
	if _, err := ApplyTakeover(home, &plan); err != nil {
		t.Fatal(err)
	}
	pending := plan.Items[0].PendingPath
	if info, err := os.Lstat(pending); err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("pending skill was not materialized: %v %v", info, err)
	}
	if _, err := os.Stat(filepath.Join(pending, "SKILL.md")); err != nil {
		t.Fatal("pending skill content is missing:", err)
	}
	if _, err := os.Lstat(source); !os.IsNotExist(err) {
		t.Fatal("agent symlink is still present")
	}
}

func TestApplyTakeoverRestoresProcessedSkillsWhenLaterItemFails(t *testing.T) {
	home := t.TempDir()
	allowed := filepath.Join(home, ".codex", "skills", "allowed")
	writeSkill(t, allowed, "allowed")
	plan := TakeoverPlan{Items: []TakeoverItem{
		{AgentType: "codex", Name: "allowed", Source: allowed, SkillID: "skill-1", Signature: "abc", Action: "manage"},
		{AgentType: "codex", Name: "missing", Source: filepath.Join(home, "missing"), Action: "pending"},
	}}
	if _, err := ApplyTakeover(home, &plan); err == nil {
		t.Fatal("expected takeover failure")
	}
	body, err := os.ReadFile(filepath.Join(allowed, "SKILL.md"))
	if err != nil || !strings.Contains(string(body), "name: allowed") {
		t.Fatalf("processed skill was not restored: %q %v", body, err)
	}
}

func TestBuildTakeoverPlanKeepsSameNameSkillsDistinct(t *testing.T) {
	inventory := Inventory{Agents: []Agent{{
		AgentType:                "codex",
		SkillManagementSupported: true,
		Skills: []Skill{
			{Name: "same", Path: "/skills/first", Signature: "sig-1"},
			{Name: "same", Path: "/skills/second", Signature: "sig-2"},
		},
	}}}
	plan := BuildTakeoverPlan(inventory, []CompareItem{
		{AgentType: "codex", Name: "same", LocalPath: "/skills/second", LocalSignature: "sig-2", Allowed: true, SkillID: "skill-2"},
		{AgentType: "codex", Name: "same", LocalPath: "/skills/first", LocalSignature: "sig-1", Allowed: false, SkillID: "skill-1", Reason: "signature_mismatch"},
	})
	if len(plan.Items) != 2 {
		t.Fatalf("unexpected plan: %#v", plan)
	}
	if plan.Items[0].Action != "pending" || plan.Items[0].SkillID != "skill-1" {
		t.Fatalf("first same-name skill was mixed up: %#v", plan.Items[0])
	}
	if plan.Items[1].Action != "manage" || plan.Items[1].SkillID != "skill-2" {
		t.Fatalf("second same-name skill was mixed up: %#v", plan.Items[1])
	}
}

func TestBuildTakeoverPlanMarksExistingInstallAsManaged(t *testing.T) {
	inventory := Inventory{Agents: []Agent{{
		AgentType:                "codex",
		SkillManagementSupported: true,
		Skills: []Skill{{
			SkillID: "skill-1", Name: "safe", Path: "/skills/safe", Signature: "sig", Status: "managed",
		}},
	}}}
	plan := BuildTakeoverPlan(inventory, []CompareItem{{
		AgentType: "codex", Name: "safe", LocalPath: "/skills/safe", LocalSignature: "sig", Allowed: true, SkillID: "skill-1",
	}})
	if len(plan.Items) != 1 || plan.Items[0].Action != "managed" || plan.Items[0].Reason != "already_managed" {
		t.Fatalf("existing install would be taken over again: %#v", plan.Items)
	}
	if _, err := ApplyTakeover(t.TempDir(), &plan); err != nil {
		t.Fatalf("already managed item should be a no-op: %v", err)
	}
}
