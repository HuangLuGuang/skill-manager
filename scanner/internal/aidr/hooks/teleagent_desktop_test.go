package hooks

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func teleAgentTestHome(t *testing.T) string {
	t.Helper()
	if runtime.GOOS != "darwin" {
		t.Skip("desktop integration is macOS-only")
	}
	home := t.TempDir()
	binary := filepath.Join(home, ".local/share/TeleAgent/runtimes/super-agent-code/bin/TeleAgent")
	if e := os.MkdirAll(filepath.Dir(binary), 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(binary, []byte("test fixture"), 0700); e != nil {
		t.Fatal(e)
	}
	return home
}
func TestTeleAgentDesktopPreservesAndRestoresConfiguration(t *testing.T) {
	home := teleAgentTestHome(t)
	original := "# preserved settings\nllmBaseUrl: https://example.com/original\nllmPerformance: true\ncustom:\n  key: value\n"
	os.WriteFile(teleAgentConfigPath(home), []byte(original), 0600)
	status, e := configureTeleAgentDesktop(home, false)
	if e != nil || status.Installed == nil || !*status.Installed {
		t.Fatalf("install: %+v %v", status, e)
	}
	first, _ := os.ReadFile(teleAgentConfigPath(home))
	if _, e = configureTeleAgentDesktop(home, false); e != nil {
		t.Fatal(e)
	}
	second, _ := os.ReadFile(teleAgentConfigPath(home))
	if string(first) != string(second) {
		t.Fatal("installation is not idempotent")
	}
	doc, _ := readTeleAgentYAML(home)
	var actual map[string]any
	doc.Decode(&actual)
	if actual["llmPerformance"] != true || !strings.Contains(string(first), "preserved settings") {
		t.Fatal("lost unrelated settings")
	}
	status, e = configureTeleAgentDesktop(home, true)
	if e != nil || *status.Installed {
		t.Fatalf("remove: %v", e)
	}
	doc, _ = readTeleAgentYAML(home)
	_, n := teleAgentURLNode(doc)
	if n.Value != "https://example.com/original" {
		t.Fatal("upstream not restored")
	}
	if !TeleAgentProxyRequired(home) {
		t.Fatal("running host still needs proxy after disconnect")
	}
	// Refuse to overwrite a concurrent host configuration change.
	configureTeleAgentDesktop(home, false)
	os.WriteFile(teleAgentConfigPath(home), []byte("llmBaseUrl: https://example.com/new\n"), 0600)
	if _, e = configureTeleAgentDesktop(home, true); e == nil {
		t.Fatal("overwrote external change")
	}
}
func TestTeleAgentDesktopLiveProxyAndDisable(t *testing.T) {
	home := teleAgentTestHome(t)
	paths := make(chan string, 8)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { paths <- r.URL.Path; w.Write([]byte("original-service")) }))
	defer upstream.Close()
	os.WriteFile(teleAgentConfigPath(home), []byte("llmBaseUrl: "+upstream.URL+"/original\n"), 0600)
	if _, e := configureTeleAgentDesktop(home, false); e != nil {
		t.Fatal(e)
	}
	s, _ := readTeleAgentState(home)
	connection := filepath.Join(home, "bridge.json")
	os.WriteFile(connection, []byte(`{"active":true,"agents":["teleagent"]}`), 0600)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go func() { runTeleAgentDesktop(ctx, home, "/missing-receiver.sock", connection); close(done) }()
	client := &http.Client{Timeout: 2 * time.Second}
	get := func(path string) string {
		t.Helper()
		r, e := client.Get(s.base() + path)
		if e != nil {
			t.Fatal(e)
		}
		defer r.Body.Close()
		b, _ := io.ReadAll(r.Body)
		return string(b)
	}
	deadline := time.Now().Add(3 * time.Second)
	for {
		r, e := client.Get(s.base() + "/api/v1/models")
		if e == nil {
			r.Body.Close()
			break
		}
		if time.Now().After(deadline) {
			t.Fatal(e)
		}
		time.Sleep(20 * time.Millisecond)
	}
	if path := <-paths; path != "/original/api/v1/models" {
		t.Fatal(path)
	}
	payload := `{"root_id":"session","caller_id":"call","caller_type":"tool","data_type":"BeforeToolExecute","data":"{}","extra":{"tool_info":{"tool_id":"bash"}}}`
	r, e := client.Post(s.base()+"/api/v1/security/instruction/review", "application/json", strings.NewReader(payload))
	if e != nil {
		t.Fatal(e)
	}
	var denied map[string]any
	json.NewDecoder(r.Body).Decode(&denied)
	r.Body.Close()
	raw, _ := json.Marshal(denied)
	if !strings.Contains(string(raw), `"result":2`) {
		t.Fatalf("missing receiver should deny: %s", raw)
	}
	// Corrupt local enrollment configuration must not fall back to upstream review.
	os.WriteFile(connection, []byte("invalid"), 0600)
	r, e = client.Post(s.base()+"/api/v1/security/instruction/review", "application/json", strings.NewReader(payload))
	if e != nil {
		t.Fatal(e)
	}
	b, _ := io.ReadAll(r.Body)
	r.Body.Close()
	if !strings.Contains(string(b), `"result":2`) {
		t.Fatalf("invalid config did not deny: %s", b)
	}
	if _, e = configureTeleAgentDesktop(home, true); e != nil {
		t.Fatal(e)
	}
	if got := get("/api/v1/security/instruction/review"); got != "original-service" {
		t.Fatal(got)
	}
	if path := <-paths; path != "/original/api/v1/security/instruction/review" {
		t.Fatal(path)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("listener did not stop")
	}
}
