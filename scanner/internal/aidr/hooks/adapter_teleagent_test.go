package hooks

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

const teleReview = `{"root_id":"session","message_id":"message","caller_id":"call","sub_agent":"build","caller_type":"tool","worktree":"/workspace","data_type":"input","data":"{\"command\":\"printf test\"}","extra":{"tool_info":{"tool_id":"bash"}}}`

func TestTeleAgentNativeDecodeAndIsolation(t *testing.T) {
	p := agentlog.AuditPolicy{Version: "1", Enabled: true, Receipt: strings.Repeat("a", 32)}
	e, err := Normalize("teleagent", "BeforeToolExecute", []byte(teleReview), p, bytes.Repeat([]byte{1}, 32))
	if err != nil || e.Tool != "bash" || e.Session != "session" || e.Call != "call" || e.Subagent != "" || e.Turn != "" || e.InputDigest == "" {
		t.Fatalf("%+v %v", e, err)
	}
	if e.Context != nil && e.Context.Cwd != "" {
		t.Fatal("project worktree was used as a working directory")
	}
	for _, action := range e.Behavior.Actions {
		if action.Cwd != "" {
			t.Fatal("project worktree was used as a tool working directory")
		}
	}
	if _, err = Normalize("codex", "PreToolUse", []byte(teleReview), p, bytes.Repeat([]byte{1}, 32)); err == nil {
		t.Fatal("native protocol crossed adapter boundary")
	}
	mcp := strings.ReplaceAll(teleReview, `"caller_type":"tool"`, `"caller_type":"mcp"`)
	mcp = strings.ReplaceAll(mcp, `"tool_info":{"tool_id":"bash"}`, `"mcp_info":{"mcp_server":"local","mcp_tool":"read","mcp_config":"PRIVATE_CONFIG"}`)
	e, err = Normalize("teleagent", "BeforeMCPExecute", []byte(mcp), p, bytes.Repeat([]byte{1}, 32))
	if err != nil || e.Tool != "mcp__local__read" {
		t.Fatal(e, err)
	}
	raw, _ := json.Marshal(e)
	if bytes.Contains(raw, []byte("PRIVATE_CONFIG")) {
		t.Fatal("native MCP configuration persisted")
	}
}

func TestTeleAgentHTTPDecisionAndFailure(t *testing.T) {
	secret := strings.Repeat("a", 64)
	for _, tc := range []struct {
		name     string
		result   int
		exchange func(context.Context, string, IPCRequest) (IPCResponse, error)
	}{
		{"allow", 1, func(context.Context, string, IPCRequest) (IPCResponse, error) {
			return IPCResponse{Decision: &ToolDecision{Decision: "allow"}}, nil
		}},
		{"deny", 2, func(context.Context, string, IPCRequest) (IPCResponse, error) {
			return IPCResponse{Decision: &ToolDecision{Decision: "deny"}}, nil
		}},
		{"audit", 1, func(context.Context, string, IPCRequest) (IPCResponse, error) {
			return IPCResponse{Code: "aidr_hook_recorded", State: &StoreStatus{ControlMode: "audit"}}, nil
		}},
		{"missing_decision", 2, func(context.Context, string, IPCRequest) (IPCResponse, error) {
			return IPCResponse{Code: "aidr_hook_recorded", State: &StoreStatus{ControlMode: "plugin_pre_tool"}}, nil
		}},
		{"failure", 2, func(context.Context, string, IPCRequest) (IPCResponse, error) {
			return IPCResponse{}, errors.New("private failure")
		}},
		{"timeout", 2, func(ctx context.Context, _ string, _ IPCRequest) (IPCResponse, error) {
			<-ctx.Done()
			return IPCResponse{}, ctx.Err()
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: "/private/socket", Secret: secret, Exchange: tc.exchange})
			if err != nil {
				t.Fatal(err)
			}
			r := httptest.NewRequest(http.MethodPost, "http://127.0.0.1/"+secret+"/security/instruction/review", strings.NewReader(teleReview))
			r.RemoteAddr = "127.0.0.1:1234"
			w := httptest.NewRecorder()
			start := time.Now()
			h.ServeHTTP(w, r)
			var response struct{ Data struct{ Result int } }
			if json.Unmarshal(w.Body.Bytes(), &response) != nil || response.Data.Result != tc.result || w.Code != 200 {
				t.Fatal(w.Code, w.Body.String())
			}
			if time.Since(start) > 2*time.Second {
				t.Fatal("response exceeded native MCP review deadline")
			}
			if strings.Contains(w.Body.String(), "private failure") {
				t.Fatal("error detail leaked")
			}
		})
	}
}

func TestTeleAgentHTTPAuthentication(t *testing.T) {
	h, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: "/private/socket", Secret: strings.Repeat("b", 64), Exchange: func(context.Context, string, IPCRequest) (IPCResponse, error) {
		t.Fatal("unauthenticated submission")
		return IPCResponse{}, nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("POST", "http://127.0.0.1/wrong/security/instruction/review", strings.NewReader(teleReview))
	r.RemoteAddr = "127.0.0.1:1234"
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal(w.Code)
	}
}

func TestRegisteredHookAdaptersCoverCatalog(t *testing.T) {
	for agent := range catalog {
		a, ok := hookAdapters[agent]
		if !ok || a.Decode == nil || a.WriteDecision == nil {
			t.Fatalf("missing %s", agent)
		}
	}
}
