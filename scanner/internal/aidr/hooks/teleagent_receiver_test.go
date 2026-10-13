//go:build darwin || linux

package hooks

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestTeleAgentHTTPThroughReceiverSignedPolicyAndOutbox(t *testing.T) {
	root, err := os.MkdirTemp("", "ta-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	root, _ = filepath.EvalSymlinks(root)
	s := openTestStore(t, filepath.Join(root, "state"), 20)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err = s.ConfigureControl(ctx, elliptic.Marshal(elliptic.P256(), key.X, key.Y)); err != nil {
		t.Fatal(err)
	}
	p := ToolPolicy{Schema: 3, Domain: "aidr.tool-policy/3", Device: "device-a", Revision: "1", Issued: fmt.Sprint(time.Now().Unix()), Default: "allow", Rules: []ToolRule{{ID: "deny-shell", Agent: "teleagent", Tool: "bash", Decision: "deny", Command: &CommandCondition{Executable: "printf", ArgsAll: []string{"test"}}}}}
	if err = s.ApplyToolPolicy(ctx, signGrant(t, key, p), time.Now()); err != nil {
		t.Fatal(err)
	}
	socket := filepath.Join(root, "r.sock")
	receiver, err := Listen(socket, s)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- receiver.Serve(ctx) }()
	defer func() { cancel(); <-done }()
	secret := strings.Repeat("c", 64)
	handler, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: socket, Secret: secret, Exchange: func(ctx context.Context, path string, req IPCRequest) (IPCResponse, error) {
		r, e := Exchange(ctx, path, req)
		t.Logf("receiver code=%s decision=%+v err=%v", r.Code, r.Decision, e)
		return r, e
	}})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	defer server.Close()
	response, err := http.Post(server.URL+"/"+secret+"/security/instruction/review", "application/json", strings.NewReader(teleReview))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var body struct {
		Data struct {
			Result int
			Reason string
		}
	}
	if json.NewDecoder(response.Body).Decode(&body) != nil || body.Data.Result != 2 || body.Data.Reason != "aidr_hook_rule_deny" {
		t.Fatalf("decision %+v", body)
	}
	batch, err := s.Prepare(ctx)
	if err != nil || batch == nil {
		t.Fatal("event not queued", err)
	}
	if !strings.Contains(string(batch.Payload), `"agent":"teleagent"`) || !strings.Contains(string(batch.Payload), `"decision":"deny"`) {
		t.Fatal("missing normalized audit/decision", string(batch.Payload))
	}
}
