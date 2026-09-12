package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/manifest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestClassificationTracksExactContentAndTrustedBaseline(t *testing.T) {
	value := classifyObservation(SkillObservation{}, Skill{Signature: "trusted"}, &CompareItem{LocalSignature: "trusted", Certified: true, SkillID: "family", VersionID: "v1"})
	if value.Certification != "certified" {
		t.Fatal(value)
	}
	changed := Skill{Signature: "edit"}
	for i := 0; i < 2; i++ {
		value = classifyObservation(value, changed, &CompareItem{LocalSignature: "edit"})
		if value.Trigger != "trusted_content_changed" {
			t.Fatal("lost baseline", value)
		}
	}
	value = classifyObservation(value, changed, &CompareItem{LocalSignature: "edit", Malicious: true})
	if value.Trigger != "malicious" {
		t.Fatal(value)
	}
	value = classifyObservation(value, Skill{Signature: "new"}, &CompareItem{LocalSignature: "edit", Malicious: true})
	if value.Malicious || value.Trigger != "trusted_content_changed" {
		t.Fatal("reused old verdict", value)
	}
	value = classifyObservation(value, Skill{Signature: "v2"}, &CompareItem{LocalSignature: "v2", Certified: true, SkillID: "family", VersionID: "v2"})
	if value.Trigger != "" || value.TrustedVersionID != "v2" {
		t.Fatal("trusted upgrade not recognized", value)
	}
}

func TestUnverifiedChangesRemainDistinctAcrossObservations(t *testing.T) {
	value := classifyObservation(SkillObservation{}, Skill{Signature: "a"}, &CompareItem{LocalSignature: "a"})
	if value.Trigger != "unverified" {
		t.Fatal(value)
	}
	value = classifyObservation(value, Skill{Signature: "b"}, nil)
	if value.Trigger != "unverified_content_changed" {
		t.Fatal(value)
	}
	value = classifyObservation(value, Skill{Signature: "b"}, &CompareItem{LocalSignature: "b"})
	if value.Trigger != "unverified_content_changed" {
		t.Fatal(value)
	}
}

func observedFixture(t *testing.T) (string, *Store, Inventory, Skill) {
	t.Helper()
	home := t.TempDir()
	root := filepath.Join(home, ".codex", "skills", "sample")
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("---\nname: sample\ndescription: example\n---\n# Example"), 0600); err != nil {
		t.Fatal(err)
	}
	m, err := manifest.Build(root, DefaultManifestOptions())
	if err != nil {
		t.Fatal(err)
	}
	skill := Skill{Name: "sample", Path: root, Signature: manifest.ContentSignature(m.Files)}
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	return home, store, Inventory{ClientID: "host", Agents: []Agent{{AgentType: "codex", SkillsPath: filepath.Dir(root), SkillManagementSupported: true, Skills: []Skill{skill}}}}, skill
}

func TestDefaultRecordsWithoutMovingSkillsAndReportsObservationCounts(t *testing.T) {
	for _, malicious := range []bool{false, true} {
		t.Run(map[bool]string{false: "unverified", true: "malicious"}[malicious], func(t *testing.T) {
			home, store, inventory, skill := observedFixture(t)
			events := 0
			counts := []int{}
			keys := map[string]bool{}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.HasSuffix(r.URL.Path, "/compare") {
					json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{AgentType: "codex", Name: skill.Name, LocalPath: skill.Path, LocalSignature: skill.Signature, Malicious: malicious}}})
					return
				}
				if strings.HasSuffix(r.URL.Path, "/events") {
					events++
					var event struct {
						Count   int            `json:"observation_count"`
						Details map[string]any `json:"details"`
					}
					if err := json.NewDecoder(r.Body).Decode(&event); err != nil {
						t.Error(err)
					}
					counts = append(counts, event.Count)
					keys[event.Details["event_key"].(string)] = true
				}
				w.Write([]byte(`{}`))
			}))
			defer server.Close()
			api := NewAPI(server.URL, "token", time.Second)
			policy := Policy{Classification: DefaultClassificationPolicy()}
			for i := 0; i < 2; i++ {
				if err := patrol(context.Background(), home, inventory, policy, api, store, true, true); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := os.Stat(filepath.Join(skill.Path, "SKILL.md")); err != nil {
				t.Fatal("default moved file", err)
			}
			if events != 2 {
				t.Fatalf("events=%d", events)
			}
			if len(keys) != 1 || counts[0] != 1 || counts[1] != 2 {
				t.Fatalf("observations did not reuse incident identity: %v %v", keys, counts)
			}
			value, err := store.Observation(skill.Path)
			if err != nil {
				t.Fatal(err)
			}
			if value.Action != "record" || value.Count != 2 {
				t.Fatal(value)
			}
		})
	}
}

func TestChangedContentPreventsDestructiveAction(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	os.WriteFile(filepath.Join(skill.Path, "SKILL.md"), []byte("edited"), 0600)
	value := SkillObservation{Action: "quarantine", Trigger: "unverified"}
	err := applyObservedAction(context.Background(), home, inventory, inventory.Agents[0], skill, Policy{}, API{}, store, &value)
	if err == nil || value.ErrorCode != "skill_content_changed" {
		t.Fatal(err, value)
	}
	if _, err := os.Stat(skill.Path); err != nil {
		t.Fatal(err)
	}
}

func TestOfflineDefaultKeepsUnknownContent(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	if err := patrolClassified(context.Background(), home, inventory, Policy{Classification: DefaultClassificationPolicy()}, NewAPI("http://127.0.0.1:1", "token", time.Millisecond), store, false); err != nil {
		t.Fatal(err)
	}
	value, _ := store.Observation(skill.Path)
	if value.Certification != "confirmation_pending" {
		t.Fatal(value)
	}
	if _, err := os.Stat(skill.Path); err != nil {
		t.Fatal(err)
	}
}

func TestManualScanKeepsSourceAndReusesExactSnapshot(t *testing.T) {
	home, store, _, skill := observedFixture(t)
	var uploads atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/scanner/imports" {
			if r.Header.Get("Authorization") != "Bearer submit-token" {
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			uploads.Add(1)
			w.Write([]byte(`{"skill_id":"scanned-content","version_id":"v1","status":"PENDING"}`))
			return
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	api := NewAPI(server.URL, "submit-token", time.Second)
	var first string
	for attempt := 0; attempt < 2; attempt++ {
		id, err := SubmitDiscoveredSkill(context.Background(), home, api, store, "codex", skill.Path, skill.Signature)
		if err != nil {
			t.Fatal(err)
		}
		if attempt == 0 {
			first = id
		} else if id != first {
			t.Fatal("repeated click created another snapshot")
		}
		if err := checkObservedContent(skill); err != nil {
			t.Fatal("original content changed:", err)
		}
	}
	if uploads.Load() != 1 {
		t.Fatalf("duplicate scan submission: %d", uploads.Load())
	}
	task := Task{ID: 51, TaskType: "skill_action", Payload: map[string]any{"action": "submit_scan", "agent_type": "codex", "path": skill.Path, "expected_signature": skill.Signature}}
	for retry := 0; retry < 2; retry++ {
		if err := executeObservedTask(context.Background(), home, Policy{}, api, store, task); err != nil {
			t.Fatal("platform scan task failed", err)
		}
	}
	if uploads.Load() != 1 {
		t.Fatal("platform task did not reuse the pending content snapshot")
	}
	observation, err := store.Observation(skill.Path)
	if err != nil || observation.PendingID != first || observation.Signature != skill.Signature {
		t.Fatal(observation, err)
	}
	if err := os.WriteFile(filepath.Join(skill.Path, "SKILL.md"), []byte("edited after selection"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := SubmitDiscoveredSkill(context.Background(), home, api, store, "codex", skill.Path, skill.Signature); err == nil {
		t.Fatal("stale selection submitted new content")
	}
	if uploads.Load() != 1 {
		t.Fatal("stale selection reached scanner")
	}
}

func TestAuthorizedFileActionBindsContentAndRetainsRecovery(t *testing.T) {
	for _, action := range []string{"quarantine", "uninstall"} {
		t.Run(action, func(t *testing.T) {
			home, store, inventory, skill := observedFixture(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{}`)) }))
			defer server.Close()
			api := NewAPI(server.URL, "token", time.Second)
			task := Task{ID: 19, TaskType: "skill_action", Payload: map[string]any{
				"action": action, "agent_type": "codex", "path": skill.Path, "expected_signature": "older-content",
			}}
			if err := executeTask(context.Background(), home, inventory, Policy{}, api, store, task); err == nil {
				t.Fatal("old task modified current content")
			}
			if err := checkObservedContent(skill); err != nil {
				t.Fatal(err)
			}
			task.Payload["expected_signature"] = skill.Signature
			for retry := 0; retry < 2; retry++ {
				if err := executeTask(context.Background(), home, inventory, Policy{}, api, store, task); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
				t.Fatal("active copy was not removed", err)
			}
			items, err := store.QuarantineItems()
			if err != nil || len(items) != 1 {
				t.Fatal(items, err)
			}
			if action == "uninstall" && items[0].Status != "uninstalled" {
				t.Fatal("uninstall recovery disposition missing")
			}
			if err := checkObservedContent(Skill{Path: items[0].QuarantinePath, Signature: skill.Signature}); err != nil {
				t.Fatal("recovery copy changed", err)
			}
		})
	}
}

func TestTrustedRecoveryVerifiesDownloadBeforeChangingCurrentFiles(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		w.Write([]byte(`{"error_code":"client.skill_not_authorized"}`))
	}))
	defer server.Close()
	task := Task{ID: 23, TaskType: "skill_action", Payload: map[string]any{
		"action": "restore_trusted", "agent_type": "codex", "path": skill.Path,
		"expected_signature": skill.Signature, "skill_id": "family", "version_id": "v1", "trusted_signature": "trusted",
	}}
	err := executeTask(context.Background(), home, inventory, Policy{}, NewAPI(server.URL, "token", time.Second), store, task)
	if err == nil {
		t.Fatal("unauthorized restore succeeded")
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal("failed download changed active content", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 0 {
		t.Fatal("source moved before download authorization", items, err)
	}
}
