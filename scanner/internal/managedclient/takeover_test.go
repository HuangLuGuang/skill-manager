package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/manifest"
)

func TestApplyTakeoverManagesAllowedAndMovesDenied(t *testing.T) {
	home := t.TempDir()
	allowed := filepath.Join(home, ".codex", "skills", "allowed")
	denied := filepath.Join(home, ".codex", "skills", "denied")
	writeSkill(t, allowed, "allowed")
	writeSkill(t, denied, "denied")
	allowedManifest, err := manifest.Build(allowed, DefaultManifestOptions())
	if err != nil {
		t.Fatal(err)
	}
	plan := TakeoverPlan{Items: []TakeoverItem{
		{AgentType: "codex", Name: "allowed", Source: allowed, SkillID: "skill-1", ManagedAgentID: "codex-agent", Signature: manifest.ContentSignature(allowedManifest.Files), Action: "manage"},
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

func TestRecordTakeoverRejectsContentChangedAfterComparison(t *testing.T) {
	home := t.TempDir()
	first := filepath.Join(home, ".codex", "skills", "first")
	second := filepath.Join(home, ".codex", "skills", "second")
	writeSkill(t, first, "first")
	writeSkill(t, second, "second")
	firstManifest, err := manifest.Build(first, DefaultManifestOptions())
	if err != nil {
		t.Fatal(err)
	}
	secondManifest, err := manifest.Build(second, DefaultManifestOptions())
	if err != nil {
		t.Fatal(err)
	}
	plan := TakeoverPlan{Items: []TakeoverItem{
		{AgentType: "codex", Name: "first", Source: first, SkillID: "skill-1", Signature: manifest.ContentSignature(firstManifest.Files), Action: "manage"},
		{AgentType: "codex", Name: "second", Source: second, SkillID: "skill-2", Signature: manifest.ContentSignature(secondManifest.Files), Action: "manage"},
	}}
	if _, err := ApplyTakeover(home, &plan); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(ManagedSkillsRoot(home), "skill-2", "release", "SKILL.md"), []byte("---\nname: changed\n---\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := RecordTakeover(home, plan, store); err == nil || !strings.Contains(err.Error(), "changed after platform verification") {
		t.Fatalf("expected post-comparison change to be rejected, got %v", err)
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 0 {
		t.Fatalf("failed takeover left partial registrations: %#v %v", installs, err)
	}
	if enabled, err := store.GovernanceEnabled(); err != nil || enabled {
		t.Fatalf("failed takeover enabled governance: %v %v", enabled, err)
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
		AgentType: "codex", Name: "safe", LocalPath: "/skills/safe", LocalSignature: "sig", Allowed: true,
		SkillID: "skill-1", VersionID: "version-2",
	}})
	if len(plan.Items) != 1 || plan.Items[0].Action != "managed" || plan.Items[0].Reason != "already_managed" {
		t.Fatalf("existing install would be taken over again: %#v", plan.Items)
	}
	if _, err := ApplyTakeover(t.TempDir(), &plan); err != nil {
		t.Fatalf("already managed item should be a no-op: %v", err)
	}
}

func TestPlatformInstallRemainsManagedAfterTakeoverAndFullPatrol(t *testing.T) {
	home := t.TempDir()
	familyID := "family-1"
	versionID := "version-2"
	release := filepath.Join(ManagedSkillsRoot(home), familyID, "versions", versionID, "release")
	content := []byte("---\nname: safe\n---\n")
	if err := os.MkdirAll(release, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(release, "SKILL.md"), content, 0o644); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(home, ".codex", "skills", "safe")
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(release, target); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(content)
	manifest := releaseManifest{
		Version: 2, SkillID: familyID, VersionID: versionID, Name: "safe", ContentSignature: "sig",
		Files: []releaseFile{{Path: "SKILL.md", Size: int64(len(content)), SHA256: hex.EncodeToString(sum[:])}},
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SaveInstall(Installation{
		AgentType: "codex", SkillID: familyID, SkillName: "safe", TargetPath: target, Manifest: manifest,
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	inventory := Inventory{ClientID: "host", Agents: []Agent{{
		AgentType: "codex", SkillManagementSupported: true,
		Skills: []Skill{{SkillID: familyID, VersionID: versionID, Name: "safe", Path: target, Signature: "sig", Status: "managed"}},
	}}}
	plan := BuildTakeoverPlan(inventory, []CompareItem{{
		AgentType: "codex", Name: "safe", LocalPath: target, LocalSignature: "sig", Allowed: true,
		SkillID: familyID, VersionID: versionID,
	}})
	if len(plan.Items) != 1 || plan.Items[0].Action != "managed" {
		t.Fatalf("platform install would be taken over again: %#v", plan.Items)
	}
	if _, err := ApplyTakeover(home, &plan); err != nil {
		t.Fatal(err)
	}
	if err := RecordTakeover(home, plan, store); err != nil {
		t.Fatal(err)
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 1 || installs[0].SkillID != familyID || installs[0].Manifest.VersionID != versionID {
		t.Fatalf("platform installation identity changed: %#v %v", installs, err)
	}
	api := NewAPI("http://127.0.0.1:1", "token", 20*time.Millisecond)
	if err := patrolLocalChanges(context.Background(), home, inventory, Policy{Mode: "block"}, api, store, installs, true); err != nil {
		t.Fatal(err)
	}
	if quarantined, err := store.QuarantineItems(); err != nil || len(quarantined) != 0 {
		t.Fatalf("unchanged platform install was quarantined: %#v %v", quarantined, err)
	}
	if _, err := os.Stat(filepath.Join(target, "SKILL.md")); err != nil {
		t.Fatalf("platform install disappeared after patrol: %v", err)
	}
}
