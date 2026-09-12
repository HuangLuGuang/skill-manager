package managedclient

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func sharedLinksFixture(t *testing.T) (string, *Store, Inventory, Skill, string) {
	t.Helper()
	home, store, inventory, skill := observedFixture(t)
	external := filepath.Join(t.TempDir(), "external-skill")
	if err := os.Rename(skill.Path, external); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(external, skill.Path); err != nil {
		t.Fatal(err)
	}
	alias := skill
	alias.Path = filepath.Join(home, ".claude", "skills", "sample")
	if err := os.MkdirAll(filepath.Dir(alias.Path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(external, alias.Path); err != nil {
		t.Fatal(err)
	}
	inventory.Agents = append(inventory.Agents, Agent{AgentType: "claude-code", SkillManagementSupported: true, SkillsPath: filepath.Dir(alias.Path), Skills: []Skill{alias}})
	return home, store, inventory, skill, external
}

func TestAutomaticSharedLinksKeepOneCopyAndRestoreEachPath(t *testing.T) {
	for _, action := range []string{"quarantine", "uninstall"} {
		t.Run(action, func(t *testing.T) {
			home, store, inventory, skill, external := sharedLinksFixture(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch {
				case strings.HasSuffix(r.URL.Path, "/policy"):
					json.NewEncoder(w).Encode(Policy{Classification: DefaultClassificationPolicy()})
				case strings.HasSuffix(r.URL.Path, "/compare"):
					items := []CompareItem{}
					for _, agent := range inventory.Agents {
						for _, local := range agent.Skills {
							items = append(items, CompareItem{AgentType: agent.AgentType, LocalPath: local.Path, LocalSignature: local.Signature})
						}
					}
					json.NewEncoder(w).Encode(map[string]any{"items": items})
				default:
					w.Write([]byte(`{}`))
				}
			}))
			defer server.Close()
			api := NewAPI(server.URL, "token", time.Second)
			value := SkillObservation{Action: action, Trigger: "malicious", Signature: skill.Signature}
			ids, err := applyAutomaticObservedAction(context.Background(), home, inventory, inventory.Agents[0], skill, canonicalSkillRoot(external), Policy{}, api, store, &value)
			if err != nil {
				t.Fatal(err)
			}
			if len(ids) != 2 || ids[skill.Path] == ids[inventory.Agents[1].Skills[0].Path] {
				t.Fatal(ids)
			}
			items, err := store.QuarantineItems()
			if err != nil || len(items) != 2 {
				t.Fatal(items, err)
			}
			if items[0].QuarantinePath != items[1].QuarantinePath {
				t.Fatal("duplicated retained content", items)
			}
			for i, agent := range inventory.Agents {
				path := agent.Skills[0].Path
				if _, err := os.Lstat(path); !os.IsNotExist(err) {
					t.Fatal("reader remains active", path, err)
				}
				task := Task{ID: int64(71 + i), TaskType: "skill_action", Payload: map[string]any{"action": "restore_quarantine", "agent_type": agent.AgentType, "path": path, "expected_signature": skill.Signature, "quarantine_id": ids[path]}}
				if err := restoreQuarantineTask(context.Background(), home, inventory, agent, api, store, task); err != nil {
					t.Fatal(err)
				}
				if err := checkObservedContent(Skill{Path: path, Signature: skill.Signature}); err != nil {
					t.Fatal(err)
				}
			}
			if err := checkObservedContent(Skill{Path: external, Signature: skill.Signature}); err != nil {
				t.Fatal("external source changed", err)
			}
		})
	}
}

func TestDiscardSharedRecoveryPreservesOtherReaderCopy(t *testing.T) {
	home, store, inventory, skill, _ := sharedLinksFixture(t)
	value := SkillObservation{Action: "quarantine", Trigger: "unverified"}
	ids, err := applyAutomaticObservedAction(context.Background(), home, inventory, inventory.Agents[0], skill, canonicalSkillRoot(skill.Path), Policy{}, API{}, store, &value)
	if err != nil {
		t.Fatal(err)
	}
	pending, err := QueueQuarantineForDetection(home, store, ids[skill.Path])
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.DiscardPending(pending.ID); err != nil {
		t.Fatal(err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].Signature != skill.Signature {
		t.Fatal("other recovery lost", items, err)
	}
}

func TestSharedRootAliasesRemoveEachLinkEntryOnce(t *testing.T) {
	home, store, inventory, skill, external := sharedLinksFixture(t)
	rootAlias := filepath.Join(home, "custom-skills")
	if err := os.Symlink(filepath.Dir(skill.Path), rootAlias); err != nil {
		t.Fatal(err)
	}
	alias := skill
	alias.Path = filepath.Join(rootAlias, filepath.Base(skill.Path))
	inventory.Agents = append(inventory.Agents, Agent{AgentType: "custom", SkillsPath: rootAlias, SkillManagementSupported: true, Skills: []Skill{alias}})
	value := SkillObservation{Action: "quarantine", Trigger: "unverified"}
	ids, err := applyAutomaticObservedAction(context.Background(), home, inventory, inventory.Agents[0], skill, canonicalSkillRoot(external), Policy{}, API{}, store, &value)
	if err != nil {
		t.Fatal(err)
	}
	if len(ids) != 3 || ids[skill.Path] != ids[alias.Path] {
		t.Fatal("root aliases did not share recovery", ids)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 2 {
		t.Fatal("duplicate recovery for same link entry", items, err)
	}
	for _, agent := range inventory.Agents {
		for _, local := range agent.Skills {
			if _, err := os.Lstat(local.Path); !os.IsNotExist(err) {
				t.Fatal("link remains", local.Path, err)
			}
		}
	}
	if err := checkObservedContent(Skill{Path: external, Signature: skill.Signature}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Readlink(rootAlias); err != nil {
		t.Fatal("root alias was removed", err)
	}
}

func TestSharedLinkPatrolPinsReadersBeforeEventDelivery(t *testing.T) {
	for _, changed := range []bool{false, true} {
		t.Run(fmt.Sprint(changed), func(t *testing.T) {
			home, store, inventory, skill, external := sharedLinksFixture(t)
			alias := inventory.Agents[1].Skills[0].Path
			replacement := filepath.Join(t.TempDir(), "replacement")
			if err := copyDir(external, replacement); err != nil {
				t.Fatal(err)
			}
			changedOnce := false
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasSuffix(r.URL.Path, "/events") && changed && !changedOnce {
					changedOnce = true
					if err := os.Remove(alias); err != nil {
						t.Error(err)
					}
					if err := os.Symlink(replacement, alias); err != nil {
						t.Error(err)
					}
				}
				w.Write([]byte(`{"items":[]}`))
			}))
			defer server.Close()
			policy := Policy{Classification: DefaultClassificationPolicy()}
			policy.Classification.Rules["unverified"] = "quarantine"
			err := patrolClassified(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, true)
			if changed {
				if err == nil {
					t.Fatal("accepted changed sharing scope")
				}
				for _, path := range []string{skill.Path, alias, external, replacement} {
					if err := checkObservedContent(Skill{Path: path, Signature: skill.Signature}); err != nil {
						t.Fatal("content lost", path, err)
					}
				}
				items, _ := store.QuarantineItems()
				if len(items) != 0 {
					t.Fatal("partial quarantine before preflight", items)
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				ids := map[string]bool{}
				for _, path := range []string{skill.Path, alias} {
					value, err := store.Observation(path)
					if err != nil || value.ActionStatus != "completed" || value.QuarantineID == "" {
						t.Fatal(value, err)
					}
					ids[value.QuarantineID] = true
					if _, err := os.Lstat(path); !os.IsNotExist(err) {
						t.Fatal("reader not isolated", path, err)
					}
				}
				if len(ids) != 2 {
					t.Fatal("recovery destinations collapsed", ids)
				}
			}
		})
	}
}
