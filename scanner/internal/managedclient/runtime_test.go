package managedclient

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestModelConfigTaskRetrievesAgentCredentialOutsideTaskPayload(t *testing.T) {
	home := t.TempDir()
	requestedPath := ""
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		requestedPath = request.URL.Path
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(request.URL.Path, "/model-preflight") {
			_, _ = w.Write([]byte(`{"ok":true}`))
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"token":          "amat_task_bound_agent_secret",
			"token_prefix":   "amat_task_bo",
			"bound_agent_id": "managed-claude",
			"allowed_models": []string{"claude-managed"},
		})
	}))
	defer server.Close()
	store, err := OpenStore(filepath.Join(home, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	err = executeTask(
		context.Background(),
		home,
		Inventory{ClientID: "host-1"},
		Policy{},
		NewAPI(server.URL, "client-token", time.Second),
		store,
		Task{
			ID:       42,
			TaskType: "apply_model_config",
			Payload: map[string]any{
				"local_agent_id":        "claude-main",
				"agent_type":            "claude-code",
				"model":                 "claude-managed",
				"auto_issue_credential": true,
			},
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	if requestedPath != "/api/v1/clients/host-1/tasks/42/agent-credential" {
		t.Fatalf("unexpected credential endpoint: %s", requestedPath)
	}
	body, err := os.ReadFile(filepath.Join(home, ".claude", "settings.json"))
	if err != nil {
		t.Fatal(err)
	}
	var settings map[string]any
	if err := json.Unmarshal(body, &settings); err != nil {
		t.Fatal(err)
	}
	env, _ := settings["env"].(map[string]any)
	if env["ANTHROPIC_AUTH_TOKEN"] != "amat_task_bound_agent_secret" {
		t.Fatalf("task-issued credential was not applied: %#v", env)
	}
}

func TestModelPreflightFailureDoesNotIssueCredentialOrWrite(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, ".claude", "settings.json")
	before := []byte(`{"env":{"CLAUDE_CODE_MAX_OUTPUT_TOKENS":"2048"},"unrelated":true}`)
	if err := atomicWriteFile(path, before, 0o600); err != nil {
		t.Fatal(err)
	}
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		requests++
		if !strings.HasSuffix(request.URL.Path, "/model-preflight") {
			t.Errorf("credential requested after failed preflight")
		}
		var body struct {
			Current map[string]any `json:"current_parameters"`
		}
		_ = json.NewDecoder(request.Body).Decode(&body)
		if body.Current["max_output_tokens"] != float64(2048) {
			t.Errorf("inherited parameter missing: %v", body.Current)
		}
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"error_code":"client.model_output_limit"}`))
	}))
	defer server.Close()
	store, err := OpenStore(filepath.Join(home, "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	err = executeTask(context.Background(), home, Inventory{ClientID: "host"}, Policy{}, NewAPI(server.URL, "test", time.Second), store, Task{ID: 42, TaskType: "apply_model_config", Payload: map[string]any{"agent_type": "claude-code", "local_agent_id": "claude-code", "model": "model-b", "auto_issue_credential": true}})
	if err == nil || requests != 1 {
		t.Fatalf("failed preflight did not stop task: %v, requests=%d", err, requests)
	}
	after, _ := os.ReadFile(path)
	if !bytes.Equal(before, after) {
		t.Fatal("configuration changed after failed preflight")
	}
}

func TestRunOnceInstallsSignedTaskAndRecordsCompletion(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(filepath.Join(home, ".codex", "skills"), 0o755); err != nil {
		t.Fatal(err)
	}
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackage(t, privateKey)
	resultStatuses := []string{}
	mode := "audit"
	events := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		switch {
		case strings.HasSuffix(request.URL.Path, "/heartbeat"):
			w.Write([]byte(`{"ok":true}`))
		case strings.HasSuffix(request.URL.Path, "/policy"):
			json.NewEncoder(w).Encode(map[string]any{"mode": mode, "release_public_key": base64.StdEncoding.EncodeToString(publicKey)})
		case strings.HasSuffix(request.URL.Path, "/tasks") && request.Method == http.MethodGet:
			json.NewEncoder(w).Encode([]map[string]any{{
				"id":        9,
				"task_type": "install_skill",
				"payload": map[string]any{
					"agent_type":       "codex",
					"managed_agent_id": "codex-agent",
					"skill_id":         "skill-1",
				},
			}})
		case strings.HasSuffix(request.URL.Path, "/compare"):
			w.Write([]byte(`{"items":[]}`))
		case strings.HasSuffix(request.URL.Path, "/inventory"):
			w.Write([]byte(`{"ok":true}`))
		case strings.Contains(request.URL.Path, "/skills/skill-1/package"):
			w.Write(packageBody)
		case strings.HasSuffix(request.URL.Path, "/tasks/9/result"):
			var payload map[string]any
			json.NewDecoder(request.Body).Decode(&payload)
			resultStatuses = append(resultStatuses, payload["status"].(string))
			w.Write([]byte(`{"ok":true}`))
		case strings.HasSuffix(request.URL.Path, "/events"):
			var payload map[string]any
			json.NewDecoder(request.Body).Decode(&payload)
			events = append(events, payload["event_type"].(string))
			w.Write([]byte(`{"ok":true}`))
		default:
			t.Fatalf("unexpected request %s %s", request.Method, request.URL.Path)
		}
	}))
	defer server.Close()

	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	api := NewAPI(server.URL, "token", 5*time.Second)
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInventory(inventory); err != nil {
		t.Fatal(err)
	}
	policyBody, _ := json.Marshal(Policy{Mode: "block", ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey)})
	if err := store.SetState("policy", string(policyBody)); err != nil {
		t.Fatal(err)
	}
	if err := PollTasks(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	refreshedBody, ok, err := store.State("policy")
	if err != nil || !ok {
		t.Fatal("refreshed policy was not cached")
	}
	var refreshedPolicy Policy
	if err := json.Unmarshal([]byte(refreshedBody), &refreshedPolicy); err != nil || refreshedPolicy.Mode != mode {
		t.Fatalf("cached policy was not refreshed: %#v %v", refreshedPolicy, err)
	}
	if got := strings.Join(resultStatuses, ","); got != "running,succeeded" {
		t.Fatalf("unexpected task statuses %s", got)
	}
	if _, err := os.Stat(filepath.Join(home, ".codex", "skills", "safe-skill", "SKILL.md")); err != nil {
		t.Fatal("installed skill is not visible:", err)
	}
	completed, err := store.TaskCompleted(9)
	if err != nil || !completed {
		t.Fatalf("task completion not stored: %v %v", completed, err)
	}
	installed := filepath.Join(home, ".codex", "skills", "safe-skill", "SKILL.md")
	if err := os.WriteFile(installed, []byte("tampered"), 0o644); err != nil {
		t.Fatal(err)
	}
	mode = "repair"
	if err := RunFullScan(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(installed)
	if err != nil || !strings.Contains(string(body), "name: safe-skill") {
		t.Fatalf("repair did not restore the approved package: %q %v", body, err)
	}
	if got := strings.Join(events, ","); got != "skill_installed,skill_modified,skill_installed,skill_repaired" {
		t.Fatalf("unexpected patrol events %s", got)
	}
	status, err := store.LocalStatus()
	if err != nil || len(status.PatrolFindings) != 1 || status.PatrolFindings[0].SkillName != "safe-skill" {
		t.Fatalf("modified Skill was not exposed in patrol status: %#v %v", status.PatrolFindings, err)
	}
	if err := store.SetGovernanceEnabled(false); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(installed, []byte("left unchanged while paused"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := RunFullScan(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	pausedBody, err := os.ReadFile(installed)
	if err != nil || string(pausedBody) != "left unchanged while paused" {
		t.Fatalf("paused governance changed the Skill: %q %v", pausedBody, err)
	}
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(installed, []byte("tampered again"), 0o644); err != nil {
		t.Fatal(err)
	}
	mode = "block"
	if err := RunFullScan(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	if installs, err := store.Installations(); err != nil || len(installs) != 0 {
		t.Fatalf("quarantined Skill left a stale installation: %#v %v", installs, err)
	}
	if err := RunFullScan(context.Background(), home, api, store); err != nil {
		t.Fatalf("next patrol failed after quarantine: %v", err)
	}
}

func TestRescanTaskRequestsFullScan(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if !strings.HasSuffix(request.URL.Path, "/inventory") {
			t.Fatalf("unexpected request %s %s", request.Method, request.URL.Path)
		}
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer server.Close()
	if err := executeTask(
		context.Background(),
		home,
		Inventory{},
		Policy{},
		NewAPI(server.URL, "token", time.Second),
		store,
		Task{TaskType: "rescan"},
	); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(home, ".agent-manager", "run-now"))
	if err != nil {
		t.Fatal(err)
	}
	if string(body) != "full" {
		t.Fatalf("rescan requested %q scan, want full", body)
	}
}

func TestInstallConfirmsInstalledContentBeforeReturning(t *testing.T) {
	for _, scenario := range []string{"certified", "signature_mismatch", "unavailable", "malicious"} {
		t.Run(scenario, func(t *testing.T) {
			home := t.TempDir()
			root := filepath.Join(home, ".codex", "skills")
			if err := os.MkdirAll(root, 0o755); err != nil {
				t.Fatal(err)
			}
			publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
			if err != nil {
				t.Fatal(err)
			}
			body := signedPackage(t, privateKey)
			store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			compared := false
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch {
				case strings.Contains(r.URL.Path, "/skills/skill-1/package"):
					_, _ = w.Write(body)
				case strings.HasSuffix(r.URL.Path, "/compare"):
					compared = true
					if scenario == "unavailable" {
						w.WriteHeader(http.StatusServiceUnavailable)
						return
					}
					var payload struct {
						Agents []Agent `json:"agents"`
					}
					if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
						t.Error(err)
						return
					}
					if len(payload.Agents) != 1 || len(payload.Agents[0].Skills) != 1 {
						t.Error("expected only the installed skill")
						return
					}
					skill := payload.Agents[0].Skills[0]
					sig := skill.Signature
					if scenario == "signature_mismatch" {
						sig = "different-content"
					}
					_ = json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{
						AgentType: "codex", Name: skill.Name, LocalPath: skill.Path,
						LocalSignature: sig, Certified: true, Malicious: scenario == "malicious",
						SkillID: "skill-1", VersionID: "version-1",
					}}})
				case strings.HasSuffix(r.URL.Path, "/events"):
					_, _ = w.Write([]byte(`{"ok":true}`))
				default:
					t.Errorf("unexpected request %s", r.URL.Path)
					w.WriteHeader(http.StatusNotFound)
				}
			}))
			defer server.Close()
			inventory := Inventory{ClientID: "client-1", Agents: []Agent{{AgentType: "codex", SkillsPath: root, SkillManagementSupported: true}}}
			policy := Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey), Classification: DefaultClassificationPolicy()}
			if err := InstallApprovedSkill(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, "codex", "", "skill-1"); err != nil {
				t.Fatal(err)
			}
			value, err := store.Observation(filepath.Join(root, "safe-skill"))
			if err != nil {
				t.Fatal(err)
			}
			if !compared {
				t.Fatal("install returned without comparing installed content")
			}
			if scenario == "certified" || scenario == "malicious" {
				if value.Certification != "certified" || value.TrustedSignature == "" || value.TrustedVersionID != "version-1" {
					t.Fatalf("missing immediate certification: %+v", value)
				}
			} else if value.Certification == "certified" {
				t.Fatalf("invalid certification: %+v", value)
			}
		})
	}
}

func TestInstallApprovedSkillSharesReleaseAcrossAgents(t *testing.T) {
	home := t.TempDir()
	codexSkills := filepath.Join(home, ".codex", "skills")
	hermesSkills := filepath.Join(home, ".hermes", "skills")
	opencodeSkills := filepath.Join(home, ".config", "opencode", "skills")
	geminiSkills := filepath.Join(home, ".gemini", "skills")
	for _, path := range []string{codexSkills, hermesSkills, opencodeSkills, geminiSkills} {
		if err := os.MkdirAll(path, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackage(t, privateKey)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		switch {
		case strings.Contains(request.URL.Path, "/skills/skill-1/package"):
			_, _ = w.Write(packageBody)
		case strings.HasSuffix(request.URL.Path, "/events"):
			_, _ = w.Write([]byte(`{"ok":true}`))
		default:
			t.Fatalf("unexpected request %s %s", request.Method, request.URL.Path)
		}
	}))
	defer server.Close()

	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	quarantineSource := filepath.Join(codexSkills, "safe-skill")
	writeSkill(t, quarantineSource, "safe-skill")
	if _, err := QuarantineSkill(home, store, "codex", "safe-skill", quarantineSource, "signature_mismatch"); err != nil {
		t.Fatal(err)
	}
	inventory := Inventory{
		ClientID: "client-1",
		Agents: []Agent{
			{AgentType: "codex", SkillsPath: codexSkills, SkillManagementSupported: true},
			{AgentType: "hermes", SkillsPath: hermesSkills, SkillManagementSupported: true},
			{AgentType: "opencode", SkillsPath: opencodeSkills, SkillManagementSupported: true},
			{AgentType: "gemini", SkillsPath: geminiSkills, SkillManagementSupported: true},
		},
	}
	policy := Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey)}
	api := NewAPI(server.URL, "token", 5*time.Second)
	for _, agentType := range []string{"codex", "hermes"} {
		if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, agentType, "", "skill-1"); err != nil {
			t.Fatal(err)
		}
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 0 {
		t.Fatalf("approved install did not resolve quarantine: %#v %v", items, err)
	}

	expectedTarget := filepath.Join(ManagedSkillsRoot(home), "skill-1", "release")
	expectedTarget, err = filepath.EvalSymlinks(expectedTarget)
	if err != nil {
		t.Fatal(err)
	}
	for _, link := range []string{
		filepath.Join(codexSkills, "safe-skill"),
		filepath.Join(hermesSkills, "safe-skill"),
	} {
		info, err := os.Lstat(link)
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode()&os.ModeSymlink == 0 {
			t.Fatalf("%s is not a symlink", link)
		}
		target, err := filepath.EvalSymlinks(link)
		if err != nil {
			t.Fatal(err)
		}
		if target != expectedTarget {
			t.Fatalf("%s points to %s, want %s", link, target, expectedTarget)
		}
	}
	brokenLink := filepath.Join(geminiSkills, "safe-skill")
	if err := os.Symlink(filepath.Join(home, ".agent-manager", "skills", "deleted-skill", "release"), brokenLink); err != nil {
		t.Fatal(err)
	}
	if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, "gemini", "", "skill-1"); err != nil {
		t.Fatalf("approved install did not replace broken managed link: %v", err)
	}
	if target, err := filepath.EvalSymlinks(brokenLink); err != nil || target != expectedTarget {
		t.Fatalf("broken managed link was not restored: %s %v", target, err)
	}
	conflict := filepath.Join(opencodeSkills, "safe-skill")
	if err := os.MkdirAll(conflict, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(conflict, "SKILL.md"), []byte("local content"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, "opencode", "", "skill-1"); err == nil || !strings.Contains(err.Error(), "already has a different skill") {
		t.Fatalf("expected same-name conflict, got %v", err)
	}
	body, err := os.ReadFile(filepath.Join(conflict, "SKILL.md"))
	if err != nil || string(body) != "local content" {
		t.Fatalf("same-name conflict was overwritten: %q %v", body, err)
	}
}

func TestReconcileInstalledRecoveryCopiesArchivesExistingMatchingUninstall(t *testing.T) {
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	target := filepath.Join(home, ".hermes", "skills", "demo")
	writeSkill(t, target, "demo")
	item, err := QuarantineSkill(home, store, "hermes", "demo", target, "manual")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`UPDATE client_quarantine SET status='uninstalled' WHERE id=?`, item.ID); err != nil {
		t.Fatal(err)
	}
	quarantined, err := store.QuarantineItems()
	if err != nil || len(quarantined) != 1 {
		t.Fatal(quarantined, err)
	}
	content := []byte("---\nname: demo\ndescription: test\n---\n")
	if err := os.MkdirAll(target, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(target, "SKILL.md"), content, 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(content)
	if err := store.SaveInstall(Installation{
		AgentType: "hermes", SkillID: "skill-1", SkillName: "demo", TargetPath: target,
		Manifest: releaseManifest{
			ContentSignature: quarantined[0].Signature,
			Files:            []releaseFile{{Path: "SKILL.md", Size: int64(len(content)), SHA256: hex.EncodeToString(sum[:])}},
		},
	}); err != nil {
		t.Fatal(err)
	}
	changed, err := ReconcileInstalledRecoveryCopies(home, store)
	if err != nil || !changed {
		t.Fatalf("matching stale copy was not reconciled: %v %v", changed, err)
	}
	if remaining, err := store.QuarantineItems(); err != nil || len(remaining) != 0 {
		t.Fatalf("reconciled copy remains active: %#v %v", remaining, err)
	}
}

func TestManagedSymlinkTargetAcceptsCurrentAndLegacyTakeoverPaths(t *testing.T) {
	home := t.TempDir()
	manifest := releaseManifest{VersionID: "version-2", ContentSignature: "signature-1"}
	for _, target := range []string{
		filepath.Join(ManagedSkillsRoot(home), "skill-1", "release"),
		filepath.Join(ManagedSkillsRoot(home), "skill-1", "versions", "version-2", "release"),
		filepath.Join(ManagedSkillsRoot(home), "skill-1", "signature-1"),
		filepath.Join(legacyContentRoot(home, "skills"), "skill-1", "signature-1"),
	} {
		if err := os.MkdirAll(target, 0o755); err != nil {
			t.Fatal(err)
		}
		link := filepath.Join(t.TempDir(), "safe-skill")
		if err := os.Symlink(target, link); err != nil {
			t.Fatal(err)
		}
		resolved, ok := managedSymlinkTarget(home, Installation{
			SkillID: "skill-1", TargetPath: link, Manifest: manifest,
		})
		if !ok || filepath.Clean(resolved) != filepath.Clean(target) {
			t.Fatalf("managed target was rejected: target=%s resolved=%s", target, resolved)
		}
	}
}

func TestRemoveTaskRejectsAgentWithoutManagedSkillRoot(t *testing.T) {
	home := t.TempDir()
	sentinel := filepath.Join(home, "do-not-remove")
	if err := os.MkdirAll(sentinel, 0o755); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	inventory := Inventory{Agents: []Agent{{
		AgentType:                "unsupported-agent",
		SkillManagementSupported: false,
	}}}
	err = executeTask(
		context.Background(),
		home,
		inventory,
		Policy{},
		API{},
		store,
		Task{TaskType: "remove_skill", Payload: map[string]any{
			"agent_type": "unsupported-agent",
			"skill_id":   "skill-1",
			"skill_name": "do-not-remove",
		}},
	)
	if err == nil {
		t.Fatal("unsupported agent accepted a remove task")
	}
	if _, statErr := os.Stat(sentinel); statErr != nil {
		t.Fatal("remove task touched a path outside an Agent skill root")
	}
}

func TestRunOnceUsesCachedPolicyAndQueuesOfflineEvents(t *testing.T) {
	home := t.TempDir()
	target := filepath.Join(home, ".codex", "skills", "safe-skill")
	if err := os.MkdirAll(target, 0o755); err != nil {
		t.Fatal(err)
	}
	original := []byte("---\nname: safe-skill\n---\n")
	if err := os.WriteFile(filepath.Join(target, "SKILL.md"), original, 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(original)
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SaveInstall(Installation{
		AgentType: "codex", SkillID: "skill-1", SkillName: "safe-skill", TargetPath: target,
		Manifest: releaseManifest{Files: []releaseFile{{Path: "SKILL.md", Size: int64(len(original)), SHA256: hex.EncodeToString(sum[:])}}},
	}); err != nil {
		t.Fatal(err)
	}
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	policyBody, _ := json.Marshal(Policy{Mode: "block", GovernanceMode: "registry"})
	if err := store.SetState("policy", string(policyBody)); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(target, "SKILL.md"), []byte("tampered"), 0o644); err != nil {
		t.Fatal(err)
	}
	api := NewAPI("http://127.0.0.1:1", "token", 50*time.Millisecond)
	if err := RunOnce(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(target); !os.IsNotExist(err) {
		t.Fatalf("tampered skill was not quarantined: %v", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].Reason != "signature_mismatch" {
		t.Fatalf("unexpected quarantine state: %#v %v", items, err)
	}
	events, err := store.QueuedEvents()
	if err != nil || len(events) < 2 {
		t.Fatalf("offline events were not queued: %#v %v", events, err)
	}
}

func TestPatrolKeepsValidRegistrationWhenLegacyAliasSharesTarget(t *testing.T) {
	home := t.TempDir()
	versionID := "version-2"
	release := filepath.Join(ManagedSkillsRoot(home), versionID, "release")
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
	files := []releaseFile{{Path: "SKILL.md", Size: int64(len(content)), SHA256: hex.EncodeToString(sum[:])}}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	for index, install := range []Installation{
		{AgentType: "codex", SkillID: "family-1", SkillName: "safe", TargetPath: target, Manifest: releaseManifest{SkillID: "family-1", VersionID: versionID, Files: files}},
		{AgentType: "codex", SkillID: versionID, SkillName: "safe", TargetPath: target, Manifest: releaseManifest{SkillID: versionID, Files: files}},
	} {
		body, _ := json.Marshal(install.Manifest)
		if _, err := store.db.Exec(
			`INSERT INTO client_installs(agent_type, managed_agent_id, skill_id, skill_name, target_path, manifest_json, updated_at)
			 VALUES(?, '', ?, ?, ?, ?, ?)`,
			install.AgentType, install.SkillID, install.SkillName, install.TargetPath, string(body), time.Now().Add(time.Duration(index)*time.Second).Format(time.RFC3339Nano),
		); err != nil {
			t.Fatal(err)
		}
	}
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	inventory := Inventory{ClientID: "host", Agents: []Agent{{
		AgentType: "codex", SkillManagementSupported: true,
		Skills: []Skill{{Name: "safe", Path: target, Signature: "sig", Status: "managed"}},
	}}}
	if err := patrol(context.Background(), home, inventory, Policy{Mode: "block"}, API{}, store, true, false); err != nil {
		t.Fatal(err)
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 1 || installs[0].SkillID != versionID {
		t.Fatalf("valid registration was not retained: %#v %v", installs, err)
	}
	if quarantined, err := store.QuarantineItems(); err != nil || len(quarantined) != 0 {
		t.Fatalf("valid target was quarantined because of a stale alias: %#v %v", quarantined, err)
	}
}

func TestUnknownSkillIsComparedBeforeBlockModeQuarantine(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	home := t.TempDir()
	target := filepath.Join(home, ".codex", "skills", "local-skill")
	writeSkill(t, target, "local-skill")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SetState("governance_enabled", "1"); err != nil {
		t.Fatal(err)
	}
	allowed := true
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		switch {
		case strings.HasSuffix(request.URL.Path, "/heartbeat"):
			w.Write([]byte(`{"ok":true}`))
		case strings.HasSuffix(request.URL.Path, "/policy"):
			w.Write([]byte(`{"mode":"block","governance_mode":"registry","agent_bindings":{"codex":"bound-codex"}}`))
		case strings.HasSuffix(request.URL.Path, "/tasks"):
			w.Write([]byte(`[]`))
		case strings.HasSuffix(request.URL.Path, "/compare"):
			var payload struct {
				Agents []map[string]any `json:"agents"`
			}
			if err := json.NewDecoder(request.Body).Decode(&payload); err != nil {
				t.Fatal(err)
			}
			if len(payload.Agents) != 1 || payload.Agents[0]["managed_agent_id"] != "bound-codex" {
				t.Fatalf("platform Agent binding was not used: %#v", payload.Agents)
			}
			reason := "allowed"
			if !allowed {
				reason = "skill_not_approved"
			}
			json.NewEncoder(w).Encode(map[string]any{"items": []map[string]any{{
				"agent_type": "codex", "name": "local-skill", "local_path": target,
				"allowed": allowed, "reason": reason,
			}}})
		case strings.HasSuffix(request.URL.Path, "/events"), strings.HasSuffix(request.URL.Path, "/inventory"):
			w.Write([]byte(`{"ok":true}`))
		default:
			t.Fatalf("unexpected request %s", request.URL.Path)
		}
	}))
	defer server.Close()
	api := NewAPI(server.URL, "token", time.Second)
	if err := RunOnce(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(target); err != nil {
		t.Fatal("allowed unknown skill was quarantined:", err)
	}
	allowed = false
	if err := RunOnce(context.Background(), home, api, store); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(target); !os.IsNotExist(err) {
		t.Fatalf("denied unknown skill was not quarantined: %v", err)
	}
}

func TestSharedCleanupPreservesReplacedTargets(t *testing.T) {
	for _, replacement := range []string{"directory", "repointed", "expected", "absent"} {
		t.Run(replacement, func(t *testing.T) {
			home := t.TempDir()
			store, err := OpenStore(filepath.Join(home, "client.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			release := filepath.Join(home, "release")
			target := filepath.Join(home, "skill")
			other := filepath.Join(home, "user-content")
			if err := os.MkdirAll(other, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(other, "SKILL.md"), []byte("user edit"), 0o600); err != nil {
				t.Fatal(err)
			}
			switch replacement {
			case "directory":
				if err := os.Rename(other, target); err != nil {
					t.Fatal(err)
				}
			case "repointed":
				if err := os.Symlink(other, target); err != nil {
					t.Fatal(err)
				}
			case "expected":
				if err := os.Symlink("release", target); err != nil {
					t.Fatal(err)
				}
			}
			install := Installation{AgentType: "codex", SkillID: "skill-1", SkillName: "skill", TargetPath: target}
			if err := store.SaveInstall(install); err != nil {
				t.Fatal(err)
			}
			err = removeSharedInstalls(store, []Installation{install}, release)
			preserve := replacement == "directory" || replacement == "repointed"
			if preserve {
				if err == nil || err.Error() != "skill_content_changed" {
					t.Fatalf("expected content conflict, got %v", err)
				}
				content, readErr := os.ReadFile(filepath.Join(target, "SKILL.md"))
				if readErr != nil || string(content) != "user edit" {
					t.Fatalf("replacement lost: %q %v", content, readErr)
				}
			} else {
				if err != nil {
					t.Fatal(err)
				}
				if _, err := os.Lstat(target); !os.IsNotExist(err) {
					t.Fatalf("old link remains: %v", err)
				}
			}
			items, err := store.Installations()
			if err != nil {
				t.Fatal(err)
			}
			if (len(items) == 1) != preserve {
				t.Fatalf("unexpected installation records: %+v", items)
			}
		})
	}
}

func TestSharedSkillTamperCreatesOneQuarantine(t *testing.T) {
	home := t.TempDir()
	release := filepath.Join(home, ".agent-manager", "skills", "skill-1", "release")
	original := []byte("---\nname: shared-skill\n---\n")
	if err := os.MkdirAll(release, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(release, "SKILL.md"), original, 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(original)
	manifest := releaseManifest{
		SkillID: "skill-1", Name: "shared-skill",
		Files: []releaseFile{{Path: "SKILL.md", Size: int64(len(original)), SHA256: hex.EncodeToString(sum[:])}},
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	installs := []Installation{
		{AgentType: "claude-code", SkillID: "skill-1", SkillName: "shared-skill", TargetPath: filepath.Join(home, ".claude", "skills", "shared-skill"), Manifest: manifest},
		{AgentType: "codex", SkillID: "skill-1", SkillName: "shared-skill", TargetPath: filepath.Join(home, ".codex", "skills", "shared-skill"), Manifest: manifest},
	}
	for _, install := range installs {
		if err := os.MkdirAll(filepath.Dir(install.TargetPath), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(release, install.TargetPath); err != nil {
			t.Fatal(err)
		}
		if err := store.SaveInstall(install); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(release, "SKILL.md"), []byte("tampered"), 0o644); err != nil {
		t.Fatal(err)
	}
	api := NewAPI("http://127.0.0.1:1", "token", 20*time.Millisecond)
	if err := patrolLocalChanges(context.Background(), home, Inventory{ClientID: "host"}, Policy{Mode: "block"}, api, store, installs, true); err != nil {
		t.Fatal(err)
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 1 {
		t.Fatalf("shared content should create one quarantine: %#v %v", items, err)
	}
	if remaining, err := store.Installations(); err != nil || len(remaining) != 0 {
		t.Fatalf("shared references were not removed: %#v %v", remaining, err)
	}
	for _, install := range installs {
		if _, err := os.Lstat(install.TargetPath); !os.IsNotExist(err) {
			t.Fatalf("affected link still exists at %s: %v", install.TargetPath, err)
		}
	}
	notifications, err := store.Notifications(10)
	if err != nil || len(notifications) != 1 || !strings.Contains(notifications[0].Message, "Claude Code、Codex") {
		t.Fatalf("shared incident was not aggregated: %#v %v", notifications, err)
	}
}

func TestRepointedSharedLinkOnlyQuarantinesAffectedAgent(t *testing.T) {
	home := t.TempDir()
	release := filepath.Join(home, ".agent-manager", "skills", "skill-1", "release")
	repointed := filepath.Join(home, "other-release")
	content := []byte("---\nname: shared-skill\n---\n")
	for _, root := range []string{release, repointed} {
		if err := os.MkdirAll(root, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, "SKILL.md"), content, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	sum := sha256.Sum256(content)
	manifest := releaseManifest{
		SkillID: "skill-1", Name: "shared-skill",
		Files: []releaseFile{{Path: "SKILL.md", Size: int64(len(content)), SHA256: hex.EncodeToString(sum[:])}},
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	installs := []Installation{
		{AgentType: "claude-code", SkillID: "skill-1", SkillName: "shared-skill", TargetPath: filepath.Join(home, ".claude", "skills", "shared-skill"), Manifest: manifest},
		{AgentType: "codex", SkillID: "skill-1", SkillName: "shared-skill", TargetPath: filepath.Join(home, ".codex", "skills", "shared-skill"), Manifest: manifest},
	}
	for _, install := range installs {
		if err := os.MkdirAll(filepath.Dir(install.TargetPath), 0o755); err != nil {
			t.Fatal(err)
		}
		target := release
		if install.AgentType == "codex" {
			target = repointed
		}
		if err := os.Symlink(target, install.TargetPath); err != nil {
			t.Fatal(err)
		}
		if err := store.SaveInstall(install); err != nil {
			t.Fatal(err)
		}
	}
	api := NewAPI("http://127.0.0.1:1", "token", 20*time.Millisecond)
	if err := patrolLocalChanges(context.Background(), home, Inventory{ClientID: "host"}, Policy{Mode: "block"}, api, store, installs, true); err != nil {
		t.Fatal(err)
	}
	remaining, err := store.Installations()
	if err != nil || len(remaining) != 1 || remaining[0].AgentType != "claude-code" {
		t.Fatalf("healthy shared reference was affected: %#v %v", remaining, err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 1 || items[0].AgentType != "codex" {
		t.Fatalf("repointed link was not isolated independently: %#v %v", items, err)
	}
	if _, err := os.Stat(release); err != nil {
		t.Fatalf("shared release was removed: %v", err)
	}
}

func signedPackage(t *testing.T, privateKey ed25519.PrivateKey) []byte {
	return signedPackageFor(t, privateKey, "safe-skill")
}

func signedPackageFor(t *testing.T, privateKey ed25519.PrivateKey, name string) []byte {
	t.Helper()
	content := []byte("---\nname: " + name + "\n---\n")
	sum := sha256.Sum256(content)
	contentSignature := sha256.Sum256([]byte("SKILL.md:" + hex.EncodeToString(sum[:]) + "\n"))
	manifest := map[string]any{
		"version":           1,
		"skill_id":          "skill-1",
		"name":              name,
		"content_signature": hex.EncodeToString(contentSignature[:]),
		"files": []map[string]any{{
			"path": "SKILL.md", "size": len(content), "sha256": hex.EncodeToString(sum[:]),
		}},
	}
	manifestBody, _ := json.Marshal(manifest)
	var body bytes.Buffer
	archive := zip.NewWriter(&body)
	writeZip(t, archive, "manifest.json", manifestBody)
	writeZip(t, archive, "manifest.sig", []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, manifestBody))))
	writeZip(t, archive, "skill/SKILL.md", content)
	if err := archive.Close(); err != nil {
		t.Fatal(err)
	}
	return body.Bytes()
}
