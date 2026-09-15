package managedclient

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
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
			for _, item := range items {
				if len(item.AffectedTargets) != 2 {
					t.Fatal("shared recovery did not expose every affected target", item)
				}
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
				if i == 0 {
					active, err := store.QuarantineItems()
					if err != nil || len(active) != 1 || len(active[0].AffectedTargets) != 2 {
						t.Fatal("remaining shared recovery lost incident scope", active, err)
					}
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
	queued, err := store.PendingItems()
	if err != nil || len(queued) != 2 || queued[0].Fingerprint == "" || queued[0].Fingerprint != queued[1].Fingerprint {
		t.Fatal("shared recovery did not queue every target under one verdict", queued, err)
	}
	if _, err := store.DiscardPending(pending.ID); err != nil {
		t.Fatal(err)
	}
	queued, err = store.PendingItems()
	if err != nil || len(queued) != 1 {
		t.Fatal("discard removed another Agent pending target", queued, err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].Signature != skill.Signature {
		t.Fatal("other recovery lost", items, err)
	}
}

func TestApprovedSharedRecoveryRestoresEveryAffectedAgent(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	external := filepath.Join(t.TempDir(), "safe-skill")
	writeSkill(t, external, "safe-skill")
	state, err := inspectInstallTarget(external)
	if err != nil {
		t.Fatal(err)
	}
	paths := map[string]string{
		"codex":       filepath.Join(home, ".codex", "skills", "safe-skill"),
		"claude-code": filepath.Join(home, ".claude", "skills", "safe-skill"),
	}
	inventory := Inventory{ClientID: "client-1"}
	for _, agentType := range []string{"codex", "claude-code"} {
		path := paths[agentType]
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(external, path); err != nil {
			t.Fatal(err)
		}
		inventory.Agents = append(inventory.Agents, Agent{
			AgentType: agentType, SkillsPath: filepath.Dir(path), SkillManagementSupported: true,
			Skills: []Skill{{Name: "safe-skill", Path: path, Signature: state.signature}},
		})
	}
	value := SkillObservation{Action: "quarantine", Trigger: "trusted_content_changed", Signature: state.signature}
	ids, err := applyAutomaticObservedAction(context.Background(), home, inventory, inventory.Agents[0], inventory.Agents[0].Skills[0], canonicalSkillRoot(external), Policy{}, API{}, store, &value)
	if err != nil {
		t.Fatal(err)
	}
	pending, err := QueueQuarantineForDetectionExpected(home, store, ids[paths["codex"]], state.signature)
	if err != nil {
		t.Fatal(err)
	}
	queued, err := store.PendingItems()
	if err != nil || len(queued) != 2 {
		t.Fatal("shared event was not expanded into per-Agent recovery targets", queued, err)
	}
	if err := store.MarkPendingSubmitted(pending, "skill-1", "version-1"); err != nil {
		t.Fatal(err)
	}
	if err := store.UpdatePendingStatus("skill-1", "version-1", "APPROVED"); err != nil {
		t.Fatal(err)
	}

	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackageFor(t, privateKey, "safe-skill")
	packageRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch {
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/scanner/imports/version-1":
			_ = json.NewEncoder(response).Encode(map[string]any{
				"skill_id": "skill-1", "version_id": "version-1", "name": "safe-skill", "status": "APPROVED",
			})
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/clients/client-1/skills/skill-1/package":
			packageRequests++
			response.Header().Set("Content-Type", "application/zip")
			_, _ = response.Write(packageBody)
		case request.Method == http.MethodPost:
			response.WriteHeader(http.StatusNoContent)
		default:
			t.Errorf("unexpected request: %s %s", request.Method, request.URL.String())
			response.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()
	changed, err := ReconcileApprovedPending(context.Background(), home, NewAPI(server.URL, "token", 5*time.Second), store, inventory, Policy{
		ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey),
	})
	if err != nil {
		t.Fatal(err)
	}
	if !changed || packageRequests != 2 {
		t.Fatalf("shared approval did not install every target: changed=%v requests=%d", changed, packageRequests)
	}
	if items, err := store.PendingItems(); err != nil || len(items) != 0 {
		t.Fatal("shared pending targets remain", items, err)
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 0 {
		t.Fatal("shared quarantine targets remain", items, err)
	}
	for agentType, path := range paths {
		if _, err := filepath.EvalSymlinks(path); err != nil {
			t.Fatal("approved version was not restored", agentType, err)
		}
		content, err := os.ReadFile(filepath.Join(path, "SKILL.md"))
		if err != nil || string(content) != "---\nname: safe-skill\n---\n" {
			t.Fatalf("wrong approved content restored for %s: %q %v", agentType, content, err)
		}
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

func TestSharedLinkPatrolQueuesEventsAfterEnforcement(t *testing.T) {
	home, store, inventory, skill, external := sharedLinksFixture(t)
	alias := inventory.Agents[1].Skills[0].Path
	reported := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/events") {
			reported = append(reported, "unexpected")
		}
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer server.Close()
	policy := Policy{Classification: DefaultClassificationPolicy()}
	policy.Classification.Rules["unverified"] = "quarantine"
	if err := patrolClassified(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, true); err != nil {
		t.Fatal(err)
	}
	if len(reported) != 0 {
		t.Fatal("unexpected synchronous events", reported)
	}
	queued, err := store.QueuedEvents()
	if err != nil || len(queued) != 2 || queued[0].EventType != "skill_governance_detected" || queued[1].EventType != "skill_governance_action" {
		t.Fatal("governance events were not queued in order", queued, err)
	}
	if err := checkObservedContent(Skill{Path: external, Signature: skill.Signature}); err != nil {
		t.Fatal("shared content copy was lost", err)
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
