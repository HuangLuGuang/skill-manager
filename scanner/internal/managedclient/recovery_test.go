package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestQuarantineRecoveryRechecksPolicyAndContent(t *testing.T) {
	for _, scenario := range []struct {
		name, action, fault, wantError string
		malicious                      bool
		legacyMode                     string
		certified                      bool
		backup                         bool
	}{
		{name: "record", action: "record"},
		{name: "backup_replace", action: "record", backup: true},
		{name: "backup_target_changed", action: "record", backup: true, fault: "backup_changed", wantError: "skill_content_changed"},
		{name: "backup_policy_blocks", action: "quarantine", backup: true, wantError: "recovery_blocked_by_policy"},
		{name: "legacy_block_trusted", legacyMode: "block", certified: true},
		{name: "legacy_block_untrusted", legacyMode: "block", wantError: "recovery_blocked_by_policy"},
		{name: "legacy_repair_trusted", legacyMode: "repair", certified: true},
		{name: "legacy_repair_untrusted", legacyMode: "repair", wantError: "recovery_blocked_by_policy"},
		{name: "rescan", action: "submit_scan"},
		{name: "quarantine", action: "quarantine", wantError: "recovery_blocked_by_policy"},
		{name: "malicious", action: "uninstall", malicious: true, wantError: "recovery_blocked_by_policy"},
		{name: "occupied", action: "record", fault: "occupied", wantError: "recovery_path_occupied"},
		{name: "root_repointed", action: "record", fault: "root_repointed", wantError: "skill_content_changed"},
		{name: "changed", action: "record", fault: "changed", wantError: "recovery_content_changed"},
		{name: "missing_manifest", action: "record", fault: "missing_manifest", wantError: "recovery_content_changed"},
		{name: "offline", action: "record", fault: "offline", wantError: "503"},
		{name: "missing_verdict", action: "record", fault: "missing_verdict", wantError: "recovery_verdict_unavailable"},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			home, store, inventory, skill := observedFixture(t)
			item, err := quarantineSkill(home, store, "codex", skill.Name, skill.Path, "unverified", skill.Signature)
			if err != nil {
				t.Fatal(err)
			}
			expectedTarget := ""
			if scenario.backup {
				if _, err := store.db.Exec(`UPDATE client_quarantine SET status='backed_up' WHERE id=?`, item.ID); err != nil {
					t.Fatal(err)
				}
				writeSkill(t, skill.Path, "current")
				if err := os.WriteFile(filepath.Join(skill.Path, "user.txt"), []byte("keep"), 0600); err != nil {
					t.Fatal(err)
				}
				state, err := inspectInstallTarget(skill.Path)
				if err != nil {
					t.Fatal(err)
				}
				expectedTarget = state.signature
				if scenario.fault == "backup_changed" {
					if err := os.WriteFile(filepath.Join(skill.Path, "changed.txt"), []byte("new edit"), 0600); err != nil {
						t.Fatal(err)
					}
				}
			}
			if scenario.fault == "occupied" {
				if err := os.MkdirAll(skill.Path, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(skill.Path, "user.txt"), []byte("keep"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if scenario.fault == "changed" {
				if err := os.WriteFile(filepath.Join(item.QuarantinePath, "new.txt"), []byte("edit"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if scenario.fault == "missing_manifest" {
				if err := os.Remove(filepath.Join(item.QuarantinePath, "SKILL.md")); err != nil {
					t.Fatal(err)
				}
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if scenario.fault == "offline" {
					http.Error(w, "offline", 503)
					return
				}
				switch {
				case strings.HasSuffix(r.URL.Path, "/policy"):
					if scenario.fault == "root_repointed" {
						root := filepath.Dir(skill.Path)
						if err := os.Rename(root, root+"-original"); err != nil {
							t.Error(err)
						}
						other := filepath.Join(home, "new-root")
						if err := os.MkdirAll(other, 0700); err != nil {
							t.Error(err)
						}
						if err := os.Symlink(other, root); err != nil {
							t.Error(err)
						}
					}
					if scenario.legacyMode != "" {
						json.NewEncoder(w).Encode(Policy{Mode: scenario.legacyMode})
						return
					}
					json.NewEncoder(w).Encode(Policy{Classification: &ClassificationPolicy{Enabled: true, Protocol: 1, Version: "2:1", Rules: map[string]string{"unverified": scenario.action, "malicious": scenario.action}}})
				case strings.HasSuffix(r.URL.Path, "/compare"):
					items := []CompareItem{}
					if scenario.fault != "missing_verdict" {
						items = append(items, CompareItem{AgentType: "codex", LocalPath: skill.Path, LocalSignature: skill.Signature, Malicious: scenario.malicious, Certified: scenario.certified})
					}
					json.NewEncoder(w).Encode(map[string]any{"items": items})
				default:
					w.Write([]byte(`{}`))
				}
			}))
			defer server.Close()
			task := Task{ID: 31, TaskType: "skill_action", Payload: map[string]any{"action": "restore_quarantine", "agent_type": "codex", "path": skill.Path, "expected_signature": skill.Signature, "quarantine_id": item.ID}}
			if scenario.backup {
				task.Payload["action"] = "restore_backup"
				task.Payload["expected_target_signature"] = expectedTarget
			}
			err = restoreQuarantineTask(context.Background(), home, inventory, inventory.Agents[0], NewAPI(server.URL, "token", time.Second), store, task)
			if scenario.wantError != "" {
				if err == nil || !strings.Contains(err.Error(), scenario.wantError) {
					t.Fatalf("wanted %s, got %v", scenario.wantError, err)
				}
				if scenario.fault == "root_repointed" {
					if _, err := os.Lstat(skill.Path); !os.IsNotExist(err) {
						t.Fatal("restored into repointed root", err)
					}
					if err := checkObservedContent(Skill{Path: item.QuarantinePath, Signature: skill.Signature}); err != nil {
						t.Fatal("recovery copy changed", err)
					}
				}
				if scenario.fault == "occupied" || scenario.backup {
					value, err := os.ReadFile(filepath.Join(skill.Path, "user.txt"))
					if err != nil || string(value) != "keep" {
						t.Fatal("existing content changed", err)
					}
				} else if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
					t.Fatal("failed recovery created active content", err)
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				if err := checkObservedContent(skill); err != nil {
					t.Fatal(err)
				}
				if err := executeObservedTask(context.Background(), home, Policy{}, NewAPI(server.URL, "token", time.Second), store, task); err != nil {
					t.Fatal("completed task replay failed", err)
				}
			}
			if _, err := os.Stat(item.QuarantinePath); err != nil {
				t.Fatal("retained copy removed", err)
			}
		})
	}
}

func TestAuthorizedManualRecoveryCompletesWithoutPlatformRoundTrip(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	item, err := quarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual", skill.Signature)
	if err != nil {
		t.Fatal(err)
	}
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/policy") || strings.HasSuffix(r.URL.Path, "/compare") {
			requests.Add(1)
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	task := Task{ID: 61, TaskType: "skill_action", Payload: map[string]any{
		"action": "restore_quarantine", "agent_type": "codex", "path": skill.Path,
		"expected_signature": skill.Signature, "quarantine_id": item.ID, "source": "manual",
	}}
	if err := restoreQuarantineTask(context.Background(), home, inventory, inventory.Agents[0], NewAPI(server.URL, "token", time.Second), store, task); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 0 {
		t.Fatalf("manual recovery waited for platform: %d requests", requests.Load())
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal(err)
	}
}

func TestRecoveryMetadataFailureRetainsCopiesAndRejectsNewContentOnRetry(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	item, err := quarantineSkill(home, store, "codex", skill.Name, skill.Path, "unverified", skill.Signature)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`CREATE TRIGGER fail_restore_metadata BEFORE UPDATE OF status ON client_quarantine
	 WHEN NEW.status='restored' BEGIN SELECT RAISE(ABORT,'simulated storage failure'); END;`); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/policy") {
			json.NewEncoder(w).Encode(Policy{Classification: DefaultClassificationPolicy()})
		} else if strings.HasSuffix(r.URL.Path, "/compare") {
			json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{AgentType: "codex", LocalPath: skill.Path, LocalSignature: skill.Signature}}})
		} else {
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	task := Task{ID: 55, TaskType: "skill_action", Payload: map[string]any{"action": "restore_quarantine", "agent_type": "codex", "path": skill.Path, "expected_signature": skill.Signature, "quarantine_id": item.ID}}
	api := NewAPI(server.URL, "token", time.Second)
	if err := restoreQuarantineTask(context.Background(), home, inventory, inventory.Agents[0], api, store, task); err == nil || !strings.Contains(err.Error(), "simulated storage failure") {
		t.Fatal("failure was not surfaced", err)
	}
	for _, path := range []string{skill.Path, item.QuarantinePath} {
		if err := checkObservedContent(Skill{Path: path, Signature: skill.Signature}); err != nil {
			t.Fatal("recovery content lost", path, err)
		}
	}
	if _, exists, err := store.State("skill-action-receipt:55"); err != nil || exists {
		t.Fatal("failed bookkeeping reported success", exists, err)
	}
	if _, err := store.db.Exec(`DROP TRIGGER fail_restore_metadata`); err != nil {
		t.Fatal(err)
	}
	writeSkill(t, skill.Path, "edited-after-recovery")
	if err := restoreQuarantineTask(context.Background(), home, inventory, inventory.Agents[0], api, store, task); err == nil || err.Error() != "recovery_path_occupied" {
		t.Fatal("retry overwrote post-recovery content", err)
	}
	content, err := os.ReadFile(filepath.Join(skill.Path, "SKILL.md"))
	if err != nil || !strings.Contains(string(content), "edited-after-recovery") {
		t.Fatal(string(content), err)
	}
}

func TestAutomaticRecoveryRequiresExactApprovedContent(t *testing.T) {
	for _, origin := range []string{"quarantine", "legacy_pending", "legacy_untracked"} {
		t.Run(origin, func(t *testing.T) {
			for _, scenario := range []string{"approved", "unapproved", "different_content", "occupied", "offline"} {
				t.Run(scenario, func(t *testing.T) {
					home, store, inventory, skill := observedFixture(t)
					item, err := quarantineSkill(home, store, "codex", skill.Name, skill.Path, "unverified", skill.Signature)
					if err != nil {
						t.Fatal(err)
					}
					if origin == "legacy_pending" || origin == "legacy_untracked" {
						legacyPath := filepath.Join(home, ".river-security", "agent-manager", "pending", "codex", skill.Name)
						if err := os.MkdirAll(filepath.Dir(legacyPath), 0o755); err != nil {
							t.Fatal(err)
						}
						if err := os.Rename(item.QuarantinePath, legacyPath); err != nil {
							t.Fatal(err)
						}
						item.QuarantinePath = legacyPath
						if _, err := store.db.Exec(`DELETE FROM client_quarantine WHERE id=?`, item.ID); err != nil {
							t.Fatal(err)
						}
						if err := store.SavePending(PendingItem{ID: "legacy-copy", AgentType: "codex", SkillName: skill.Name, OriginalPath: skill.Path, PendingPath: item.QuarantinePath, Reason: "skill_not_approved", Status: "pending"}); err != nil {
							t.Fatal(err)
						}
						item.ID = "pending:legacy-copy"
						if origin == "legacy_untracked" {
							if _, err := store.db.Exec(`DELETE FROM client_pending WHERE id=?`, "legacy-copy"); err != nil {
								t.Fatal(err)
							}
							item.ID = "pending:" + pendingID(legacyPath)
						}
					}
					if scenario == "occupied" {
						writeSkill(t, skill.Path, "existing")
					}
					comparisons := 0
					server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						if scenario == "offline" {
							http.Error(w, "offline", 503)
							return
						}
						switch {
						case strings.HasSuffix(r.URL.Path, "/policy"):
							json.NewEncoder(w).Encode(Policy{Classification: DefaultClassificationPolicy()})
						case strings.HasSuffix(r.URL.Path, "/compare"):
							comparisons++
							signature := skill.Signature
							if scenario == "different_content" {
								signature = "other"
							}
							json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{AgentType: "codex", LocalPath: skill.Path, LocalSignature: signature, Certified: scenario != "unapproved"}}})
						default:
							w.Write([]byte(`{}`))
						}
					}))
					defer server.Close()
					api := NewAPI(server.URL, "token", time.Second)
					changed, err := ReconcileCertifiedQuarantine(context.Background(), home, api, store, inventory)
					if scenario == "approved" {
						if err != nil || !changed {
							t.Fatalf("restore: %v %v", changed, err)
						}
						if err := checkObservedContent(skill); err != nil {
							t.Fatal(err)
						}
						if origin == "legacy_pending" || origin == "legacy_untracked" {
							pending, err := store.PendingItems()
							if err != nil || len(pending) != 0 {
								t.Fatalf("restored pending record remains: %v %v", pending, err)
							}
							if _, err := os.Stat(item.QuarantinePath); err != nil {
								t.Fatal("recovery source was not retained", err)
							}
						}
						var status string
						if err := store.db.QueryRow(`SELECT status FROM client_quarantine WHERE id=?`, item.ID).Scan(&status); err != nil || status != "restored" {
							t.Fatalf("status %s %v", status, err)
						}
						again, err := ReconcileCertifiedQuarantine(context.Background(), home, api, store, inventory)
						if err != nil || again || comparisons != 1 {
							t.Fatalf("duplicate recovery %v %v %d", again, err, comparisons)
						}
					} else if changed {
						t.Fatal("restored unapproved or unavailable content")
					} else if scenario != "occupied" {
						if _, err := os.Lstat(skill.Path); !os.IsNotExist(err) {
							t.Fatal("created target", err)
						}
					}
					if err := checkObservedContent(Skill{Path: item.QuarantinePath, Signature: skill.Signature}); err != nil {
						t.Fatal("lost recovery copy", err)
					}
				})
			}
		})
	}
}

func TestManualQuarantineRequiresExplicitRestore(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	item, err := quarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual", skill.Signature)
	if err != nil {
		t.Fatal(err)
	}
	comparisons := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/policy"):
			json.NewEncoder(w).Encode(Policy{Classification: DefaultClassificationPolicy()})
		case strings.HasSuffix(r.URL.Path, "/compare"):
			comparisons++
			json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{AgentType: "codex", LocalPath: skill.Path, LocalSignature: skill.Signature, Certified: true}}})
		default:
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	api := NewAPI(server.URL, "token", time.Second)
	for i := 0; i < 2; i++ {
		changed, err := ReconcileCertifiedQuarantine(context.Background(), home, api, store, inventory)
		if err != nil || changed || comparisons != 0 {
			t.Fatalf("manual quarantine auto-restored: %v %v %d", changed, err, comparisons)
		}
	}
	if _, err := os.Lstat(skill.Path); !os.IsNotExist(err) {
		t.Fatal("isolated path reappeared", err)
	}
	if err := checkObservedContent(Skill{Path: item.QuarantinePath, Signature: skill.Signature}); err != nil {
		t.Fatal(err)
	}
	task := Task{ID: 99, TaskType: "skill_action", Payload: map[string]any{"action": "restore_quarantine", "path": skill.Path, "expected_signature": skill.Signature, "quarantine_id": item.ID}}
	if err := restoreQuarantineTask(context.Background(), home, inventory, inventory.Agents[0], api, store, task); err != nil {
		t.Fatal(err)
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal(err)
	}
	if comparisons != 1 {
		t.Fatal("explicit restore did not recheck approval", comparisons)
	}
}
