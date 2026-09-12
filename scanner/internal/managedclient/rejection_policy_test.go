package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestScanRejectionRequiresSubmittedExactContent(t *testing.T) {
	previous := SkillObservation{Signature: "current", TrustedSignature: "trusted", PendingID: "snapshot"}
	skill := Skill{Signature: "current"}
	compare := CompareItem{Rejected: true, LocalSignature: "current", ExpectedSignature: "current", Status: "REJECTED"}
	if got := classifyObservation(previous, skill, &compare); got.Trigger != "trusted_scan_rejected" {
		t.Fatal(got)
	}
	compare.Rejected = false
	if got := classifyObservation(previous, skill, &compare); got.Trigger != "trusted_content_changed" {
		t.Fatal("technical failure must not trigger rejection", got)
	}
	compare.Rejected = true
	compare.Malicious = true
	if got := classifyObservation(previous, skill, &compare); got.Trigger != "malicious" {
		t.Fatal(got)
	}
	compare.Malicious = false
	for _, status := range []string{"FAILED", "PENDING", "VETTED", "CANCELLED"} {
		compare.Status = status
		if got := classifyObservation(previous, skill, &compare); got.Trigger != "trusted_content_changed" {
			t.Fatal(status, got)
		}
	}
	compare.Status = "REJECTED"
	compare.ExpectedSignature = "older"
	if got := classifyObservation(previous, skill, &compare); got.Trigger != "trusted_content_changed" {
		t.Fatal(got)
	}
	compare.ExpectedSignature = "current"
	previous.PendingID = ""
	if got := classifyObservation(previous, skill, &compare); got.Trigger != "trusted_content_changed" {
		t.Fatal(got)
	}
	previous.PendingID = "snapshot"
	previous.Signature = "older"
	if got := classifyObservation(previous, skill, &compare); got.Trigger != "trusted_content_changed" {
		t.Fatal(got)
	}
}

func TestRecordOnlyDoesNotNotify(t *testing.T) {
	for _, event := range []string{"skill_governance_detected", "skill_governance_action", "skill_governance_recorded"} {
		if _, notify := notificationForEvent(event, "codex", "test", map[string]any{"action": "record_only", "trigger": "malicious"}); notify {
			t.Fatal(event)
		}
	}
	if _, notify := notificationForEvent("skill_governance_detected", "codex", "test", map[string]any{"action": "record"}); !notify {
		t.Fatal("record and alert must notify")
	}
}

func TestSubmittedChangeTransitionsToRejectionPolicy(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	var rejected atomic.Bool
	var uploads atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/compare"):
			status := "PENDING"
			if rejected.Load() {
				status = "REJECTED"
			}
			json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{AgentType: "codex", Name: skill.Name, LocalPath: skill.Path, LocalSignature: skill.Signature, ExpectedSignature: skill.Signature, Status: status, Rejected: rejected.Load()}}})
		case r.URL.Path == "/api/v1/scanner/imports":
			uploads.Add(1)
			w.Write([]byte(`{"skill_id":"scan","version_id":"scan-v1","status":"PENDING"}`))
		default:
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	policy := Policy{Classification: DefaultClassificationPolicy()}
	policy.Classification.Rules["unverified_content_changed"] = "submit_scan"
	policy.Classification.Rules["unverified_scan_rejected"] = "quarantine"
	if err := store.SaveObservation(skill.Path, SkillObservation{Signature: "before"}); err != nil {
		t.Fatal(err)
	}
	api := NewAPI(server.URL, "token", time.Second)
	if err := patrolClassified(context.Background(), home, inventory, policy, api, store, true); err != nil {
		t.Fatal(err)
	}
	pending, err := store.Observation(skill.Path)
	if err != nil || pending.PendingID == "" || uploads.Load() != 1 {
		t.Fatal(pending, err, uploads.Load())
	}
	if err := checkObservedContent(skill); err != nil {
		t.Fatal("submission changed source", err)
	}
	rejected.Store(true)
	if err := patrolClassified(context.Background(), home, inventory, policy, api, store, true); err != nil {
		t.Fatal(err)
	}
	result, err := store.Observation(skill.Path)
	if err != nil || result.Trigger != "unverified_scan_rejected" || result.ActionStatus != "completed" {
		t.Fatal(result, err)
	}
	copies, err := store.QuarantineItems()
	if err != nil || len(copies) != 1 || uploads.Load() != 1 {
		t.Fatal(copies, err, uploads.Load())
	}
	if err := checkObservedContent(Skill{Path: copies[0].QuarantinePath, Signature: skill.Signature}); err != nil {
		t.Fatal(err)
	}
}
