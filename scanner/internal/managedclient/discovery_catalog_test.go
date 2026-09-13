package managedclient

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestDiscoveryCatalogSyncAndOfflineDiscovery(t *testing.T) {
	home := t.TempDir()
	writeSkill(t, filepath.Join(home, ".qoder", "skills", "sample"), "sample")
	writeSkill(t, filepath.Join(home, "company-skills", "internal"), "internal")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	catalog := &DiscoveryCatalog{Version: "one", Agents: []AgentDefinition{
		{AgentType: "qoder", Name: "Qoder", Enabled: false, Systems: []string{runtime.GOOS}, SkillRoots: []string{".qoder/skills"}},
		{AgentType: "company", Name: "Company Agent", Enabled: true, Systems: []string{runtime.GOOS}, SkillRoots: []string{"~/company-skills"}},
		{AgentType: "missing", Name: "Missing", Enabled: true, Systems: []string{runtime.GOOS}, SkillRoots: []string{"~/absent/skills"}},
		{AgentType: "other-os", Name: "Other", Enabled: true, Systems: []string{"unknown"}, SkillRoots: []string{"~/company-skills"}},
	}}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"policy": Policy{Mode: "audit", AgentDiscovery: catalog}})
	}))
	if err := heartbeatOnce(context.Background(), home, NewAPI(server.URL, "test", time.Second), store); err != nil {
		t.Fatal(err)
	}
	server.Close()
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Agents) != 1 || inventory.Agents[0].AgentType != "company" || inventory.Agents[0].DisplayName != "Company Agent" || len(inventory.Agents[0].Skills) != 1 {
		t.Fatalf("unexpected discovery: %+v", inventory.Agents)
	}
	if _, err := os.Stat(filepath.Join(home, "absent")); !os.IsNotExist(err) {
		t.Fatal("discovery created an absent directory")
	}
	if cached := discoveryCatalog(home); cached == nil || cached.Version != "one" {
		t.Fatal("catalog not persisted")
	}
	catalog.Agents = nil
	body, _ := json.Marshal(Policy{Mode: "audit", AgentDiscovery: catalog})
	if err := store.SetState("policy", string(body)); err != nil {
		t.Fatal(err)
	}
	inventory, err = Discover(home)
	if err != nil || len(inventory.Agents) != 0 {
		t.Fatal("empty platform catalog did not disable discovery", err, inventory.Agents)
	}
}

func TestDiscoveryBuiltinsBeforeFirstSync(t *testing.T) {
	home := t.TempDir()
	for _, dir := range []string{".qoder", ".qoder-cn", ".qoderwork", ".zcode"} {
		writeSkill(t, filepath.Join(home, dir, "skills", "sample"), "sample")
	}
	inventory, err := Discover(home)
	if err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"qoder", "qoder-cn", "qoderwork", "zcode"} {
		agent, ok := findAgent(inventory, kind)
		if !ok || len(agent.Skills) != 1 {
			t.Fatal("missing builtin", kind)
		}
	}
}

func TestRunOnceUsesNewCatalogBeforeComparingSkills(t *testing.T) {
	home := t.TempDir()
	writeSkill(t, filepath.Join(home, ".qoder", "skills", "sample"), "sample")
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	comparedDisabled := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/heartbeat"):
			json.NewEncoder(w).Encode(map[string]any{"policy": Policy{Mode: "audit", AgentDiscovery: &DiscoveryCatalog{Version: "empty", Agents: []AgentDefinition{}}}})
		case strings.HasSuffix(r.URL.Path, "/compare"):
			var body struct {
				Agents []Agent `json:"agents"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			comparedDisabled = len(body.Agents) != 0
			w.Write([]byte(`{"items":[]}`))
		case strings.HasSuffix(r.URL.Path, "/tasks"):
			w.Write([]byte(`[]`))
		default:
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	if err := RunOnce(context.Background(), home, NewAPI(server.URL, "test", time.Second), store); err != nil {
		t.Fatal(err)
	}
	if comparedDisabled {
		t.Fatal("patrol used Agent removed by newly synced catalog")
	}
}
