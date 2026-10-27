package managedclient

import (
	"errors"
	"testing"
)

func TestSyncStateSkipsUnchangedErrorsAndRefreshesSuccess(t *testing.T) {
	_, store, _, _ := observedFixture(t)
	stamp := func(key string) string {
		t.Helper()
		var value string
		if err := store.db.QueryRow(`SELECT updated_at FROM client_state WHERE key=?`, key).Scan(&value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	syncError(store, "test_health", errors.New("offline"))
	before := stamp("sync:test_health:error")
	syncError(store, "test_health", errors.New("offline"))
	if stamp("sync:test_health:error") != before {
		t.Fatal("unchanged error rewrote state")
	}
	syncError(store, "test_health", nil)
	value, found, err := store.State("sync:test_health:error")
	if err != nil || !found || value != "" {
		t.Fatal("recovery not persisted", err)
	}
	before = stamp("sync:test_health:success")
	cleared := stamp("sync:test_health:error")
	syncError(store, "test_health", nil)
	if stamp("sync:test_health:success") == before || stamp("sync:test_health:error") != cleared {
		t.Fatal("success freshness or unchanged error state lost")
	}
}

func TestDaemonHealthPersistsOnlyErrorTransitions(t *testing.T) {
	_, store, _, _ := observedFixture(t)
	syncError(store, "daemon_health", nil)
	var before, after int
	if err := store.db.QueryRow(`SELECT total_changes()`).Scan(&before); err != nil {
		t.Fatal(err)
	}
	syncError(store, "daemon_health", nil)
	if err := store.db.QueryRow(`SELECT total_changes()`).Scan(&after); err != nil || after != before {
		t.Fatal("healthy tick rewrote database", before, after, err)
	}
	if _, exists, err := store.State("sync:daemon_health:success"); err != nil || exists {
		t.Fatal("duplicate health success timestamp", exists, err)
	}
	syncError(store, "daemon_health", errors.New("client_hook_not_ready"))
	if value, _, err := store.State("sync:daemon_health:error"); err != nil || value != "client_hook_not_ready" {
		t.Fatal("health failure not persisted", value, err)
	}
	syncError(store, "daemon_health", nil)
	if value, _, err := store.State("sync:daemon_health:error"); err != nil || value != "" {
		t.Fatal("health recovery not persisted", value, err)
	}
}
