package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/localstore"
)

func TestAidrSyncDurationReleasesWriter(t *testing.T) {
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	defer server.Close()
	t.Setenv("AIDR_TEST_TOKEN", "synthetic-test-token")
	var out bytes.Buffer
	started := time.Now()
	err = aidrSync([]string{"--state-dir", filepath.Join(root, "state"), "--server", server.URL, "--client-id", "device-one", "--token-env", "AIDR_TEST_TOKEN", "--claude-root", root, "--codex-root", root, "--duration", "150ms"}, &out)
	if err != nil || !json.Valid(out.Bytes()) || time.Since(started) > 3*time.Second {
		t.Fatal(err, out.String())
	}
	store, err := localstore.Open(filepath.Join(root, "state"), localstore.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err = store.Status(context.Background()); err != nil {
		t.Fatal(err)
	}
}
