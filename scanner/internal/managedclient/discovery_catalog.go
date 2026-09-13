package managedclient

import (
	"database/sql"
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
)

type AgentDefinition struct {
	AgentType  string   `json:"agent_type"`
	Name       string   `json:"name"`
	Enabled    bool     `json:"enabled"`
	Systems    []string `json:"systems"`
	SkillRoots []string `json:"skill_roots"`
}
type DiscoveryCatalog struct {
	Version string            `json:"version"`
	Agents  []AgentDefinition `json:"agents"`
}

// Read the same durable policy used by the daemon, so CLI discovery and the
// desktop use identical definitions without changing local credentials.
func discoveryCatalog(home string) *DiscoveryCatalog {
	path := filepath.Join(home, ".agent-manager", "client.db")
	if _, err := os.Stat(path); err != nil {
		return nil
	}
	db, err := sql.Open("sqlite", (&url.URL{Scheme: "file", Path: filepath.ToSlash(path), RawQuery: "mode=ro"}).String())
	if err != nil {
		return nil
	}
	defer db.Close()
	var body string
	if err := db.QueryRow(`SELECT value FROM client_state WHERE key='policy'`).Scan(&body); err != nil {
		return nil
	}
	var policy Policy
	if json.Unmarshal([]byte(body), &policy) != nil {
		return nil
	}
	return policy.AgentDiscovery
}

func adaptersForHome(home string) []adapter {
	builtins := adapters()
	catalog := discoveryCatalog(home)
	if catalog == nil {
		return builtins
	}
	byType := map[string]adapter{}
	for _, item := range builtins {
		byType[item.agentType] = item
	}
	result := []adapter{}
	for _, definition := range catalog.Agents {
		supportedOS := false
		for _, system := range definition.Systems {
			if system == runtime.GOOS {
				supportedOS = true
			}
		}
		if !definition.Enabled || !supportedOS || len(definition.SkillRoots) == 0 {
			continue
		}
		spec := byType[definition.AgentType]
		spec.agentType = definition.AgentType
		if definition.AgentType != "global-skills" {
			spec.displayName = definition.Name
		}
		spec.skillRoots = definition.SkillRoots
		spec.supportsSkill = true
		result = append(result, spec)
	}
	return result
}
