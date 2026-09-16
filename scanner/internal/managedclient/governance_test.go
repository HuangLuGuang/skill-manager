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
				if i == 0 {
					if _, err := store.db.Exec(`UPDATE client_notifications SET created_at = ?`, time.Now().UTC().Add(-10*time.Minute).Format(time.RFC3339Nano)); err != nil {
						t.Fatal(err)
					}
				}
			}
			if _, err := os.Stat(filepath.Join(skill.Path, "SKILL.md")); err != nil {
				t.Fatal("default moved file", err)
			}
			notifications, err := store.Notifications(10)
			if err != nil || len(notifications) != 1 {
				t.Fatalf("stable incident emitted repeated notifications: %#v %v", notifications, err)
			}
			skill.Signature += "-changed"
			inventory.Agents[0].Skills[0].Signature = skill.Signature
			if err := patrol(context.Background(), home, inventory, policy, api, store, true, true); err != nil {
				t.Fatal(err)
			}
			if events != 3 || len(keys) != 2 || counts[0] != 1 || counts[1] != 2 || counts[2] != 1 {
				t.Fatalf("incident identity did not track stable and changed content: events=%d keys=%v counts=%v", events, keys, counts)
			}
			notifications, err = store.Notifications(10)
			if err != nil || len(notifications) != 2 {
				t.Fatalf("changed content did not emit a new notification: %#v %v", notifications, err)
			}
			value, err := store.Observation(skill.Path)
			if err != nil {
				t.Fatal(err)
			}
			if value.Action != "record" || value.Count != 1 {
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

func TestCompareFailurePreservesTrustedVerdict(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	if err := store.SaveObservation(skill.Path, SkillObservation{
		Signature: skill.Signature, TrustedSignature: skill.Signature,
		TrustedSkillID: "skill-1", TrustedVersionID: "version-1", Certification: "certified",
	}); err != nil {
		t.Fatal(err)
	}
	policy := Policy{Classification: DefaultClassificationPolicy()}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if err := patrolClassified(ctx, home, inventory, policy, NewAPI("http://127.0.0.1:1", "token", 20*time.Millisecond), store, true); err != nil {
		t.Fatal(err)
	}
	value, err := store.Observation(skill.Path)
	if err != nil {
		t.Fatal(err)
	}
	if value.Certification != "certified" || value.Trigger != "" {
		t.Fatalf("platform failure downgraded trusted skill: %#v", value)
	}
}

func TestPartialComparePreservesUnreturnedTrustedVerdict(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	if err := store.SaveObservation(skill.Path, SkillObservation{Signature: skill.Signature, TrustedSignature: skill.Signature, Certification: "certified"}); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{}})
	}))
	defer server.Close()
	if err := patrolClassified(context.Background(), home, inventory, Policy{Classification: DefaultClassificationPolicy()}, NewAPI(server.URL, "token", time.Second), store, true); err != nil {
		t.Fatal(err)
	}
	value, err := store.Observation(skill.Path)
	if err != nil || value.Certification != "certified" {
		t.Fatalf("partial comparison downgraded unreturned trusted skill: %#v %v", value, err)
	}
}

func TestFileActionQueuesDetectionBeforeEnforcement(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	reported := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/compare"):
			_ = json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{
				AgentType: "codex", Name: skill.Name, LocalPath: skill.Path, LocalSignature: skill.Signature,
			}}})
		case strings.HasSuffix(r.URL.Path, "/events"):
			var payload map[string]any
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				t.Error(err)
				return
			}
			reported = append(reported, payload["event_type"].(string))
			_, _ = w.Write([]byte(`{}`))
		default:
			_, _ = w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()

	policy := Policy{Classification: DefaultClassificationPolicy()}
	policy.Classification.Rules["unverified"] = "quarantine"
	if err := patrolClassified(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, true); err != nil {
		t.Fatal(err)
	}
	if len(reported) != 0 {
		t.Fatalf("file enforcement should not wait for event uploads: %v", reported)
	}
	queued, err := store.QueuedEvents()
	if err != nil || len(queued) != 2 || queued[0].EventType != "skill_governance_detected" || queued[1].EventType != "skill_governance_action" {
		t.Fatalf("governance evidence was not persisted for ordered background upload: %#v %v", queued, err)
	}
	if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
		t.Fatalf("active skill was not quarantined: %v", err)
	}
}

func TestManualScanKeepsSourceAndReusesExactSnapshot(t *testing.T) {
	for _, linked := range []bool{false, true} {
		t.Run(map[bool]string{false: "directory", true: "managed_symlink"}[linked], func(t *testing.T) {
			home, store, _, skill := observedFixture(t)
			if linked {
				release := filepath.Join(ManagedSkillsRoot(home), "sample", "versions", "v1", "release")
				if err := os.MkdirAll(filepath.Dir(release), 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.Rename(skill.Path, release); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(release, skill.Path); err != nil {
					t.Fatal(err)
				}
			}
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
		})
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

func TestManualUninstallWithoutRetentionRemovesRecoveryCopy(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{}`)) }))
	defer server.Close()
	task := Task{ID: 20, TaskType: "skill_action", Payload: map[string]any{
		"action": "uninstall", "agent_type": "codex", "path": skill.Path,
		"expected_signature": skill.Signature, "retain_copy": false,
	}}
	if err := executeTask(context.Background(), home, inventory, Policy{}, NewAPI(server.URL, "token", time.Second), store, task); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
		t.Fatal("active copy was not removed", err)
	}
	items, err := store.QuarantineItems()
	if err != nil || len(items) != 0 {
		t.Fatal("unretained uninstall remained visible as a recovery copy", items, err)
	}
	var status, copyPath string
	if err := store.db.QueryRow(`SELECT status,quarantine_path FROM client_quarantine WHERE original_path=? ORDER BY created_at DESC LIMIT 1`, skill.Path).Scan(&status, &copyPath); err != nil {
		t.Fatal(err)
	}
	if status != "discarded" {
		t.Fatalf("unexpected audit disposition %q", status)
	}
	if _, err := os.Stat(copyPath); !os.IsNotExist(err) {
		t.Fatal("unretained recovery files still exist", err)
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

func TestRescannedApprovalClearsPreviousMaliciousVerdict(t *testing.T) {
	previous := SkillObservation{Signature: "same", Malicious: true, Trigger: "malicious", Certification: "unverified"}
	current := classifyObservation(previous, Skill{Signature: "same"}, &CompareItem{LocalSignature: "same", Certified: true, SkillID: "approved", VersionID: "v1"})
	if current.Malicious || current.Trigger != "" || current.Certification != "certified" {
		t.Fatalf("old verdict survived fresh approval: %+v", current)
	}
}
