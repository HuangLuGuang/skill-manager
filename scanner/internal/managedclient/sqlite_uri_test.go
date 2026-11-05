package managedclient

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/url"
	"path/filepath"
	"testing"
)

func TestSQLiteURIWindowsDriveAndEscaping(t *testing.T) {
	for _, path := range []string{"C:/Users/test/client.db", "D:/用户/space #?%/client.db", "/tmp/space #?%/client.db"} {
		u, err := url.Parse(sqliteURI(path, "mode=ro"))
		if err != nil {
			t.Fatal(err)
		}
		want := path
		if path[1] == ':' {
			want = "/" + path
		}
		if u.Host != "" || u.Path != want || u.Query().Get("mode") != "ro" || u.Fragment != "" {
			t.Fatalf("invalid SQLite URI for %q: %s", path, u)
		}
	}
}

func TestDesktopReadOnlyPathsWithSpecialCharacters(t *testing.T) {
	home := filepath.Join(t.TempDir(), "用户 space #%")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.SaveInventory(Inventory{ClientID: "fixture", DiscoveryVersion: InventoryCacheVersion}); err != nil {
		t.Fatal(err)
	}
	policy, err := json.Marshal(Policy{
		Classification: &ClassificationPolicy{DesktopMenuVisibility: map[string]bool{"models": false}},
		AgentDiscovery: &DiscoveryCatalog{Version: "fixture"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SetState("policy", string(policy)); err != nil {
		t.Fatal(err)
	}
	if _, err := DesktopSnapshot(context.Background(), home); err != nil {
		t.Fatal(err)
	}
	if visibility := desktopMenuReceipt(context.Background(), home); visibility == nil || visibility["models"] {
		t.Fatalf("menu policy not read: %v", visibility)
	}
	if catalog := discoveryCatalog(home); catalog == nil || catalog.Version != "fixture" {
		t.Fatalf("discovery policy not read: %v", catalog)
	}
	db, err := sql.Open("sqlite", sqliteURI(filepath.Join(home, ".agent-manager", "client.db"), "mode=ro"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec("DELETE FROM client_state"); err == nil {
		t.Fatal("read-only connection allowed a write")
	}
	var body string
	if err := db.QueryRow("SELECT value FROM client_state WHERE key='inventory'").Scan(&body); err != nil || !json.Valid([]byte(body)) {
		t.Fatalf("cannot read inventory: %v", err)
	}
}
