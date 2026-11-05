package managedclient

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
)

// ResolveAuditSkillPath preserves ordinary paths. A symlink is readable only
// when the exact local installation points to its own managed release.
func ResolveAuditSkillPath(home, path string) (string, error) {
	path = filepath.Clean(path)
	if !filepath.IsAbs(path) || filepath.Base(path) != "SKILL.md" {
		return "", fmt.Errorf("aidr_skill_source_unknown")
	}
	resolved, err := filepath.EvalSymlinks(path)
	if os.IsNotExist(err) {
		return path, nil
	}
	if err != nil {
		return "", err
	}
	if resolved == path {
		return path, nil
	}
	// A link on SKILL.md itself is not an installation-directory alias.
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("aidr_skill_source_unknown")
	}
	dsn := sqliteURI(filepath.Join(RuntimeRoot(home), "client.db"), "mode=ro")
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return "", err
	}
	defer db.Close()
	var id, body string
	err = db.QueryRow(`SELECT skill_id,manifest_json FROM client_installs WHERE target_path=? LIMIT 1`, filepath.Dir(path)).Scan(&id, &body)
	if err != nil {
		return "", fmt.Errorf("aidr_skill_source_unknown")
	}
	var manifest releaseManifest
	if json.Unmarshal([]byte(body), &manifest) != nil || id == "" || id == "." || id == ".." || filepath.Base(id) != id {
		return "", fmt.Errorf("aidr_skill_source_unknown")
	}
	for _, base := range managedSkillsRoots(home) {
		targets := []string{filepath.Join(base, id, "release", "SKILL.md")}
		if manifest.VersionID != "" && manifest.VersionID != "." && manifest.VersionID != ".." && filepath.Base(manifest.VersionID) == manifest.VersionID {
			targets = append(targets, filepath.Join(base, id, "versions", manifest.VersionID, "release", "SKILL.md"))
		}
		for _, target := range targets {
			// Canonicalize only the known data root, not the expected release:
			// an attacker must not redirect both aliases to an arbitrary target.
			canonicalBase, e := filepath.EvalSymlinks(base)
			if e != nil {
				continue
			}
			rel, _ := filepath.Rel(base, target)
			if resolved == filepath.Join(canonicalBase, rel) {
				return resolved, nil
			}
		}
	}
	return "", fmt.Errorf("aidr_skill_source_unknown")
}

func executeSkillObservation(ctx context.Context, home string, inventory Inventory, api API, task Task) error {
	var payload struct {
		Skill         agentlog.SkillUse         `json:"skill"`
		LocalAgentID  string                    `json:"local_agent_id"`
		AgentType     string                    `json:"agent_type"`
		Policy        agentlog.SkillAuditPolicy `json:"audit_policy"`
		PolicyVersion string                    `json:"audit_policy_version"`
	}
	if err := api.getJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/tasks/%d/skill-observation", inventory.ClientID, task.ID), &payload); err != nil {
		return fmt.Errorf("aidr_skill_observation_policy_unavailable")
	}
	if !payload.Policy.Enabled || !payload.Policy.Valid() {
		return fmt.Errorf("aidr_skill_audit_disabled")
	}
	path := filepath.FromSlash(payload.Skill.Path)
	allowed := false
	for _, agent := range inventory.Agents {
		if agent.LocalAgentID != payload.LocalAgentID || agent.AgentType != payload.AgentType {
			continue
		}
		for _, root := range agentSkillRoots(agent) {
			rel, err := filepath.Rel(root, filepath.Dir(path))
			if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel) {
				allowed = true
			}
		}
	}
	if !allowed {
		return fmt.Errorf("aidr_skill_source_unknown")
	}
	resolved, err := ResolveAuditSkillPath(home, path)
	if err != nil {
		return fmt.Errorf("aidr_skill_source_unknown")
	}
	observer := agentlog.NewSkillObserver()
	observer.ResolvePath = func(path string) (string, error) { return ResolveAuditSkillPath(home, path) }
	payload.Policy.CheckMode = "every_use"
	observationCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	observer.Observe(observationCtx, &payload.Skill, &agentlog.AuditPolicy{SkillAudit: &payload.Policy})
	task.Payload["skill_observation"] = map[string]any{"skill": payload.Skill, "resolved_path": filepath.ToSlash(resolved), "policy_version": payload.PolicyVersion, "observed_at": time.Now().UTC().Format(time.RFC3339Nano)}
	return nil
}
