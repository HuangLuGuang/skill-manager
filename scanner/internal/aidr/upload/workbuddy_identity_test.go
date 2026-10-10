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
	"testing"

	"skill-manager/scanner/internal/aidr/hooks"
)

func TestWorkBuddyHookIdentityThroughQueueAndUpload(t *testing.T) {
	for _, hook := range []string{"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"} {
		for _, turn := range []string{"", "native-turn-1"} {
			t.Run(hook+"/turn="+turn, func(t *testing.T) {
				requests := 0
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					requests++
					raw, err := io.ReadAll(r.Body)
					if err != nil {
						t.Error(err)
						w.WriteHeader(500)
						return
					}
					var batch struct {
						Stream  string         `json:"stream_id"`
						Records []hooks.Record `json:"records"`
					}
					if err := json.Unmarshal(raw, &batch); err != nil || len(batch.Records) != 1 {
						t.Errorf("invalid batch: %v", err)
						w.WriteHeader(500)
						return
					}
					event := batch.Records[0].Event
					if event.Agent != "workbuddy" || event.Session != "native-session-1" || event.Turn != turn {
						t.Errorf("identity changed: agent=%q session=%q turn=%q", event.Agent, event.Session, event.Turn)
					}
					if (hook == "PreToolUse" || hook == "PostToolUse") && event.Call != "native-call-1" {
						t.Errorf("tool call ID lost: %q", event.Call)
					}
					sum := sha256.Sum256(raw)
					json.NewEncoder(w).Encode(map[string]any{"schema_version": 1, "client_id": "device", "stream_id": batch.Stream, "digest": hex.EncodeToString(sum[:]), "accepted": 1, "durable": true})
				}))
				defer server.Close()
				client, err := New(Options{Server: server.URL, ClientID: "device", Token: "synthetic-token"})
				if err != nil {
					t.Fatal(err)
				}
				defer client.Close()
				root, err := filepath.EvalSymlinks(t.TempDir())
				if err != nil {
					t.Fatal(err)
				}
				store, err := hooks.OpenStore(filepath.Join(root, "hooks"), server.URL, "device", 10)
				if err != nil {
					t.Fatal(err)
				}
				defer store.Close()
				// WorkBuddy command hooks carry session/tool IDs independently of turn_id.
				input := map[string]any{"hook_event_name": hook, "session_id": "native-session-1", "cwd": "/tmp/synthetic-project", "transcript_path": "/tmp/synthetic-session.jsonl"}
				if turn != "" {
					input["turn_id"] = turn
				}
				if hook == "UserPromptSubmit" {
					input["prompt"] = "synthetic question"
				}
				if hook == "PreToolUse" || hook == "PostToolUse" {
					input["tool_use_id"], input["call_id"] = "native-call-1", "native-call-1"
					input["tool_name"] = "Bash"
					input["tool_input"] = map[string]string{"command": "pwd"}
				}
				if hook == "PostToolUse" {
					input["tool_response"] = "synthetic output"
				}
				raw, err := json.Marshal(input)
				if err != nil {
					t.Fatal(err)
				}
				id, err := hooks.NewEventID()
				if err != nil {
					t.Fatal(err)
				}
				if _, err := store.Receive(context.Background(), id, "501", "workbuddy", hook, raw); err != nil {
					t.Fatal(err)
				}
				result, err := client.SendHooks(context.Background(), store)
				if err != nil || !result.Uploaded || requests != 1 {
					t.Fatalf("upload failed: result=%+v err=%v requests=%d", result, err, requests)
				}
			})
		}
	}
}
