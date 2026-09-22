package managedclient

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestPatrolArchivesPermittedUnverifiedIsolation(t *testing.T) {
	for _, test := range []struct {
		name, reason, action, status string
		changed                      bool
		resolve                      bool
	}{
		{"same-copy", "unverified", "record_only", "quarantined", false, true},
		{"recreated-copy", "unverified", "record", "quarantined", true, true},
		{"manual", "manual", "record_only", "quarantined", false, false},
		{"still-isolating", "unverified", "quarantine", "quarantined", false, false},
		{"backup", "unverified", "record_only", "backed_up", false, false},
		{"failed-isolation", "unverified", "record_only", "quarantine_failed", false, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			home := t.TempDir()
			store, err := OpenStore(filepath.Join(RuntimeRoot(home), "client.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			target := filepath.Join(home, ".codex", "skills", "demo")
			writeSkill(t, target, "demo")
			item, err := QuarantineSkill(home, store, "codex", "demo", target, test.reason)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := store.db.Exec(`UPDATE client_quarantine SET status=? WHERE id=?`, test.status, item.ID); err != nil {
				t.Fatal(err)
			}
			if err := copyDir(item.QuarantinePath, target); err != nil {
				t.Fatal(err)
			}
			if test.changed {
				previous, err := inspectInstallTarget(target)
				if err != nil {
					t.Fatal(err)
				}
				if err := store.SaveObservation(target, SkillObservation{Signature: previous.signature}); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(target, "new.txt"), []byte("new version"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			state, err := inspectInstallTarget(target)
			if err != nil {
				t.Fatal(err)
			}
			// Same-name records for another path and Agent remain independent.
			for _, extra := range []struct{ id, agent, path string }{
				{"other-agent", "hermes", target},
				{"other-path", "codex", filepath.Join(home, "other", "demo")},
			} {
				_, err := store.db.Exec(`INSERT INTO client_quarantine(id,agent_type,skill_name,original_path,quarantine_path,reason,status,created_at) VALUES(?,?,?,?,?,'unverified','quarantined','now')`, extra.id, extra.agent, "demo", extra.path, item.QuarantinePath)
				if err != nil {
					t.Fatal(err)
				}
			}
			policy := Policy{Classification: DefaultClassificationPolicy()}
			policy.Classification.Rules["unverified"] = test.action
			skill := Skill{Name: "demo", Path: target, Signature: state.signature}
			inventory := Inventory{ClientID: "client", Agents: []Agent{{AgentType: "codex", SkillsPath: filepath.Dir(target), SkillManagementSupported: true, Skills: []Skill{skill}}}}
			if err := patrolClassified(context.Background(), home, inventory, policy, API{}, store, false); err != nil {
				t.Fatal(err)
			}
			var status string
			if err := store.db.QueryRow(`SELECT status FROM client_quarantine WHERE id=?`, item.ID).Scan(&status); err != nil {
				t.Fatal(err)
			}
			if (status == "resolved") != test.resolve {
				t.Fatalf("status=%s resolve=%v", status, test.resolve)
			}
			if _, err := os.Stat(filepath.Join(item.QuarantinePath, "SKILL.md")); err != nil {
				t.Fatal("historical evidence removed", err)
			}
			var untouched int
			if err := store.db.QueryRow(`SELECT COUNT(*) FROM client_quarantine WHERE id IN ('other-agent','other-path') AND status='quarantined'`).Scan(&untouched); err != nil || untouched != 2 {
				t.Fatal("unrelated rows changed", untouched, err)
			}
			if test.resolve {
				items, err := store.QuarantineItems()
				if err != nil {
					t.Fatal(err)
				}
				for _, active := range items {
					if active.ID == item.ID {
						t.Fatal("resolved record is still visible")
					}
				}
				if _, event, err := store.LatestUIEvent(); err != nil || event != "local_state_changed" {
					t.Fatal("missing UI invalidation", event, err)
				}
				if err := checkObservedContent(skill); err != nil {
					t.Fatal("live content changed", err)
				}
			}
		})
	}
}

func TestPermittedCopyResolutionRequiresFreshContent(t *testing.T) {
	for _, missing := range []bool{false, true} {
		home := t.TempDir()
		store, err := OpenStore(filepath.Join(RuntimeRoot(home), "client.db"))
		if err != nil {
			t.Fatal(err)
		}
		target := filepath.Join(home, "skills", "demo")
		writeSkill(t, target, "demo")
		state, err := inspectInstallTarget(target)
		if err != nil {
			t.Fatal(err)
		}
		item, err := QuarantineSkill(home, store, "codex", "demo", target, "unverified")
		if err != nil {
			t.Fatal(err)
		}
		if !missing {
			writeSkill(t, target, "different")
		}
		policy := Policy{Classification: DefaultClassificationPolicy()}
		observation := SkillObservation{Signature: state.signature, Trigger: "unverified", Action: "record", ActionStatus: "completed"}
		if err := store.resolvePermittedUnverifiedCopy(context.Background(), home, "codex", Skill{Name: "demo", Path: target}, policy, observation); err == nil {
			t.Fatal("stale or missing path was accepted")
		}
		var status string
		if err := store.db.QueryRow(`SELECT status FROM client_quarantine WHERE id=?`, item.ID).Scan(&status); err != nil || status != "quarantined" {
			t.Fatal(status, err)
		}
		store.Close()
	}
}
