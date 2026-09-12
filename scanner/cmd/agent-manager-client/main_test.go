package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestConfirmedLegacyTakeoverUsesEffectiveClassification(t *testing.T) {
	home := t.TempDir()
	skill := filepath.Join(home, ".codex", "skills", "local", "SKILL.md")
	if err := os.MkdirAll(filepath.Dir(skill), 0700); err != nil {
		t.Fatal(err)
	}
	const content = "---\nname: local\n---\nlocal content"
	if err := os.WriteFile(skill, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/policy"), strings.HasSuffix(r.URL.Path, "/heartbeat"):
			json.NewEncoder(w).Encode(managedclient.Policy{Mode: "block", Classification: managedclient.DefaultClassificationPolicy()})
		case strings.HasSuffix(r.URL.Path, "/tasks"):
			w.Write([]byte(`[]`))
		case strings.HasSuffix(r.URL.Path, "/compare"):
			w.Write([]byte(`{"items":[]}`))
		default:
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	if err := run([]string{"takeover", "--home", home, "--server", server.URL, "--token", "test", "--confirm"}); err != nil {
		t.Fatal(err)
	}
	if actual, err := os.ReadFile(skill); err != nil || string(actual) != content {
		t.Fatal("legacy command moved content under record policy", string(actual), err)
	}
}

func TestPendingCopyCommandsRespectMutationLock(t *testing.T) {
	for _, command := range []string{"discard-pending", "queue-quarantine"} {
		t.Run(command, func(t *testing.T) {
			home := t.TempDir()
			release, err := managedclient.AcquireMutationLock(home)
			if err != nil {
				t.Fatal(err)
			}
			defer release()
			err = run([]string{command, "--home", home, "--id", "example", "--confirm"})
			if err == nil || !strings.Contains(err.Error(), "skill_action_busy") {
				t.Fatal("command bypassed mutation lock", err)
			}
		})
	}
}

func TestConfigureConnectionChangeKeepsDiscoveryAndClearsPlatformState(t *testing.T) {
	home := t.TempDir()
	if err := managedclient.SaveConfig(home, managedclient.Config{
		Server: "http://old.example",
		Token:  "old-token",
		Name:   "test client",
	}); err != nil {
		t.Fatal(err)
	}
	store, err := managedclient.OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	if err := store.SetState("policy", `{"mode":"block"}`); err != nil {
		t.Fatal(err)
	}
	if err := store.SetState("patrol_findings", `[{"event_type":"skill_modified"}]`); err != nil {
		t.Fatal(err)
	}
	if err := store.SetState("inventory", `{"client_id":"old-client"}`); err != nil {
		t.Fatal(err)
	}
	platformKeys := []string{"patrol:full", "patrol:inventory", "patrol:force", "tasks:poll", "pending:auto-install:old-pending", "observation:trusted", "observation-count:incident", "skill-action-receipt:42", "task:reported:42", "sync:heartbeat:success", "sync:worker:error"}
	for _, key := range platformKeys {
		if err := store.MarkSchedule(key); err != nil {
			t.Fatal(err)
		}
	}
	if err := store.SaveTask(managedclient.Task{ID: 42, TaskType: "install_skill"}, "succeeded", ""); err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInstall(managedclient.Installation{
		AgentType: "codex", ManagedAgentID: "old-agent", SkillID: "old-family",
		SkillName: "old-installed", TargetPath: filepath.Join(home, ".codex", "skills", "old-installed"),
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.QueueEvent(managedclient.QueuedEvent{
		ClientID: "client-1", EventType: "skill_modified", AgentType: "codex", SkillName: "demo",
	}); err != nil {
		t.Fatal(err)
	}
	pendingPath := filepath.Join(home, "pending", "demo")
	if err := os.MkdirAll(pendingPath, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := store.SavePending(managedclient.PendingItem{
		ID: "old-pending", AgentType: "codex", SkillName: "demo",
		PendingPath: pendingPath, Status: "REJECTED",
		SkillID: "old-family", VersionID: "old-version", SubmittedAt: "2026-08-01T00:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	if err := run([]string{
		"configure", "--home", home,
		"--server", "http://new.example/",
		"--token", "new-token",
		"--name", "test client",
	}); err != nil {
		t.Fatal(err)
	}

	config, err := managedclient.LoadConfig(home)
	if err != nil {
		t.Fatal(err)
	}
	if config.Server != "http://new.example" || config.Token != "new-token" {
		t.Fatalf("unexpected saved config: %#v", config)
	}
	store, err = managedclient.OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if enabled, err := store.GovernanceEnabled(); err != nil || !enabled {
		t.Fatalf("automatic discovery was disabled: enabled=%v err=%v", enabled, err)
	}
	for _, key := range append(platformKeys, "policy", "patrol_findings", "inventory") {
		if _, ok, err := store.State(key); err != nil || ok {
			t.Fatalf("%s was not cleared: ok=%v err=%v", key, ok, err)
		}
	}
	if tasks, err := store.TaskHistory(10); err != nil || len(tasks) != 0 {
		t.Fatalf("tasks from the previous platform were retained: %#v err=%v", tasks, err)
	}
	if installs, err := store.Installations(); err != nil || len(installs) != 0 {
		t.Fatalf("install associations from the previous platform were retained: %#v err=%v", installs, err)
	}
	if events, err := store.QueuedEvents(); err != nil || len(events) != 0 {
		t.Fatalf("events from the previous platform were retained: %#v err=%v", events, err)
	}
	pending, err := store.PendingItems()
	if err != nil {
		t.Fatal(err)
	}
	if len(pending) != 1 || pending[0].Status != "pending" || pending[0].SkillID != "" || pending[0].VersionID != "" || pending[0].SubmittedAt != "" {
		t.Fatalf("pending submission remained bound to the previous platform: %#v", pending)
	}
	notifications, err := store.Notifications(10)
	if err != nil {
		t.Fatal(err)
	}
	if len(notifications) != 1 || notifications[0].EventType != "connection_changed_state_reset" {
		t.Fatalf("connection change notification was not recorded: %#v", notifications)
	}
}

func TestConfigureDoesNotChangeConnectionDuringRuntimeOrFileAction(t *testing.T) {
	for _, kind := range []string{"runtime", "mutation"} {
		t.Run(kind, func(t *testing.T) {
			home := t.TempDir()
			original := managedclient.Config{Server: "http://old.example", Token: "old-token"}
			if err := managedclient.SaveConfig(home, original); err != nil {
				t.Fatal(err)
			}
			acquire := managedclient.AcquireRunLock
			if kind == "mutation" {
				acquire = managedclient.AcquireMutationLock
			}
			release, err := acquire(home)
			if err != nil {
				t.Fatal(err)
			}
			defer release()
			if err := run([]string{"configure", "--home", home, "--server", "http://new.example", "--token", "new-token"}); err == nil {
				t.Fatal("connection changed during active work")
			}
			config, err := managedclient.LoadConfig(home)
			if err != nil || config.Server != original.Server || config.Token != original.Token {
				t.Fatal("configuration changed", err)
			}
		})
	}
}

func TestLoadCachedInventoryRejectsOutdatedCache(t *testing.T) {
	store, err := managedclient.OpenStore(filepath.Join(t.TempDir(), "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SetState("inventory", `{"client_id":"old-client"}`); err != nil {
		t.Fatal(err)
	}
	if _, err := loadCachedInventory(store); err == nil {
		t.Fatal("outdated inventory cache should be rejected")
	}
	if err := store.SaveInventory(managedclient.Inventory{ClientID: "current-client"}); err != nil {
		t.Fatal(err)
	}
	cached, err := loadCachedInventory(store)
	if err != nil || cached.ClientID != "current-client" {
		t.Fatalf("current inventory cache was not loaded: %#v %v", cached, err)
	}
}

func TestTakeoverPreviewUsesCachedInventory(t *testing.T) {
	home := t.TempDir()
	store, err := managedclient.OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInventory(managedclient.Inventory{
		ClientID: "cached-client",
		Agents: []managedclient.Agent{{
			AgentType:                "codex",
			SkillManagementSupported: true,
			Skills:                   []managedclient.Skill{{Name: "cached-skill", Path: "/missing/cached-skill", Signature: "cached-signature"}},
		}},
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/api/v1/clients/cached-client/inventory":
			response.WriteHeader(http.StatusOK)
		case "/api/v1/clients/cached-client/compare":
			_ = json.NewEncoder(response).Encode(map[string]any{"items": []map[string]any{{
				"agent_type": "codex", "name": "cached-skill", "local_path": "/missing/cached-skill",
				"local_signature": "cached-signature", "allowed": false, "reason": "skill_not_found",
			}}})
		default:
			http.NotFound(response, request)
		}
	}))
	defer server.Close()

	if err := run([]string{"takeover", "--home", home, "--server", server.URL, "--token", "token", "--skill", "/missing/cached-skill"}); err != nil {
		t.Fatalf("takeover preview should use cached inventory without reading the missing Skill path: %v", err)
	}
}

func TestFilterInventorySkillsBeforeCompare(t *testing.T) {
	inventory := managedclient.Inventory{Agents: []managedclient.Agent{
		{AgentType: "codex", Skills: []managedclient.Skill{{Path: "/skills/first"}, {Path: "/skills/second"}}},
		{AgentType: "hermes", Skills: []managedclient.Skill{{Path: "/skills/third"}}},
	}}
	filtered, excluded := filterInventorySkills(inventory, []string{"/skills/second"})
	if len(filtered.Agents) != 1 || len(filtered.Agents[0].Skills) != 1 || filtered.Agents[0].Skills[0].Path != "/skills/second" {
		t.Fatalf("unexpected filtered inventory: %#v", filtered.Agents)
	}
	if len(excluded) != 2 {
		t.Fatalf("unexpected exclusions: %#v", excluded)
	}
}
