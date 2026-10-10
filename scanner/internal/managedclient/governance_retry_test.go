package managedclient

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAutomaticQuarantineBackoffPersistsAndPolicyChangeRetries(t *testing.T) {
	for _, reset := range []string{"deadline", "policy"} {
		t.Run(reset, func(t *testing.T) {
			home, store, inventory, skill := observedFixture(t)
			if _, err := store.db.Exec(`CREATE TRIGGER reject_quarantine BEFORE INSERT ON client_quarantine BEGIN SELECT RAISE(FAIL, 'storage failure'); END`); err != nil {
				t.Fatal(err)
			}
			policy := Policy{Classification: DefaultClassificationPolicy()}
			policy.Classification.Rules["unverified"] = "quarantine"
			api := NewAPI("http://127.0.0.1:1", "fixture", time.Second)
			if err := patrolClassified(context.Background(), home, inventory, policy, api, store, false); err == nil {
				t.Fatal("expected failed quarantine")
			}
			value, err := store.Observation(skill.Path)
			if err != nil || value.ActionFailures != 1 || !automaticFileActionDeferred(value, time.Now()) {
				t.Fatal(value, err)
			}
			if _, err := store.db.Exec(`DROP TRIGGER reject_quarantine`); err != nil {
				t.Fatal(err)
			}
			store.Close()
			store, err = OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			if err := patrolClassified(context.Background(), home, inventory, policy, api, store, false); err != nil {
				t.Fatal(err)
			}
			if _, err := os.Stat(skill.Path); err != nil {
				t.Fatal("retried before deadline after restart", err)
			}
			if reset == "deadline" {
				value.NextActionAt = time.Now().Add(-time.Second).Format(time.RFC3339Nano)
				if err := store.SaveObservation(skill.Path, value); err != nil {
					t.Fatal(err)
				}
			} else {
				policy.Classification.Version = "changed"
			}
			if err := patrolClassified(context.Background(), home, inventory, policy, api, store, false); err != nil {
				t.Fatal(err)
			}
			if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
				t.Fatal("retry did not quarantine", err)
			}
			value, err = store.Observation(skill.Path)
			if err != nil || value.ActionFailures != 0 || value.NextActionAt != "" || value.ActionStatus != "completed" {
				t.Fatal(value, err)
			}
		})
	}
}

func TestAutomaticFileActionBackoffBounded(t *testing.T) {
	now := time.Now()
	value := SkillObservation{Action: "quarantine", ActionStatus: "failed"}
	for attempt := 0; attempt < 30; attempt++ {
		deferAutomaticFileAction(&value, now)
		next, err := time.Parse(time.RFC3339Nano, value.NextActionAt)
		if err != nil || next.Sub(now) < 30*time.Second || next.Sub(now) > 30*time.Minute {
			t.Fatal(value, err)
		}
	}
	if !automaticFileActionDeferred(value, now) || automaticFileActionDeferred(value, now.Add(30*time.Minute)) {
		t.Fatal(value)
	}
}
