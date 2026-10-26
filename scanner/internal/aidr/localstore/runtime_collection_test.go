package localstore

import (
	"bytes"
	"os"
	"strings"
	"testing"
	"time"
)

func TestRuntimePausePreservesFrozenAndResumeBoundary(t *testing.T) {
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	if err := s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	if err := s.SetRuntimeCollection(testContext, true); err != nil {
		t.Fatal(err)
	}
	src := source(t, lines(1))
	collect(t, s, src)
	before := status(t, s)
	frozen, err := s.Prepare(testContext, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	checkpoint, _ := s.Checkpoint(testContext, src.ID)
	if err := s.SetRuntimeCollection(testContext, false); err != nil {
		t.Fatal(err)
	}
	same, _ := s.Prepare(testContext, 500, 1<<20)
	after, _ := s.Checkpoint(testContext, src.ID)
	if !bytes.Equal(frozen.Payload, same.Payload) || checkpoint.Cursor.Offset != after.Cursor.Offset || status(t, s).LogicalEvents != before.LogicalEvents {
		t.Fatal("OFF changed evidence, cursor or frozen bytes")
	}
	if err := os.WriteFile(src.Path, []byte(lines(2)), 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s = openStore(t, dir, DefaultLimits())
	defer s.Close()
	if err := s.LoadPolicy(testContext); err != nil {
		t.Fatal(err)
	}
	if err := s.SetRuntimeCollection(testContext, true); err != nil {
		t.Fatal(err)
	}
	resume := s.runtimeResumeAt
	if resume.IsZero() {
		t.Fatal("durable OFF was forgotten")
	}
	newLine := strings.Split(lines(3), "\n")[2] + "\n"
	newLine = strings.ReplaceAll(newLine, "2026-09-23T01:00:00Z", time.Now().Add(time.Second).UTC().Format(time.RFC3339Nano))
	if err := os.WriteFile(src.Path, []byte(lines(2)+newLine), 0600); err != nil {
		t.Fatal(err)
	}
	result := collect(t, s, src)
	if status(t, s).LogicalEvents != 2 || result.Coverage.Status != "partial" || !strings.Contains(strings.Join(result.Coverage.Reasons, ","), "aidr_audit_collection_disabled") {
		t.Fatal("disabled interval collected or gap hidden", result.Coverage)
	}
	if err := s.SetRuntimeCollection(testContext, true); err != nil || !s.runtimeResumeAt.Equal(resume) {
		t.Fatal("duplicate ON moved boundary", err)
	}
	same, _ = s.Prepare(testContext, 500, 1<<20)
	if !bytes.Equal(frozen.Payload, same.Payload) {
		t.Fatal("resume rewrote frozen bytes")
	}
	if err := s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil {
		t.Fatal(err)
	}
	ackTime := status(t, s).LastAcknowledgedAt
	if _, err := time.Parse(time.RFC3339Nano, ackTime); err != nil {
		t.Fatal("ACK time missing")
	}
	if err := s.Acknowledge(testContext, frozen.ID, frozen.Digest); err != nil || status(t, s).LastAcknowledgedAt != ackTime {
		t.Fatal("duplicate ACK changed receipt time", err)
	}
}

func TestRuntimeTargetRejectsPresentEmptyMetadata(t *testing.T) {
	for _, key := range []string{"runtime_collection_enabled", "runtime_collection_resume_at"} {
		t.Run(key, func(t *testing.T) {
			s := openStore(t, tempDir(t), DefaultLimits())
			if _, err := s.db.Exec(`INSERT INTO metadata(key,value) VALUES(?,'')`, key); err != nil {
				t.Fatal(err)
			}
			if err := s.SetRuntimeTarget(testContext, true, "1"); err != ErrInvalid {
				t.Fatal("corrupt metadata accepted", err)
			}
		})
	}
}
