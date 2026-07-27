package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

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
			for _, field := range []string{"use_behavioral", "use_skillspector", "use_deep_scan", "use_sandbox", "use_llm", "no_cache"} {
				if request.FormValue(field) != "true" {
					t.Errorf("%s was not enabled", field)
				}
			}
			_ = json.NewEncoder(response).Encode(map[string]any{"skill_id": "skill-1", "name": "demo", "status": "PENDING"})
			return
		}
		getCount++
		_ = json.NewEncoder(response).Encode(map[string]any{"skill_id": "skill-1", "name": "demo", "status": "APPROVED"})
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
		if pending.SkillID != "skill-1" || pending.Status != "submitted" {
			t.Fatalf("duplicate pending Skill did not share submission: %#v", submitted)
		}
	}
	items, err := RefreshPending(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 2 || items[0].Status != "APPROVED" || items[1].Status != "APPROVED" {
		t.Fatalf("pending result was not refreshed: %#v", items)
	}
	if getCount != 1 {
		t.Fatalf("same platform Skill status was queried %d times", getCount)
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
