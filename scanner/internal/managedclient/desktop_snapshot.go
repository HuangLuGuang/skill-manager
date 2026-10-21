package managedclient

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/url"
	"path/filepath"
)

// DesktopSnapshot reads all visible partitions from one SQLite read transaction.
// A separate read-only connection leaves the daemon's writer available in WAL mode.
func DesktopSnapshot(ctx context.Context, home string, includeRecovery ...bool) (map[string]any, error) {
	path := filepath.Join(home, ".agent-manager", "client.db")
	db, err := sql.Open("sqlite", (&url.URL{Scheme: "file", Path: filepath.ToSlash(path), RawQuery: "mode=ro"}).String())
	if err != nil {
		return nil, err
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	if _, err := db.ExecContext(ctx, "PRAGMA busy_timeout=1000; BEGIN"); err != nil {
		return nil, err
	}
	defer db.Exec("ROLLBACK")
	store := &Store{db: db, root: filepath.Dir(path)}
	local, err := store.LocalStatus()
	if err != nil {
		return nil, err
	}
	body, ok, err := store.State("inventory")
	if err != nil {
		return nil, err
	}
	var inventory Inventory
	if !ok || json.Unmarshal([]byte(body), &inventory) != nil || inventory.ClientID == "" || inventory.DiscoveryVersion != InventoryCacheVersion {
		return nil, fmt.Errorf("client_inventory_unavailable")
	}
	revision, _, err := store.LatestUIEvent()
	if err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	result := map[string]any{"local": local, "inventory": inventory, "revision": fmt.Sprint(revision)}
	if len(includeRecovery) > 0 && includeRecovery[0] {
		if result["pending"], err = store.PendingItems(); err != nil {
			return nil, err
		}
		if result["scan_history"], err = store.ScanHistory(); err != nil {
			return nil, err
		}
		if result["quarantine"], err = store.QuarantineItems(); err != nil {
			return nil, err
		}
	}
	return result, nil
}
