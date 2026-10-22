package localstore

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

func TestDoubaoAcknowledgedHistoryTurnBackfill(t *testing.T) {
	store := openStore(t, tempDir(t), DefaultLimits())
	defer store.Close()
	base := tempDir(t)
	root := filepath.Join(base, "Default/.doubaowork/agent_mode/workspace/.sessions")
	path := filepath.Join(root, "session", "agents", "main", "system", "trajectory.jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	raw := `{"role":"assistant","tool_calls":[{"id":"call-a","function":{"name":"Bash","arguments":{"command":"printf safe"}}}]}` + "\n" + `{"role":"tool","tool_call_id":"call-a","content":"safe"}` + "\n"
	if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	src, err := agentlog.NewSource("doubaowork", root, path)
	if err != nil {
		t.Fatal(err)
	}
	policy := agentlog.AuditPolicy{Version: "2", Receipt: strings.Repeat("a", 32), Enabled: true, Capture: &agentlog.CaptureScope{}}
	if err := store.SavePolicy(testContext, policy); err != nil {
		t.Fatal(err)
	}
	collect(t, store, src)
	for {
		batch, err := store.Prepare(testContext, 500, 1<<20)
		if err != nil {
			t.Fatal(err)
		}
		if batch == nil {
			break
		}
		if err := store.Acknowledge(testContext, batch.ID, batch.Digest); err != nil {
			t.Fatal(err)
		}
	}
	logRoot := filepath.Join(base, "sdk_storage", "log")
	if err := os.MkdirAll(logRoot, 0700); err != nil {
		t.Fatal(err)
	}
	front := `[1:2:1021/100000:INFO:FRONTEND(0)] [neotix] [office-api-logger] "[webview][unknown][flow-web][logifier-report]: {"eventName":"on_message_receiving_start","meta":{"chat_session_id":"agent-a","send_message_id":"message-a"}}", source: (0)` + "\n"
	runtime := `[1:2:1021/100000:INFO:aha/saman_sandbox_shell_api_metrics.cc(113)] [sandbox] shell api call, api_name=sandbox.bash.run, status=enter, sandbox_log_id={"conversation_id":"session","agent_id":"agent-a","tcid":"call-a"}, result=<none>` + "\n"
	for name, value := range map[string]string{"saman_frontend_2026.1021.0.log": front, "saman_2026.1021.0.log": runtime} {
		if err := os.WriteFile(filepath.Join(logRoot, name), []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	budget := agentlog.DefaultBudget()
	budget.Events = 1
	for i := 0; i < 4; i++ {
		if _, err := store.Collect(testContext, src, budget, time.Unix(0, 0)); err != nil {
			t.Fatal(err)
		}
	}
	var events, links, bodies int
	store.db.QueryRow(`SELECT count(*),count(payload) FROM logical_events`).Scan(&events, &bodies)
	store.db.QueryRow(`SELECT count(*) FROM event_turn_links WHERE turn_id='message-a'`).Scan(&links)
	if events != 2 || links != 2 || bodies != 0 {
		t.Fatalf("events=%d links=%d retained bodies=%d", events, links, bodies)
	}
	batch, err := store.Prepare(testContext, 500, 1<<20)
	if err != nil || batch == nil {
		t.Fatal("metadata batch missing", err)
	}
	if !strings.Contains(string(batch.Payload), `"turn_links"`) || strings.Contains(string(batch.Payload), `"kind":"event"`) || strings.Contains(string(batch.Payload), `"doubao_turns"`) {
		t.Fatal("backfill changed evidence or leaked local state")
	}
}
