package managedclient

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestTaskRequiresPlatformAcceptanceBeforeFileAction(t *testing.T) {
	for _, scenario := range []struct {
		name, response, status string
		httpStatus             int
	}{
		{"cancelled", `{"ok":true,"ignored":true,"status":"cancelled"}`, "cancelled", 200},
		{"completed", `{"ok":true,"ignored":true,"status":"succeeded"}`, "succeeded", 200},
		{"offline", `{"detail":"unavailable"}`, "pending", 503},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			home, store, inventory, skill := observedFixture(t)
			task := Task{ID: 21, TaskType: "skill_action", Payload: map[string]any{"action": "quarantine", "agent_type": "codex", "path": skill.Path, "expected_signature": skill.Signature}}
			if err := store.SaveTask(task, "pending", ""); err != nil {
				t.Fatal(err)
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(scenario.httpStatus)
				w.Write([]byte(scenario.response))
			}))
			defer server.Close()
			err := executeTasks(context.Background(), home, inventory, Policy{}, NewAPI(server.URL, "token", time.Second), store, []Task{task})
			if (err != nil) != (scenario.httpStatus != 200) {
				t.Fatal("unexpected claim result", err)
			}
			if err := checkObservedContent(skill); err != nil {
				t.Fatal("unaccepted task changed files", err)
			}
			items, err := store.QuarantineItems()
			if err != nil || len(items) != 0 {
				t.Fatal("unaccepted task created recovery records", items, err)
			}
			history, err := store.TaskHistory(1)
			if err != nil || len(history) != 1 || history[0].Status != scenario.status {
				t.Fatal("task state mismatch", history, err)
			}
		})
	}
}
