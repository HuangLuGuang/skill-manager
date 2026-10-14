package hooks

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestTeleAgentServiceStagesUpdatesWithoutReplacingUnchangedBinary(t *testing.T) {
	dir := t.TempDir()
	source, target := filepath.Join(dir, "source"), filepath.Join(dir, "proxy")
	os.WriteFile(source, []byte("version-one"), 0700)
	if err := stageTeleAgentProxy(source, target); err != nil {
		t.Fatal(err)
	}
	old, _ := os.Open(target)
	defer old.Close()
	before, _ := old.Stat()
	if err := stageTeleAgentProxy(source, target); err != nil {
		t.Fatal(err)
	}
	after, _ := os.Stat(target)
	if !os.SameFile(before, after) {
		t.Fatal("unchanged executable replaced")
	}
	os.WriteFile(source, []byte("version-two"), 0700)
	if err := stageTeleAgentProxy(source, target); err != nil {
		t.Fatal(err)
	}
	data, _ := io.ReadAll(old)
	if string(data) != "version-one" {
		t.Fatal("running executable was modified")
	}
	data, _ = os.ReadFile(target)
	if string(data) != "version-two" {
		t.Fatal("next-start executable not updated")
	}
	path, body := teleAgentServiceDefinition("/tmp/client & home", target)
	if !strings.Contains(path, teleAgentServiceLabel("/tmp/client & home")) || !bytes.Contains(body, []byte("client &amp; home")) || bytes.Contains(body, []byte("parent-stdin")) {
		t.Fatal("invalid independent service definition")
	}
}

func TestTeleAgentLaunchAgentSurvivesLauncherExitAndReconcileDuringStream(t *testing.T) {
	binary := os.Getenv("AGENT_MANAGER_TELEAGENT_SERVICE_TEST_BINARY")
	if binary == "" {
		t.Skip("requires built client and a macOS GUI launchd domain")
	}
	home := teleAgentTestHome(t)
	release := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/stream") {
			w.Header().Set("Content-Type", "text/event-stream")
			fmt.Fprintln(w, "data: first")
			w.(http.Flusher).Flush()
			select {
			case <-release:
			case <-r.Context().Done():
				return
			}
			fmt.Fprintln(w, "data: last")
			return
		}
		fmt.Fprint(w, "model-ok")
	}))
	defer upstream.Close()
	defer close(release)
	os.WriteFile(teleAgentConfigPath(home), []byte("llmBaseUrl: "+upstream.URL+"/original\n"), 0600)
	if _, err := configureTeleAgentDesktop(home, false); err != nil {
		t.Fatal(err)
	}
	state, _ := readTeleAgentState(home)
	domain := fmt.Sprintf("gui/%d/%s", os.Getuid(), teleAgentServiceLabel(home))
	t.Cleanup(func() { _ = teleAgentLaunchctl("bootout", domain) })
	ensure := func() {
		t.Helper()
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, binary, "aidr-teleagent-service", "--home", home, "--action", "ensure")
		if output, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("service ensure: %v %s", err, output)
		}
	}
	ensure()
	client := &http.Client{Timeout: 15 * time.Second, Transport: &http.Transport{Proxy: nil}}
	defer client.CloseIdleConnections()
	deadline := time.Now().Add(10 * time.Second)
	for {
		r, err := client.Get(state.base() + "/_agent_manager/health")
		if err == nil {
			r.Body.Close()
			if r.StatusCode == 200 {
				break
			}
		}
		if time.Now().After(deadline) {
			t.Fatal("independent proxy did not become healthy")
		}
		time.Sleep(50 * time.Millisecond)
	}
	// No receiver exists. Model forwarding must still work after the launcher exits.
	r, err := client.Get(state.base() + "/api/v1/models")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(r.Body)
	r.Body.Close()
	if string(body) != "model-ok" {
		t.Fatal("model forwarding depends on receiver")
	}
	r, err = client.Get(state.base() + "/stream")
	if err != nil {
		t.Fatal(err)
	}
	defer r.Body.Close()
	reader := bufio.NewReader(r.Body)
	first, err := reader.ReadString('\n')
	if err != nil || first != "data: first\n" {
		t.Fatal("stream did not start", err)
	}
	// Repeated desktop startup/update reconciliation must not restart the proxy.
	ensure()
	ensure()
	// Close the stream gate without double-closing the deferred cleanup channel.
	release <- struct{}{}
	last, err := reader.ReadString('\n')
	if err != nil || last != "data: last\n" {
		t.Fatal("reconcile interrupted active model stream", err)
	}
	if _, err = configureTeleAgentDesktop(home, true); err != nil {
		t.Fatal(err)
	}
	r, err = client.Get(state.base() + "/api/v1/models")
	if err != nil {
		t.Fatal("disconnect stranded a running TeleAgent", err)
	}
	r.Body.Close()
}
