package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func TestSubmitAndRefreshPendingUsesFullDetection(t *testing.T) {
	home := t.TempDir()
	pendingPath := filepath.Join(home, ".agent-manager", "pending", "codex", "demo")
	writeSkill(t, pendingPath, "demo")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	item := PendingItem{ID: "pending-1", AgentType: "codex", SkillName: "demo", PendingPath: pendingPath, Reason: "skill_not_found"}
	if err := store.SavePending(item); err != nil {
		t.Fatal(err)
	}

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
		_ = json.NewEncoder(response).Encode(map[string]any{"skill_id": "skill-1", "name": "demo", "status": "APPROVED"})
	}))
	defer server.Close()

	if _, err := SubmitPending(context.Background(), home, server.URL, "token", store, item.ID); err != nil {
		t.Fatal(err)
	}
	items, err := RefreshPending(context.Background(), server.URL, "token", store)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Status != "APPROVED" {
		t.Fatalf("pending result was not refreshed: %#v", items)
	}
}
