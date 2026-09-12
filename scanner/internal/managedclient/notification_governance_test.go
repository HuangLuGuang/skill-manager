package managedclient

import (
	"path/filepath"
	"testing"
)

func TestClassificationNotificationsPreserveCurrentContentAndActionResult(t *testing.T) {
	database := filepath.Join(t.TempDir(), "client.db")
	store, err := OpenStore(database)
	if err != nil {
		t.Fatal(err)
	}
	details := map[string]any{"path": "/skills/sample", "signature": "first", "trigger": "unverified", "action": "record", "policy_version": "1:0"}
	record := func(event string) {
		t.Helper()
		item, ok := notificationForEvent(event, "codex", "sample", details)
		if !ok {
			t.Fatal("classification event omitted")
		}
		if err := store.RecordNotification(item); err != nil {
			t.Fatal(err)
		}
	}
	record("skill_governance_detected")
	details["observation_count"] = 5
	details["last_seen_at"] = "later"
	record("skill_governance_detected")
	details["signature"] = "second"
	details["trigger"] = "malicious"
	record("skill_governance_detected")
	details["action"] = "quarantine"
	details["status"] = "failed"
	details["error_code"] = "skill_content_changed"
	record("skill_governance_action")
	details["status"] = "completed"
	details["error_code"] = ""
	record("skill_governance_action")
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = OpenStore(database)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	items, err := store.PendingNotifications(20)
	if err != nil || len(items) != 4 {
		t.Fatal("notification dedup or persistence failed", items, err)
	}
	if items[0].Severity != "warning" || items[1].Severity != "critical" || items[2].Severity != "critical" {
		t.Fatal("incorrect notification severity", items)
	}
	if items[2].Details["status"] != "failed" || items[2].Details["error_code"] != "skill_content_changed" || items[3].Details["status"] != "completed" {
		t.Fatal("action results were coalesced", items)
	}
	listed, err := store.Notifications(20)
	if err != nil || len(listed) != 4 || listed[0].Details["signature"] != "second" {
		t.Fatal("notification list lost content binding", listed, err)
	}
}
