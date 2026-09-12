package managedclient

import (
	"os"
	"path/filepath"
	"testing"
)

func TestConnectionResetPreservesCopiesAndDefaultsToRecord(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	if err := store.SaveObservation(skill.Path, SkillObservation{Signature: skill.Signature, TrustedSignature: skill.Signature, TrustedVersionID: "old-version", Certification: "certified"}); err != nil {
		t.Fatal(err)
	}
	item, err := quarantineSkill(home, store, inventory.Agents[0].AgentType, skill.Name, skill.Path, "old-policy", skill.Signature)
	if err != nil {
		t.Fatal(err)
	}
	backup := filepath.Join(BackupsRoot(home), "before-upgrade", "SKILL.md")
	if err := os.MkdirAll(filepath.Dir(backup), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(backup, []byte("retained backup"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := store.ResetForConnectionChange(); err != nil {
		t.Fatal(err)
	}
	policy := cachedPolicy(store)
	if !classificationEnabled(policy) {
		t.Fatal("classified default missing", policy)
	}
	for trigger, action := range policy.Classification.Rules {
		if action != "record" {
			t.Fatal("connection reset enables file remediation", trigger, action)
		}
	}
	observation, err := store.Observation(skill.Path)
	if err != nil || observation.TrustedSignature != "" || observation.TrustedVersionID != "" {
		t.Fatal("old trust survived", observation, err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].ID != item.ID {
		t.Fatal("recovery record lost", items, err)
	}
	if err := checkObservedContent(Skill{Path: item.QuarantinePath, Signature: skill.Signature}); err != nil {
		t.Fatal("recovery copy changed", err)
	}
	if content, err := os.ReadFile(backup); err != nil || string(content) != "retained backup" {
		t.Fatal("backup changed", err)
	}
}
