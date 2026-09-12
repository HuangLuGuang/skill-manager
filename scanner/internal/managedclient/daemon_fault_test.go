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
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestDaemonSlowInstallWithRepeatedTaskLostReceiptAndSharedEdit(t *testing.T) {
	home, store, inventory, _ := observedFixture(t)
	target := filepath.Join(inventory.Agents[0].SkillsPath, "safe-skill")
	writeSkill(t, target, "original")
	if err := store.SaveInstall(Installation{AgentType: "codex", SkillID: "skill-1", SkillName: "safe-skill", TargetPath: target}); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(home, ".claude", "skills", "shared")
	if err := os.MkdirAll(filepath.Dir(alias), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, alias); err != nil {
		t.Fatal(err)
	}
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	body := signedPackage(t, private)
	policy := Policy{Mode: "audit", Classification: DefaultClassificationPolicy(), ReleasePublicKey: base64.StdEncoding.EncodeToString(public)}
	task := Task{ID: 901, TaskType: "install_skill", Payload: map[string]any{"agent_type": "codex", "skill_id": "skill-1"}}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	entered, unblock := make(chan struct{}), make(chan struct{})
	var once sync.Once
	var heartbeats, polls, downloads, claims, rejected atomic.Int32
	var acceptReceipts, receiptAccepted atomic.Bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.Contains(r.URL.Path, "/package"):
			downloads.Add(1)
			once.Do(func() { close(entered) })
			select {
			case <-unblock:
				w.Write(body)
			case <-ctx.Done():
			case <-r.Context().Done():
			}
			return
		case strings.HasSuffix(r.URL.Path, "/heartbeat"):
			heartbeats.Add(1)
			json.NewEncoder(w).Encode(map[string]any{"policy": policy})
			return
		case strings.HasSuffix(r.URL.Path, "/policy"):
			json.NewEncoder(w).Encode(policy)
			return
		case strings.HasSuffix(r.URL.Path, "/tasks"):
			polls.Add(1)
			// Replay the same task even after receiving its result.
			json.NewEncoder(w).Encode([]Task{task, task})
			return
		case strings.HasSuffix(r.URL.Path, "/result"):
			var result struct {
				Status string `json:"status"`
			}
			if err := json.NewDecoder(r.Body).Decode(&result); err != nil {
				t.Error(err)
			}
			if result.Status == "running" {
				claims.Add(1)
			} else {
				if !acceptReceipts.Load() {
					rejected.Add(1)
					w.WriteHeader(503)
					return
				}
				if result.Status != "failed" {
					t.Errorf("edited target task status = %s", result.Status)
				}
				receiptAccepted.Store(true)
			}
		case strings.HasSuffix(r.URL.Path, "/compare"):
			w.Write([]byte(`{"items":[]}`))
			return
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	finished := make(chan error, 1)
	go func() {
		finished <- RunDaemon(ctx, home, NewAPI(server.URL, "test", 45*time.Second), store, 40*time.Millisecond, nil)
	}()
	defer func() {
		cancel()
		select {
		case err := <-finished:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(5 * time.Second):
			t.Error("daemon failed to stop")
		}
	}()
	waitFor := func(label string, condition func() bool) {
		t.Helper()
		deadline := time.Now().Add(25 * time.Second)
		for !condition() {
			if time.Now().After(deadline) {
				t.Fatal(label)
			}
			time.Sleep(10 * time.Millisecond)
		}
	}
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("installation did not enter download")
	}
	beforeHeartbeat, beforePolls := heartbeats.Load(), polls.Load()
	waitFor("slow task blocked independent loops", func() bool { return heartbeats.Load() >= beforeHeartbeat+3 && polls.Load() >= beforePolls+1 })
	if err := os.WriteFile(filepath.Join(alias, "SKILL.md"), []byte("edit through shared Agent while downloading"), 0600); err != nil {
		t.Fatal(err)
	}
	close(unblock)
	waitFor("failed result was not retried", func() bool { return rejected.Load() >= 2 })
	if err := os.WriteFile(filepath.Join(target, "SKILL.md"), []byte("later edit while receipt is offline"), 0600); err != nil {
		t.Fatal(err)
	}
	acceptReceipts.Store(true)
	waitFor("receipt did not recover", receiptAccepted.Load)
	beforePolls = polls.Load()
	waitFor("duplicate tasks not repolled", func() bool { return polls.Load() >= beforePolls+1 })
	if downloads.Load() != 1 || claims.Load() != 1 {
		t.Fatalf("task executed again: downloads=%d claims=%d", downloads.Load(), claims.Load())
	}
	for _, path := range []string{target, alias} {
		got, err := os.ReadFile(filepath.Join(path, "SKILL.md"))
		if err != nil || string(got) != "later edit while receipt is offline" {
			t.Fatal("user content changed", path, string(got), err)
		}
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 0 {
		t.Fatal("conflict created unexpected copies", items, err)
	}
	history, err := store.TaskHistory(10)
	if err != nil || len(history) != 1 || history[0].Status != "failed" || !strings.Contains(history[0].Error, "skill_content_changed") {
		t.Fatal(history, err)
	}
}

func TestLegacyGovernanceKeepsOutOfScopeLinksVisibleWithoutTakingOver(t *testing.T) {
	home, store, _, _ := observedFixture(t)
	external := t.TempDir()
	writeSkill(t, external, "external")
	link := filepath.Join(home, ".codex", "skills", "external-link")
	if err := os.Symlink(external, link); err != nil {
		t.Fatal(err)
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	plan := BuildTakeoverPlan(inventory, nil)
	found := false
	for _, path := range plan.ExcludedPaths {
		if path == link {
			found = true
		}
	}
	if !found {
		t.Fatal("out-of-scope link missing from exclusions", plan)
	}
	for _, item := range plan.Items {
		if item.Source == link {
			t.Fatal("out-of-scope link can be taken over", item)
		}
	}
	if err := store.SetGovernanceEnabled(true); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusServiceUnavailable) }))
	defer server.Close()
	if err := patrol(context.Background(), home, inventory, Policy{Mode: "block"}, NewAPI(server.URL, "test", time.Second), store, false, false); err != nil {
		t.Fatal(err)
	}
	if target, err := os.Readlink(link); err != nil || target != external {
		t.Fatal("legacy patrol moved external link", target, err)
	}
}
