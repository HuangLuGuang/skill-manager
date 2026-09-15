package managedclient

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestFastPatrolQuarantinesTrustedChangeAndPublishesLocalState(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	if err := store.SaveInstall(Installation{
		AgentType: "codex", SkillID: "skill-1", SkillName: skill.Name, TargetPath: skill.Path,
		Manifest: releaseManifest{SkillID: "skill-1", VersionID: "version-1", ContentSignature: skill.Signature},
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.SaveObservation(skill.Path, SkillObservation{
		Signature: skill.Signature, TrustedSignature: skill.Signature, TrustedSkillID: "skill-1",
		TrustedVersionID: "version-1", Certification: "certified",
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInventory(inventory); err != nil {
		t.Fatal(err)
	}
	changedFile := filepath.Join(skill.Path, "SKILL.md")
	if err := os.WriteFile(changedFile, []byte("---\nname: sample\n---\nchanged"), 0o600); err != nil {
		t.Fatal(err)
	}
	physicalBefore := canonicalSkillRoot(skill.Path)
	policy := Policy{Classification: DefaultClassificationPolicy()}
	policy.Classification.Rules["trusted_content_changed"] = "quarantine"
	handled, roots, err := fastPatrolTrustedChanges(context.Background(), home, inventory, policy, API{}, store, []string{changedFile})
	if err != nil || !handled {
		t.Fatalf("trusted change did not use fast patrol: handled=%v err=%v", handled, err)
	}
	if len(roots) != 1 || filepath.Clean(roots[0]) != physicalBefore {
		t.Fatalf("fast patrol did not return its self-change suppression root: %#v", roots)
	}
	if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
		t.Fatalf("changed Skill was not quarantined: %v", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 {
		t.Fatalf("quarantine evidence missing: %#v %v", items, err)
	}
	if _, err := os.Stat(UIStateSignalPath(home)); err != nil {
		t.Fatalf("desktop state signal missing: %v", err)
	}
	body, ok, err := store.State("inventory")
	if err != nil || !ok {
		t.Fatal(err)
	}
	var cached Inventory
	if err := json.Unmarshal([]byte(body), &cached); err != nil {
		t.Fatal(err)
	}
	if len(cached.Agents) != 1 || len(cached.Agents[0].Skills) != 0 {
		t.Fatalf("cached inventory still exposes the quarantined Skill: %#v", cached.Agents)
	}
}

func TestFastPatrolFallsBackForUnmanagedChange(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	policy := Policy{Classification: DefaultClassificationPolicy()}
	policy.Classification.Rules["trusted_content_changed"] = "quarantine"
	handled, _, err := fastPatrolTrustedChanges(context.Background(), home, inventory, policy, API{}, store, []string{filepath.Join(skill.Path, "SKILL.md")})
	if err != nil || handled {
		t.Fatalf("unmanaged change bypassed complete discovery: handled=%v err=%v", handled, err)
	}
}
