package managedclient

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestDesktopPlatformContracts(t *testing.T) {
	home, _ := desktopFixture(t)
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Header.Get("Authorization") != "Bearer fixture-token" {
			t.Error("credential not supplied from local config")
		}
		switch r.URL.Path {
		case "/api/v1/clients/test-client/status":
			if r.Method != "GET" {
				t.Error(r.Method)
			}
		case "/api/v1/clients/test-client/history":
			if r.URL.Query().Get("keyword") != "原始 & ? /" {
				t.Error(r.URL.RawQuery)
			}
		case "/api/v1/clients/test-client/model-catalog/refresh":
			var body map[string]string
			json.NewDecoder(r.Body).Decode(&body)
			if r.Method != "POST" || body["local_agent_id"] != "local" || body["agent_type"] != "codex" || body["managed_agent_id"] != "managed" {
				t.Errorf("unexpected model request: %s %v", r.Method, body)
			}
		default:
			t.Error(r.URL.Path)
		}
		w.Write([]byte(`{"items":[],"ok":true}`))
	}))
	defer server.Close()
	if err := SaveConfig(home, Config{Server: server.URL, Token: "fixture-token"}); err != nil {
		t.Fatal(err)
	}
	for _, method := range []string{"platform-status", "platform-history", "model-catalog"} {
		result, err := DesktopPlatform(context.Background(), home, DesktopRequest{Version: 1, Method: method, Filters: map[string]string{"keyword": "原始 & ? /"}, LocalAgentID: "local", AgentType: "codex", ManagedAgentID: "managed"})
		if err != nil || !json.Valid(result) {
			t.Fatalf("%s: %s %v", method, result, err)
		}
	}
	if _, err := DesktopPlatform(context.Background(), home, DesktopRequest{Method: "https://untrusted"}); err == nil || calls != 3 {
		t.Fatal("unknown operation reached network")
	}
}

func TestDesktopPlatformSlowRequestsLeaveSnapshotCapacity(t *testing.T) {
	home, _ := desktopFixture(t)
	entered := make(chan struct{}, 2)
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		entered <- struct{}{}
		select {
		case <-release:
		case <-r.Context().Done():
		}
		w.Write([]byte(`{}`))
	}))
	defer server.Close()
	defer close(release)
	SaveConfig(home, Config{Server: server.URL, Token: "fixture"})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- serveDesktop(ctx, home, listener) }()
	defer func() { cancel(); <-done }()
	call := func(method string) (map[string]any, error) {
		conn, err := net.Dial("tcp", listener.Addr().String())
		if err != nil {
			return nil, err
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(3 * time.Second))
		json.NewEncoder(conn).Encode(DesktopRequest{Version: 1, Method: method})
		var response map[string]any
		err = json.NewDecoder(conn).Decode(&response)
		return response, err
	}
	for i := 0; i < 2; i++ {
		go func() { call("platform-status") }()
		select {
		case <-entered:
		case <-time.After(3 * time.Second):
			t.Fatal("platform request did not start")
		}
	}
	value, err := call("platform-history")
	if err != nil || value["error"] != "client_ipc_busy" {
		t.Fatalf("overload: %v %v", value, err)
	}
	value, err = call("snapshot")
	if err != nil || value["inventory"] == nil {
		t.Fatalf("snapshot blocked: %v %v", value, err)
	}
}

func TestDesktopPlatformFailures(t *testing.T) {
	home, _ := desktopFixture(t)
	for _, tc := range []struct {
		status     int
		body, code string
	}{
		{401, "denied", "client_history_http_401"},
		{503, "unavailable", "client_history_http_503"},
		{200, "invalid json", "client_history_invalid_response"},
		{200, strings.Repeat(" ", 16*1024*1024) + "{}", "client_history_invalid_response"},
	} {
		t.Run(tc.code, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(tc.status); w.Write([]byte(tc.body)) }))
			defer server.Close()
			SaveConfig(home, Config{Server: server.URL, Token: "fixture-token"})
			_, err := DesktopPlatform(context.Background(), home, DesktopRequest{Method: "platform-history"})
			if err == nil || !strings.HasPrefix(err.Error(), tc.code) || strings.Contains(err.Error(), "fixture-token") {
				t.Fatal(err)
			}
		})
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := DesktopPlatform(ctx, home, DesktopRequest{Method: "platform-history"}); err == nil {
		t.Fatal("cancelled request succeeded")
	}
}
