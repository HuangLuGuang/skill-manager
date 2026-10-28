package upload

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"skill-manager/scanner/internal/aidr/hooks"
)

func TestHookRuntimeUsesActualReceiverAndExactReceipt(t *testing.T) {
	ctx := context.Background()
	var corrupt bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/clients/device/aidr/hook-runtime" || r.Header.Get("Authorization") != "Bearer synthetic-token" {
			t.Error("runtime report routing or authentication")
		}
		var body map[string]any
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Fatal("invalid report")
		}
		if len(body) != 13 || body["approval_wait_schema"] != float64(1) || body["command_rules_schema"] != float64(1) || body["control_mode"] != "audit" || body["control_code"] != "aidr_hook_audit_only" || body["control_revision"] != "" || body["queued_records"] != float64(0) || body["last_event_ack_at"] != "" {
			t.Error("runtime report is not bounded actual state")
		}
		receiver := body["receiver_instance"]
		if corrupt {
			receiver = "wrong-instance"
		}
		json.NewEncoder(w).Encode(map[string]any{"code": "aidr_hook_runtime_received", "receiver_instance": receiver, "report_sequence": body["report_sequence"]})
	}))
	defer server.Close()
	c, err := New(Options{Server: server.URL, ClientID: "device", Token: "synthetic-token"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := hooks.OpenStore(filepath.Join(root, "runtime"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	code, err := c.ReportHookRuntime(ctx, s, 9007199254740993)
	if err != nil || code != "aidr_hook_runtime_received" {
		t.Fatalf("%s %v", code, err)
	}
	corrupt = true
	code, err = c.ReportHookRuntime(ctx, s, 9007199254740994)
	if err != nil || code != "aidr_hook_runtime_ack_invalid" {
		t.Fatalf("%s %v", code, err)
	}
	state, _ := s.Status(ctx)
	if state.Queued != 0 || state.LastSequence != "0" {
		t.Fatal("telemetry modified audit sequence")
	}
}

func TestHookPolicyTransportAndFrozenACK(t *testing.T) {
	ctx := context.Background()
	var phase atomic.Int32
	var frozen []byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer synthetic-device-token" {
			t.Error("device credential missing")
		}
		if strings.HasSuffix(r.URL.Path, "audit-policy") {
			var request map[string]string
			if json.NewDecoder(r.Body).Decode(&request) != nil {
				t.Error("policy request invalid")
			}
			if phase.Load() == 0 {
				w.WriteHeader(503)
				return
			}
			json.NewEncoder(w).Encode(map[string]any{"version": "2", "enabled": false, "receipt": strings.Repeat("b", 32)})
			return
		}
		if r.URL.Path != "/api/v1/clients/device/aidr/hooks:batch" {
			t.Error("wrong hook route")
		}
		raw, _ := io.ReadAll(r.Body)
		if frozen == nil {
			frozen = append([]byte{}, raw...)
		} else if string(frozen) != string(raw) {
			t.Error("retry changed frozen batch")
		}
		var b struct {
			Stream  string         `json:"stream_id"`
			Records []hooks.Record `json:"records"`
		}
		if json.Unmarshal(raw, &b) != nil || len(b.Records) != 1 {
			t.Error("invalid projection")
		}
		sum := sha256.Sum256(raw)
		hash := hex.EncodeToString(sum[:])
		if phase.Load() < 2 {
			hash = strings.Repeat("0", 64)
		}
		json.NewEncoder(w).Encode(map[string]any{"schema_version": 1, "client_id": "device", "stream_id": b.Stream, "digest": hash, "accepted": 1, "durable": true})
	}))
	defer server.Close()
	c, err := New(Options{Server: server.URL, ClientID: "device", Token: "synthetic-device-token"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s, err := hooks.OpenStore(filepath.Join(root, "hooks"), server.URL, "device", 10)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	code, err := c.RefreshHookPolicy(ctx, s)
	state, _ := s.Status(ctx)
	if err != nil || code != "aidr_policy_cached" || !state.Policy.Enabled {
		t.Fatal("first offline policy not safe default")
	}
	id, err := hooks.NewEventID()
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Receive(ctx, id, "501", "codex", "SessionStart", []byte(`{"hook_event_name":"SessionStart","session_id":"s"}`)); err != nil {
		t.Fatal(err)
	}
	result, err := c.SendHooks(ctx, s)
	if err != nil || result.Code != "aidr_hook_ack_invalid" {
		t.Fatal("wrong ACK not rejected")
	}
	if err = s.SetRuntimeCollection(ctx, false, "9:2"); err != nil {
		t.Fatal(err)
	}
	phase.Store(1)
	code, err = c.RefreshHookPolicy(ctx, s)
	state, _ = s.Status(ctx)
	if err != nil || code != "aidr_policy_applied" || state.Policy.Enabled || state.AppliedAfter != "1" {
		t.Fatal("policy frontier incorrect")
	}
	phase.Store(2)
	result, err = c.SendHooks(ctx, s)
	state, _ = s.Status(ctx)
	if err != nil || !result.Uploaded || state.Queued != 0 || state.LastAcknowledgedAt == "" {
		t.Fatal("valid durable ACK not applied")
	}
	other, err := New(Options{Server: server.URL, ClientID: "other", Token: "synthetic-device-token"})
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	if _, err = other.SendHooks(ctx, s); err == nil {
		t.Fatal("cross-device queue permitted")
	}
}
