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
	"sync/atomic"
	"testing"
	"time"
)

func TestReconcileApprovedPendingAutomaticallyInstallsExactVersion(t *testing.T) {
	testApprovedPendingInstallation(t, false, "mismatch")
}

func TestLegacyPendingInstallsIntoAssociatedAgent(t *testing.T) {
	testApprovedPendingInstallation(t, true, "mismatch")
}

func TestApprovedQuarantineRestoresLocalCopyWithoutDownload(t *testing.T) {
	testApprovedPendingInstallation(t, false, "match")
}

func TestApprovedQuarantineMissingCopyDownloads(t *testing.T) {
	testApprovedPendingInstallation(t, false, "missing")
}

func TestApprovedQuarantineLocalCopyRequiresAuthorization(t *testing.T) {
	testApprovedPendingInstallation(t, false, "denied")
}

func TestApprovedQuarantineCompareFailureDoesNotDownload(t *testing.T) {
	testApprovedPendingInstallation(t, false, "offline")
}

func TestApprovedQuarantineCopyChangedAfterCompareDownloads(t *testing.T) {
	testApprovedPendingInstallation(t, false, "changed")
}

func testApprovedPendingInstallation(t *testing.T, legacy bool, localCopy string) {
	t.Helper()
	home := t.TempDir()
	skillsRoot := filepath.Join(home, ".codex", "skills")
	source := filepath.Join(skillsRoot, "safe-skill")
	writeSkill(t, source, "safe-skill")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	quarantined, err := QuarantineSkill(home, store, "codex", "safe-skill", source, "skill_modified")
	if err != nil {
		t.Fatal(err)
	}
	pending, err := QueueQuarantineForDetection(home, store, quarantined.ID)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.MarkPendingSubmitted(pending, "skill-1", "skill-version-2"); err != nil {
		t.Fatal(err)
	}
	if legacy {
		if _, err := store.db.Exec(`UPDATE client_pending SET original_path='', reason='legacy_pending' WHERE id=?`, pending.ID); err != nil {
			t.Fatal(err)
		}
	}
	status := "REJECTED"
	if legacy {
		status = "PENDING"
	}
	if err := store.UpdatePendingStatus("skill-1", "skill-version-2", status); err != nil {
		t.Fatal(err)
	}

	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackage(t, privateKey)
	snapshot, err := inspectInstallTarget(pending.PendingPath)
	if err != nil {
		t.Fatal(err)
	}
	if localCopy == "missing" {
		if err := os.RemoveAll(pending.PendingPath); err != nil {
			t.Fatal(err)
		}
	}
	packageRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch {
		case strings.HasSuffix(request.URL.Path, "/compare"):
			if localCopy == "offline" {
				response.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			verdict := CompareItem{AgentType: "codex", LocalPath: source, LocalSignature: snapshot.signature,
				SkillID: "skill-1", VersionID: "skill-version-2", Reason: "signature_mismatch"}
			if localCopy == "match" || localCopy == "denied" || localCopy == "changed" {
				verdict.Certified, verdict.Allowed = true, true
				verdict.ExpectedSignature, verdict.Reason = snapshot.signature, "allowed"
			}
			if localCopy == "denied" {
				verdict.Allowed, verdict.Reason = false, "agent_not_authorized"
			}
			if localCopy == "changed" {
				if err := os.WriteFile(filepath.Join(pending.PendingPath, "SKILL.md"), []byte("changed"), 0600); err != nil {
					t.Error(err)
				}
			}
			_ = json.NewEncoder(response).Encode(map[string]any{"items": []CompareItem{verdict}})
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/scanner/imports/skill-version-2":
			_ = json.NewEncoder(response).Encode(map[string]any{
				"skill_id": "skill-1", "version_id": "skill-version-2", "name": "safe-skill", "status": "APPROVED",
			})
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/clients/client-1/skills/skill-1/package":
			packageRequests++
			if got := request.URL.Query().Get("version_id"); got != "skill-version-2" {
				t.Errorf("installed version %q instead of submitted version", got)
			}
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

	inventory := Inventory{
		ClientID: "client-1",
		Agents: []Agent{{
			AgentType: "codex", SkillsPath: skillsRoot, SkillManagementSupported: true,
		}},
	}
	policy := Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey)}
	changed, err := ReconcileApprovedPending(
		context.Background(), home, NewAPI(server.URL, "token", 5*time.Second), store, inventory, policy,
	)
	if err != nil {
		t.Fatal(err)
	}
	if localCopy == "denied" || localCopy == "offline" {
		lastError, _, _ := store.State("pending:install-error:" + pending.ID)
		if changed || packageRequests != 0 || lastError == "" {
			t.Fatalf("failed authorization must remain pending without download: %v %d %q", changed, packageRequests, lastError)
		}
		if _, err := os.Lstat(source); !os.IsNotExist(err) {
			t.Fatalf("unauthorized content was restored: %v", err)
		}
		return
	}
	wantDownloads := 1
	if localCopy == "match" {
		wantDownloads = 0
	}
	if !changed || packageRequests != wantDownloads {
		lastError, _, _ := store.State("pending:install-error:" + pending.ID)
		t.Fatalf("approved pending Skill was not installed exactly once: changed=%v requests=%d error=%s", changed, packageRequests, lastError)
	}
	if entries, err := os.ReadDir(filepath.Join(DataRoot(home), "staging")); err != nil || len(entries) != 0 {
		t.Fatalf("installation staging not cleaned: %v %v", entries, err)
	}
	if items, err := store.PendingItems(); err != nil || len(items) != 0 {
		t.Fatalf("installed pending record was not cleared: %#v %v", items, err)
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 0 {
		t.Fatalf("installed Skill was not released from quarantine: %#v %v", items, err)
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 1 || !verifyInstalled(installs[0]) {
		t.Fatalf("restored installation has no valid integrity baseline: %#v %v", installs, err)
	}
	if _, err := filepath.EvalSymlinks(filepath.Join(skillsRoot, "safe-skill")); err != nil {
		t.Fatalf("trusted Skill was not restored to the Agent: %v", err)
	}
	fresh, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.EnrichInventory(&fresh); err != nil {
		t.Fatal(err)
	}
	codex, ok := findAgent(fresh, "codex")
	if !ok || len(codex.Skills) != 1 {
		t.Fatalf("installed Skill was not rediscovered under Codex: %#v", fresh.Agents)
	}
	if codex.Skills[0].Status != "managed" || codex.Skills[0].SkillID != "skill-1" {
		t.Fatalf("rediscovered Skill was not enriched as managed: %#v", codex.Skills[0])
	}
	notifications, err := store.Notifications(10)
	if err != nil || len(notifications) == 0 || notifications[0].EventType != "skill_auto_installed" {
		t.Fatalf("automatic install notification was not recorded: %#v %v", notifications, err)
	}
}

func TestSubmitAndRefreshPendingUsesFullDetection(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "demo")
	duplicatePath := filepath.Join(home, ".agent-manager", "pending", "claude-code", "demo")
	writeSkill(t, pendingPath, "demo")
	writeSkill(t, duplicatePath, "demo")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	item := PendingItem{ID: "pending-1", AgentType: "codex", SkillName: "demo", PendingPath: pendingPath, Reason: "skill_not_found"}
	if err := store.SavePending(item); err != nil {
		t.Fatal(err)
	}
	if err := store.SavePending(PendingItem{ID: "pending-2", AgentType: "claude-code", SkillName: "demo", PendingPath: duplicatePath, Reason: "skill_not_found"}); err != nil {
		t.Fatal(err)
	}

	getCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Method == http.MethodPost {
			if err := request.ParseMultipartForm(10 << 20); err != nil {
				t.Error(err)
				response.WriteHeader(http.StatusBadRequest)
				return
			}
			for _, field := range []string{"use_behavioral", "use_skillspector", "use_deep_scan", "use_sandbox", "use_llm"} {
				if request.FormValue(field) != "true" {
					t.Errorf("%s was not enabled", field)
				}
			}
			var submitted struct {
				Name        string `json:"name"`
				Fingerprint string `json:"fingerprint"`
				Files       []any  `json:"files"`
			}
			if err := json.Unmarshal([]byte(request.FormValue("manifest")), &submitted); err != nil || submitted.Name != "demo" || submitted.Fingerprint == "" || len(submitted.Files) != 0 {
				t.Errorf("invalid compact submission manifest: %+v, %v", submitted, err)
			}
			if _, exists := request.MultipartForm.Value["no_cache"]; exists {
				t.Errorf("no_cache must be controlled only by the platform global policy")
			}
			_ = json.NewEncoder(response).Encode(map[string]any{
				"skill_id": "skill-family-1", "version_id": "skill-version-2", "version_no": 2, "source_version": "1.4.0", "name": "demo", "status": "PENDING",
			})
			return
		}
		if request.URL.Path != "/api/v1/scanner/imports/skill-version-2" {
			t.Errorf("status was read from the family instead of the submitted version: %s", request.URL.Path)
		}
		getCount++
		_ = json.NewEncoder(response).Encode(map[string]any{
			"skill_id": "skill-family-1", "version_id": "skill-version-2", "version_no": 2, "source_version": "1.4.0", "name": "demo", "status": "APPROVED",
		})
	}))
	defer server.Close()

	if _, err := SubmitPending(context.Background(), home, server.URL, "token", store, item.ID); err != nil {
		t.Fatal(err)
	}
	submitted, err := store.PendingItems()
	if err != nil {
		t.Fatal(err)
	}
	for _, pending := range submitted {
		if pending.SkillID != "skill-family-1" || pending.VersionID != "skill-version-2" || pending.VersionNo != 2 || pending.SourceVersion != "1.4.0" || pending.Status != "submitted" {
			t.Fatalf("duplicate pending Skill did not share submission: %#v", submitted)
		}
	}
	items, err := RefreshPending(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 2 || items[0].Status != "APPROVED" || items[1].Status != "APPROVED" || items[0].VersionNo != 2 || items[1].VersionNo != 2 {
		t.Fatalf("pending result was not refreshed: %#v", items)
	}
	if getCount != 1 {
		t.Fatalf("same platform Skill status was queried %d times", getCount)
	}
}

func TestManualRefreshRechecksRejectedVersionAfterPlatformRescan(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "understand-domain")
	writeSkill(t, pendingPath, "understand-domain")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	item := PendingItem{
		ID: "pending-1", AgentType: "codex", SkillName: "understand-domain",
		PendingPath: pendingPath, Status: "REJECTED",
		SkillID: "family-1", VersionID: "version-1",
	}
	if err := store.SavePending(item); err != nil {
		t.Fatal(err)
	}
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		requests++
		if request.URL.Path != "/api/v1/scanner/imports/version-1" {
			t.Errorf("unexpected status path: %s", request.URL.Path)
		}
		_ = json.NewEncoder(response).Encode(map[string]any{
			"skill_id": "version-1", "name": "understand-domain", "status": "APPROVED",
		})
	}))
	defer server.Close()

	items, err := RefreshPending(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if requests != 0 || len(items) != 1 || items[0].Status != "REJECTED" {
		t.Fatalf("background refresh should preserve terminal result: requests=%d items=%#v", requests, items)
	}
	items, err = RefreshPendingIncludingTerminal(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if requests != 1 || len(items) != 1 || items[0].Status != "APPROVED" {
		t.Fatalf("manual refresh did not observe platform approval: requests=%d items=%#v", requests, items)
	}
}

func TestManualRefreshDetachesSubmissionMissingFromCurrentPlatform(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "old-skill")
	writeSkill(t, pendingPath, "old-skill")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{
		ID: "old-pending", AgentType: "codex", SkillName: "old-skill",
		PendingPath: pendingPath, Status: "REJECTED",
		SkillID: "old-family", VersionID: "old-version", SubmittedAt: "2026-08-01T00:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		http.Error(response, `{"detail":"Skill not found"}`, http.StatusNotFound)
	}))
	defer server.Close()

	items, err := RefreshPendingIncludingTerminal(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Status != "pending" || items[0].SkillID != "" || items[0].VersionID != "" || items[0].SubmittedAt != "" {
		t.Fatalf("missing platform submission was not detached: %#v", items)
	}
}

func TestManualRefreshDetachesSubmissionOwnedByDifferentScannerToken(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "old-skill")
	writeSkill(t, pendingPath, "old-skill")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{
		ID: "old-pending", AgentType: "codex", SkillName: "old-skill",
		PendingPath: pendingPath, Status: "PENDING",
		SkillID: "old-family", VersionID: "old-version", SubmittedAt: "2026-08-01T00:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusForbidden)
		_, _ = response.Write([]byte(`{"detail":"scanner token can only read own submissions","error_code":"http.403","error_params":{}}`))
	}))
	defer server.Close()

	items, err := RefreshPendingIncludingTerminal(context.Background(), server.URL, "new-token", store)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Status != "pending" || items[0].SkillID != "" || items[0].VersionID != "" || items[0].SubmittedAt != "" {
		t.Fatalf("submission owned by another token was not detached: %#v", items)
	}
}

func TestManualRefreshKeepsSubmissionOnUnrelatedForbidden(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "current-skill")
	writeSkill(t, pendingPath, "current-skill")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{
		ID: "current-pending", AgentType: "codex", SkillName: "current-skill",
		PendingPath: pendingPath, Status: "PENDING",
		SkillID: "current-family", VersionID: "current-version", SubmittedAt: "2026-08-04T00:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusForbidden)
		_, _ = response.Write([]byte(`{"detail":"missing required scope","error_code":"auth.permission_denied","error_params":{}}`))
	}))
	defer server.Close()

	if _, err := RefreshPendingIncludingTerminal(context.Background(), server.URL, "bad-token", store); err == nil {
		t.Fatal("unrelated authorization failure was silently detached")
	}
	items, err := store.PendingItems()
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].SkillID != "current-family" || items[0].VersionID != "current-version" {
		t.Fatalf("unrelated authorization failure changed submission linkage: %#v", items)
	}
}

func TestSubmitPendingDoesNotLinkSameNameWithDifferentContent(t *testing.T) {
	home := t.TempDir()
	firstPath := filepath.Join(home, ".agent-manager", "pending", "codex", "demo")
	secondPath := filepath.Join(home, ".agent-manager", "pending", "claude-code", "demo")
	writeSkill(t, firstPath, "demo")
	writeSkill(t, secondPath, "demo")
	if err := os.WriteFile(filepath.Join(secondPath, "extra.txt"), []byte("different content"), 0o600); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{ID: "pending-1", AgentType: "codex", SkillName: "demo", PendingPath: firstPath, Reason: "skill_not_found"}); err != nil {
		t.Fatal(err)
	}
	if err := store.SavePending(PendingItem{ID: "pending-2", AgentType: "claude-code", SkillName: "demo", PendingPath: secondPath, Reason: "skill_not_found"}); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		_ = json.NewEncoder(response).Encode(map[string]any{"skill_id": "skill-1", "name": "demo", "status": "PENDING"})
	}))
	defer server.Close()
	if _, err := SubmitPending(context.Background(), home, server.URL, "token", store, "pending-1"); err != nil {
		t.Fatal(err)
	}

	items, err := store.PendingItems()
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range items {
		if item.ID == "pending-2" && item.SkillID != "" {
			t.Fatalf("same-name Skill with different content was linked: %#v", item)
		}
	}
}

func TestRefreshPendingDoesNotFingerprintUnsubmittedItems(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "demo")
	writeSkill(t, pendingPath, "demo")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{
		ID: "pending-1", AgentType: "codex", SkillName: "demo",
		PendingPath: pendingPath, Reason: "skill_not_found",
	}); err != nil {
		t.Fatal(err)
	}

	items, err := RefreshPending(context.Background(), "http://unused.invalid", "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Fingerprint != "" {
		t.Fatalf("status refresh should not scan unsubmitted Skill files: %#v", items)
	}
}

func TestSubmitPendingRejectsEmptyDirectoryBeforeUpload(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "empty")
	if err := os.MkdirAll(pendingPath, 0o700); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SavePending(PendingItem{
		ID: "pending-empty", AgentType: "codex", SkillName: "empty",
		PendingPath: pendingPath, Reason: "legacy_pending",
	}); err != nil {
		t.Fatal(err)
	}

	_, err = SubmitPending(context.Background(), home, "http://unused.invalid", "token", store, "pending-empty")
	if err == nil || !strings.Contains(err.Error(), "缺少 SKILL.md") {
		t.Fatalf("expected a clear local validation error, got %v", err)
	}
}

func TestClientIDForHomeDoesNotRequireDiscovery(t *testing.T) {
	home := filepath.Join(t.TempDir(), "missing-home")
	hostname, _ := os.Hostname()
	if got, want := clientIDForHome(home), DeviceID(hostname, home); got != want {
		t.Fatalf("unexpected client ID: got %q want %q", got, want)
	}
}

func TestDaemonAutomaticallyInstallsApprovedPendingWithClassification(t *testing.T) {
	home := t.TempDir()
	skillsRoot := filepath.Join(home, ".codex", "skills")
	source := filepath.Join(skillsRoot, "safe-skill")
	writeSkill(t, source, "safe-skill")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	quarantined, err := QuarantineSkill(home, store, "codex", "safe-skill", source, "skill_modified")
	if err != nil {
		t.Fatal(err)
	}
	pending, err := QueueQuarantineForDetection(home, store, quarantined.ID)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.MarkPendingSubmitted(pending, "skill-1", "skill-version-2"); err != nil {
		t.Fatal(err)
	}
	if err := store.UpdatePendingStatus("skill-1", "skill-version-2", "PENDING"); err != nil {
		t.Fatal(err)
	}

	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackage(t, privateKey)
	var packageRequests atomic.Int32
	var platformApproved atomic.Bool
	var approvedAt atomic.Int64
	var taskPolls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch {
		case request.Method == http.MethodGet && request.URL.Path == "/api/v1/scanner/imports/skill-version-2":
			status := "PENDING"
			if platformApproved.Load() {
				status = "APPROVED"
			}
			_ = json.NewEncoder(response).Encode(map[string]any{
				"skill_id": "skill-1", "version_id": "skill-version-2", "name": "safe-skill", "status": status,
			})
		case request.Method == http.MethodGet && strings.HasSuffix(request.URL.Path, "/skills/skill-1/package"):
			packageRequests.Add(1)
			if got := request.URL.Query().Get("version_id"); got != "skill-version-2" {
				t.Errorf("installed version %q instead of submitted version", got)
			}
			response.Header().Set("Content-Type", "application/zip")
			_, _ = response.Write(packageBody)
		case strings.HasSuffix(request.URL.Path, "/heartbeat"):
			json.NewEncoder(response).Encode(map[string]any{"policy": Policy{Mode: "audit", ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey), Classification: DefaultClassificationPolicy()}})
		case strings.HasSuffix(request.URL.Path, "/policy"):
			json.NewEncoder(response).Encode(Policy{Mode: "audit", ReleasePublicKey: base64.StdEncoding.EncodeToString(publicKey), Classification: DefaultClassificationPolicy()})
		case strings.HasSuffix(request.URL.Path, "/tasks"):
			if taskPolls.Add(1) == 2 {
				approvedAt.Store(time.Now().UnixNano())
				platformApproved.Store(true)
				response.Write([]byte(`{"tasks":[],"scan_events":[{"revision":1,"skill_id":"skill-1","version_id":"skill-version-2","status":"APPROVED"}]}`))
			} else {
				response.Write([]byte(`{"tasks":[],"scan_events":[]}`))
			}
		case strings.HasSuffix(request.URL.Path, "/compare"):
			var body struct {
				Agents []Agent `json:"agents"`
			}
			_ = json.NewDecoder(request.Body).Decode(&body)
			var verdicts []CompareItem
			for _, agent := range body.Agents {
				for _, skill := range agent.Skills {
					verdicts = append(verdicts, CompareItem{AgentType: agent.AgentType, LocalPath: skill.Path, LocalSignature: skill.Signature, Reason: "signature_mismatch"})
				}
			}
			_ = json.NewEncoder(response).Encode(map[string]any{"items": verdicts})
		case request.Method == http.MethodPost:
			response.WriteHeader(http.StatusNoContent)
		default:
			t.Errorf("unexpected request: %s %s", request.Method, request.URL.String())
			response.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()

	// Measure approval wakeup with an available inventory, independently of cold discovery.
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SaveInventory(inventory); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- RunDaemon(ctx, home, NewAPI(server.URL, "token", time.Second), store, 5*time.Minute, nil)
	}()
	defer func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(5 * time.Second):
			t.Error("daemon did not stop")
		}
	}()
	deadline := time.Now().Add(5 * time.Second)
	for {
		items, err := store.PendingItems()
		if err != nil {
			t.Fatal(err)
		}
		if len(items) == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("daemon never installed approved Skill", items)
		}
		time.Sleep(20 * time.Millisecond)
	}
	if packageRequests.Load() != 1 {
		t.Fatal("unexpected installation count", packageRequests.Load())
	}
	if elapsed := time.Since(time.Unix(0, approvedAt.Load())); elapsed >= 2*time.Second {
		t.Fatalf("event-driven recovery waited for巡检 interval: %s", elapsed)
	}
	if revision, ok, err := store.State("platform:scan-revision"); err != nil || !ok || revision != "1" {
		t.Fatalf("platform scan revision was not persisted: %q %v %v", revision, ok, err)
	}

	if items, err := store.PendingItems(); err != nil || len(items) != 0 {
		t.Fatalf("installed pending record was not cleared: %#v %v", items, err)
	}
	if items, err := store.QuarantineItems(); err != nil || len(items) != 0 {
		t.Fatalf("installed Skill was not released from quarantine: %#v %v", items, err)
	}
	if _, err := filepath.EvalSymlinks(filepath.Join(skillsRoot, "safe-skill")); err != nil {
		t.Fatalf("trusted Skill was not restored to the Agent: %v", err)
	}
	fresh, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.EnrichInventory(&fresh); err != nil {
		t.Fatal(err)
	}
	codex, ok := findAgent(fresh, "codex")
	if !ok || len(codex.Skills) != 1 {
		t.Fatalf("installed Skill was not rediscovered under Codex: %#v", fresh.Agents)
	}
	if codex.Skills[0].Status != "managed" || codex.Skills[0].SkillID != "skill-1" {
		t.Fatalf("rediscovered Skill was not enriched as managed: %#v", codex.Skills[0])
	}
	notifications, err := store.Notifications(10)
	// Removing the pending row precedes recording the final notification.
	for err == nil && len(notifications) == 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
		notifications, err = store.Notifications(10)
	}
	if err != nil || len(notifications) == 0 || notifications[0].EventType != "skill_auto_installed" {
		t.Fatalf("automatic install notification was not recorded: %#v %v", notifications, err)
	}
}

func TestAutomaticInstallBindsOriginalRootAndCurrentContent(t *testing.T) {
	for _, scenario := range []string{"secondary", "unchanged", "skillhub_alias", "edited", "changed_during_download", "removed_root"} {
		t.Run(scenario, func(t *testing.T) {
			home := t.TempDir()
			root := filepath.Join(home, "secondary")
			source := filepath.Join(root, "safe-skill")
			if scenario == "skillhub_alias" {
				source += "__skillhub"
			}
			snapshot := filepath.Join(home, "snapshot")
			os.MkdirAll(snapshot, 0700)
			os.WriteFile(filepath.Join(snapshot, "SKILL.md"), []byte("---\nname: safe-skill\n---\n"), 0600)
			if scenario == "unchanged" || scenario == "skillhub_alias" || scenario == "edited" || scenario == "changed_during_download" {
				os.MkdirAll(source, 0700)
				content := []byte("---\nname: safe-skill\n---\n")
				if scenario == "edited" {
					content = []byte("new user content")
				}
				os.WriteFile(filepath.Join(source, "SKILL.md"), content, 0600)
			}
			public, private, _ := ed25519.GenerateKey(rand.Reader)
			body := signedPackage(t, private)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasSuffix(r.URL.Path, "/package") {
					if scenario == "changed_during_download" {
						os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("new user content"), 0600)
					}
					w.Write(body)
				} else {
					w.Write([]byte(`{}`))
				}
			}))
			defer server.Close()
			store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			roots := []any{filepath.Join(home, "primary"), root}
			if scenario == "removed_root" {
				roots = roots[:1]
			}
			inventory := Inventory{ClientID: "host", Agents: []Agent{{AgentType: "codex", SkillsPath: filepath.Join(home, "primary"), SkillManagementSupported: true, Capabilities: map[string]any{"skill_roots": roots}}}}
			item := PendingItem{ID: "pending", AgentType: "codex", SkillName: "safe-skill", OriginalPath: source, PendingPath: snapshot, SkillID: "skill-1", Status: "APPROVED"}
			if err := store.SavePending(item); err != nil {
				t.Fatal(err)
			}
			changed, err := ReconcileApprovedPending(context.Background(), home, NewAPI(server.URL, "token", time.Second), store, inventory, Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(public), Classification: DefaultClassificationPolicy()})
			if err != nil {
				t.Fatal(err)
			}
			if scenario == "skillhub_alias" {
				if items, err := store.PendingItems(); err != nil || len(items) != 0 {
					t.Fatalf("alias installation left a pending retry: %#v, %v", items, err)
				}
				if _, err := os.Lstat(filepath.Join(root, "safe-skill")); !os.IsNotExist(err) {
					t.Fatal("installed a duplicate under the package name")
				}
				installs, err := store.Installations()
				if err != nil || len(installs) != 1 || installs[0].TargetPath != source || installs[0].SkillName != "safe-skill" {
					t.Fatalf("wrong installation: %#v, %v", installs, err)
				}
			}
			if scenario == "secondary" || scenario == "unchanged" || scenario == "skillhub_alias" {
				if !changed {
					t.Fatal("approved content not installed")
				}
				if _, err := os.Stat(filepath.Join(source, "SKILL.md")); err != nil {
					t.Fatal(err)
				}
				if _, err := os.Stat(filepath.Join(home, "primary", "safe-skill")); !os.IsNotExist(err) {
					t.Fatal("installed in wrong root")
				}
			} else {
				if changed {
					t.Fatal("conflicting target overwritten")
				}
				items, err := store.PendingItems()
				if err != nil || len(items) != 1 || items[0].AutoInstallError == "" {
					t.Fatal("failure not visible", items, err)
				}
				if scenario != "removed_root" {
					body, _ := os.ReadFile(filepath.Join(source, "SKILL.md"))
					if string(body) != "new user content" {
						t.Fatal("user edit overwritten")
					}
				}
			}
		})
	}
}

func TestLegacyPendingWithMultipleRootsKeepsCopy(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	inventory.Agents[0].Capabilities = map[string]any{"skill_roots": []string{filepath.Dir(skill.Path), filepath.Join(home, "other-skills")}}
	item := PendingItem{ID: "legacy", AgentType: inventory.Agents[0].AgentType, SkillName: skill.Name, PendingPath: skill.Path, Reason: "legacy_pending", Status: "APPROVED"}
	if err := store.SavePending(item); err != nil {
		t.Fatal(err)
	}
	err := installApprovedPending(context.Background(), home, inventory, Policy{}, API{}, store, item, "")
	if err == nil || err.Error() != "skill_target_unavailable" {
		t.Fatal(err)
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal(err)
	}
	var original string
	if err := store.db.QueryRow(`SELECT original_path FROM client_pending WHERE id='legacy'`).Scan(&original); err != nil || original != "" {
		t.Fatal(original, err)
	}
}
