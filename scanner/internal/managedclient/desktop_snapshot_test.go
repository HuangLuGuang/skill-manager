package managedclient

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func desktopFixture(t testing.TB) (string, *Store) {
	t.Helper()
	home := t.TempDir()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	if err := store.SaveInventory(Inventory{ClientID: "test-client", DiscoveryVersion: InventoryCacheVersion, Agents: []Agent{}}); err != nil {
		t.Fatal(err)
	}
	return home, store
}

func TestDesktopSnapshotReadOnly(t *testing.T) {
	home, store := desktopFixture(t)
	before, _, _ := store.State("inventory")
	snapshot, err := DesktopSnapshot(context.Background(), home)
	if err != nil {
		t.Fatal(err)
	}
	if snapshot["inventory"].(Inventory).ClientID != "test-client" || snapshot["revision"] != "0" {
		t.Fatalf("unexpected snapshot: %#v", snapshot)
	}
	after, _, _ := store.State("inventory")
	if before != after {
		t.Fatal("snapshot modified inventory")
	}
	if _, included := snapshot["pending"]; included {
		t.Fatal("hidden recovery partition was loaded")
	}
	recovery, err := DesktopSnapshot(context.Background(), home, true)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"pending", "scan_history", "quarantine"} {
		if _, ok := recovery[key]; !ok {
			t.Fatalf("missing recovery partition: %s", key)
		}
	}
}

func TestDesktopSnapshotMissingDatabaseDoesNotCreate(t *testing.T) {
	home := t.TempDir()
	if _, err := DesktopSnapshot(context.Background(), home); err == nil {
		t.Fatal("missing database accepted")
	}
	if _, err := os.Stat(filepath.Join(home, ".agent-manager")); !os.IsNotExist(err) {
		t.Fatalf("read created state: %v", err)
	}
}

func TestDesktopSnapshotRejectsOutdatedInventory(t *testing.T) {
	home, store := desktopFixture(t)
	store.SetState("inventory", `{"client_id":"test-client","discovery_version":-1}`)
	if _, err := DesktopSnapshot(context.Background(), home); err == nil {
		t.Fatal("outdated inventory accepted")
	}
}

func TestDesktopIPCProtocolAndShutdown(t *testing.T) {
	home, _ := desktopFixture(t)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- serveDesktop(ctx, home, listener) }()
	for _, request := range []string{
		`{"version":1,"method":"snapshot"}`,
		`{"version":2,"method":"snapshot"}`,
		`{"version":1,"method":"execute"}`,
		`{"version":1,"method":"snapshot","command":"anything"}`,
	} {
		conn, err := net.Dial("tcp", listener.Addr().String())
		if err != nil {
			t.Fatal(err)
		}
		conn.SetDeadline(time.Now().Add(time.Second * 5))
		conn.Write([]byte(request + "\n"))
		var response map[string]any
		err = json.NewDecoder(conn).Decode(&response)
		conn.Close()
		if err != nil {
			t.Fatal(err)
		}
		if request == `{"version":1,"method":"snapshot"}` {
			if response["local"] == nil || response["inventory"] == nil {
				t.Fatalf("missing snapshot: %v", response)
			}
		} else if response["error"] != "client_ipc_invalid_request" {
			t.Fatalf("invalid request accepted: %v", response)
		}
	}
	idle, err := net.Dial("tcp", listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer idle.Close()
	idle.Write([]byte("{"))
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("IPC did not stop")
	}
}

func BenchmarkDesktopSnapshot(b *testing.B) {
	home, _ := desktopFixture(b)
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := DesktopSnapshot(context.Background(), home); err != nil {
			b.Fatal(err)
		}
	}
}

func benchmarkInventory(b *testing.B, store *Store) {
	inventory := Inventory{ClientID: "test-client", Agents: []Agent{}}
	for i := 0; i < 10; i++ {
		agent := Agent{AgentType: fmt.Sprintf("agent-%d", i), Skills: []Skill{}}
		for j := 0; j < 100; j++ {
			agent.Skills = append(agent.Skills, Skill{Name: fmt.Sprintf("skill-%d", j), Path: fmt.Sprintf("/agents/%d/skills/%d", i, j)})
		}
		inventory.Agents = append(inventory.Agents, agent)
	}
	if err := store.SaveInventory(inventory); err != nil {
		b.Fatal(err)
	}
}

func BenchmarkDesktopLegacyCommands(b *testing.B) {
	binary := os.Getenv("CLIENT_BASELINE_BINARY")
	if binary == "" {
		b.Skip("set CLIENT_BASELINE_BINARY to the pre-change client")
	}
	home, store := desktopFixture(b)
	benchmarkInventory(b, store)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		for _, command := range []string{"local-status", "cached-inventory"} {
			if output, err := exec.Command(binary, command, "--home", home).CombinedOutput(); err != nil {
				b.Fatalf("%v: %s", err, output)
			}
		}
	}
}

func TestEmptyEventFlushDoesNotWrite(t *testing.T) {
	_, store := desktopFixture(t)
	var before, after int
	store.db.QueryRow("SELECT total_changes()").Scan(&before)
	if err := flushEventsLimit(context.Background(), NewAPI("http://127.0.0.1:1", "test", time.Second), store, 10); err != nil {
		t.Fatal(err)
	}
	store.db.QueryRow("SELECT total_changes()").Scan(&after)
	if after != before {
		t.Fatalf("empty queue wrote %d rows", after-before)
	}
}

func TestDesktopSnapshotLargeRecovery(t *testing.T) {
	home, store := desktopFixture(t)
	tx, err := store.db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 1000; i++ {
		path := filepath.Join(home, "recovery", fmt.Sprint(i))
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(path, "SKILL.md"), []byte("# Fixture\n"+strings.Repeat("content\n", 512)), 0600); err != nil {
			t.Fatal(err)
		}
		_, err := tx.Exec(`INSERT INTO client_quarantine(id,agent_type,skill_name,original_path,quarantine_path,reason,status,created_at) VALUES(?,?,?,?,?,?,?,?)`,
			fmt.Sprint(i), "codex", fmt.Sprintf("skill-%d", i), filepath.Join(home, "original", fmt.Sprint(i)), path, "fixture", "quarantined", time.Now().UTC().Format(time.RFC3339Nano))
		if err != nil {
			t.Fatal(err)
		}
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	for _, recovery := range []bool{false, true} {
		start := time.Now()
		snapshot, err := DesktopSnapshot(context.Background(), home, recovery)
		if err != nil {
			t.Fatal(err)
		}
		t.Logf("1000 recovery directories: recovery=%t elapsed=%s", recovery, time.Since(start))
		if recovery {
			items := snapshot["quarantine"].([]QuarantineItem)
			if len(items) != 1000 {
				t.Fatal(len(items))
			}
			for _, item := range items {
				if item.Signature == "" || item.ErrorCode != "" {
					t.Fatalf("invalid recovery evidence: %+v", item)
				}
			}
		} else if _, present := snapshot["quarantine"]; present {
			t.Fatal("hidden recovery partition loaded")
		}
	}
}
