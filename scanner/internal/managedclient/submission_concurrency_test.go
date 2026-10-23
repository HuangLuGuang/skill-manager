package managedclient

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"skill-manager/scanner/internal/manifest"
)

func TestSubmissionIgnoresUnrelatedBusySnapshotAndAIDR(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	id, err := stageObservedSkill(home, inventory.Agents[0], skill, store)
	if err != nil {
		t.Fatal(err)
	}
	peer := skill
	peer.Path = filepath.Join(filepath.Dir(skill.Path), "peer")
	if err := copyDir(skill.Path, peer.Path); err != nil {
		t.Fatal(err)
	}
	peerID, err := stageObservedSkill(home, inventory.Agents[0], peer, store)
	if err != nil {
		t.Fatal(err)
	}
	item, _ := store.PendingItem(peerID)
	_, release, err := withFileLocks(context.Background(), home, item.PendingPath)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	_, releaseAIDR, err := AIDRMutationLock(context.Background(), home)
	if err != nil {
		t.Fatal(err)
	}
	defer releaseAIDR()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := SubmitPending(ctx, home, server.URL, "test", store, id); err != nil {
		t.Fatal(err)
	}
}

func TestForegroundReusesBackgroundResultDespiteBusyFiles(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	id, err := stageObservedSkill(home, inventory.Agents[0], skill, store)
	if err != nil {
		t.Fatal(err)
	}
	entered, finish := make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(finish) }) }
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-finish
		w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
	}))
	defer server.Close()
	defer unblock()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	background := make(chan error, 1)
	go func() { _, e := SubmitPending(ctx, home, server.URL, "test", store, id); background <- e }()
	select {
	case <-entered:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	item, _ := store.PendingItem(id)
	_, release, err := withFileLocks(ctx, home, skill.Path, item.PendingPath)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	done := make(chan error, 1)
	go func() {
		result, e := SubmitDiscoveredSkillWithResult(ctx, home, NewAPI(server.URL, "test", time.Second), store, "codex", skill.Path, skill.Signature)
		if e == nil && !result.AlreadySubmitted {
			e = errors.New("background result not reused")
		}
		done <- e
	}()
	unblock()
	if err := <-background; err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestConcurrentForcedRescansReuseCompletedSubmission(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	first, err := stageObservedSkill(home, inventory.Agents[0], skill, store)
	if err != nil {
		t.Fatal(err)
	}
	alias := skill
	alias.Path = filepath.Join(filepath.Dir(skill.Path), "alias")
	if err := copyDir(skill.Path, alias.Path); err != nil {
		t.Fatal(err)
	}
	second, err := stageObservedSkill(home, inventory.Agents[0], alias, store)
	if err != nil {
		t.Fatal(err)
	}
	value, err := manifest.Build(skill.Path, DefaultManifestOptions())
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{first, second} {
		if err := store.UpdatePendingFingerprint(id, value.Fingerprint); err != nil {
			t.Fatal(err)
		}
		if err := store.SetState("pending:force-rescan:"+id, "1"); err != nil {
			t.Fatal(err)
		}
	}
	var uploads atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		uploads.Add(1)
		time.Sleep(100 * time.Millisecond)
		w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
	}))
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	done := make(chan error, 2)
	for _, id := range []string{first, second} {
		go func(id string) { _, err := SubmitPending(ctx, home, server.URL, "test", store, id); done <- err }(id)
	}
	for i := 0; i < 2; i++ {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
	if uploads.Load() != 1 {
		t.Fatalf("duplicate forced uploads: %d", uploads.Load())
	}
	for _, id := range []string{first, second} {
		flag, _, err := store.State("pending:force-rescan:" + id)
		if err != nil || flag != "" {
			t.Fatal("completed rescan left retry intent", flag, err)
		}
	}
}

func TestRescanIntentAndResetAreAtomic(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	id, err := stageObservedSkill(home, inventory.Agents[0], skill, store)
	if err != nil {
		t.Fatal(err)
	}
	item, err := store.PendingItem(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.MarkPendingSubmitted(item, "family", "v1"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`CREATE TRIGGER reject_rescan_intent BEFORE INSERT ON client_state
		WHEN NEW.key LIKE 'pending:force-rescan:%' BEGIN SELECT RAISE(ABORT,'injected failure'); END`); err != nil {
		t.Fatal(err)
	}
	if err := store.resetPendingForRescan(id); err == nil {
		t.Fatal("fault did not abort transaction")
	}
	item, err = store.PendingItem(id)
	if err != nil || item.SkillID != "family" || item.Status != "submitted" {
		t.Fatal("partial reset survived transaction failure", item, err)
	}
}

func TestSubmissionProcessHelper(t *testing.T) {
	if os.Getenv("SUBMISSION_HELPER") != "1" {
		return
	}
	home := os.Getenv("SUBMISSION_HOME")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	_, err = SubmitPending(context.Background(), home, os.Getenv("SUBMISSION_SERVER"), "test", store, os.Getenv("SUBMISSION_ID"))
	if err != nil {
		t.Fatal(err)
	}
}

func TestSubmissionProcessKillPreservesSnapshotAndRetry(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	id, err := stageObservedSkill(home, inventory.Agents[0], skill, store)
	if err != nil {
		t.Fatal(err)
	}
	entered := make(chan struct{})
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if requests.Add(1) == 1 {
			close(entered)
			<-r.Context().Done()
			return
		}
		w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
	}))
	defer server.Close()
	binary, _ := os.Executable()
	cmd := exec.Command(binary, "-test.run=^TestSubmissionProcessHelper$")
	cmd.Env = append(os.Environ(), "SUBMISSION_HELPER=1", "SUBMISSION_HOME="+home, "SUBMISSION_SERVER="+server.URL, "SUBMISSION_ID="+id)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
	select {
	case <-entered:
	case <-time.After(10 * time.Second):
		t.Fatal("child upload did not start")
	}
	_ = cmd.Process.Kill()
	_ = cmd.Wait()
	item, err := store.PendingItem(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := checkObservedContent(Skill{Path: item.PendingPath, Signature: skill.Signature}); err != nil {
		t.Fatal("interruption damaged snapshot", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := SubmitPending(ctx, home, server.URL, "test", store, id); err != nil {
		t.Fatal("interrupted upload cannot retry", err)
	}
	if requests.Load() != 2 {
		t.Fatalf("unexpected retry count: %d", requests.Load())
	}
}

func TestSubmissionUploadReleasesFilesAndCoordinatesForegroundBackground(t *testing.T) {
	home, store, inventory, skill := observedFixture(t)
	original, err := os.ReadFile(filepath.Join(skill.Path, "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	entered, finish := make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(finish) }) }
	defer unblock()
	var uploads atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/scanner/imports" {
			w.Write([]byte(`{}`))
			return
		}
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Error(err)
			w.WriteHeader(400)
			return
		}
		defer r.MultipartForm.RemoveAll()
		file, _, err := r.FormFile("file")
		if err != nil {
			t.Error(err)
			w.WriteHeader(400)
			return
		}
		defer file.Close()
		body, err := io.ReadAll(file)
		if err != nil {
			t.Error(err)
			return
		}
		archive, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
		if err != nil {
			t.Error(err)
			return
		}
		found := false
		for _, entry := range archive.File {
			if entry.Name == "SKILL.md" {
				f, _ := entry.Open()
				data, _ := io.ReadAll(f)
				f.Close()
				found = bytes.Equal(data, original)
			}
		}
		if !found {
			t.Error("upload differs from selected snapshot")
		}
		if uploads.Add(1) == 1 {
			close(entered)
		}
		<-finish
		w.Write([]byte(`{"skill_id":"family","version_id":"v1","status":"PENDING"}`))
	}))
	defer server.Close()
	defer unblock()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	done := make(chan error, 3)
	api := NewAPI(server.URL, "token", time.Second)
	go func() {
		_, err := SubmitDiscoveredSkillWithResult(ctx, home, api, store, "codex", skill.Path, skill.Signature)
		done <- err
	}()
	select {
	case <-entered:
	case <-ctx.Done():
		t.Fatal("upload did not start")
	}
	items, err := store.PendingItems()
	if err != nil || len(items) != 1 {
		t.Fatal(items, err)
	}
	id := items[0].ID
	// Background retry uses a separate connection, like the daemon process.
	background, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer background.Close()
	go func() { _, err := SubmitPending(ctx, home, server.URL, "token", background, id); done <- err }()
	// A second Agent path with the same bytes must join the same upload.
	alias := skill
	alias.Path = filepath.Join(filepath.Dir(skill.Path), "same-content")
	if err := copyDir(skill.Path, alias.Path); err != nil {
		t.Fatal(err)
	}
	aliasID, err := stageObservedSkill(home, inventory.Agents[0], alias, store)
	if err != nil {
		t.Fatal(err)
	}
	go func() { _, err := SubmitPending(ctx, home, server.URL, "token", store, aliasID); done <- err }()
	if _, err := store.DiscardPending(id); !errors.Is(err, ErrSkillActionBusy) {
		t.Fatalf("upload snapshot discarded: %v", err)
	}
	// A real local mutation can finish while the HTTP response remains blocked.
	if _, err := QuarantineSkill(home, store, "codex", skill.Name, skill.Path, "manual"); err != nil {
		t.Fatal("network held file lock", err)
	}
	if _, err := os.Stat(skill.Path); !os.IsNotExist(err) {
		t.Fatal("quarantine did not remove active path", err)
	}
	// The newer observation must survive the older upload response.
	if err := store.SaveObservation(skill.Path, SkillObservation{Signature: "newer", Certification: "unverified"}); err != nil {
		t.Fatal(err)
	}
	unblock()
	for i := 0; i < 3; i++ {
		select {
		case err := <-done:
			if err != nil {
				t.Fatal(err)
			}
		case <-ctx.Done():
			t.Fatal("submission deadlock")
		}
	}
	if uploads.Load() != 1 {
		t.Fatalf("duplicate uploads: %d", uploads.Load())
	}
	observation, err := store.Observation(skill.Path)
	if err != nil || observation.Signature != "newer" {
		t.Fatal("stale observation overwritten", observation, err)
	}
	if _, err := store.DiscardPending(id); err != nil {
		t.Fatal("completed snapshot cannot be discarded", err)
	}
}
