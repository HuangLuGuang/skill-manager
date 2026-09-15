package managedclient

import (
	"context"
	"os"
	"path/filepath"
	"time"

	"skill-manager/scanner/internal/manifest"
)

// fastPatrolTrustedChanges handles the common high-confidence case without a
// platform round trip: a recorded signed installation changed on disk and the
// already-synced policy requires immediate quarantine or uninstall.
func fastPatrolTrustedChanges(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, changedPaths []string) (bool, []string, error) {
	started := time.Now()
	if len(changedPaths) == 0 || !classificationEnabled(policy) {
		return false, nil, nil
	}
	action := policy.Classification.Rules["trusted_content_changed"]
	if action != "quarantine" && action != "uninstall" {
		store.LogDiagnostic("info", "watcher", "fast_action_skipped", map[string]any{"reason": "policy_action_not_supported", "action": action, "changed_paths": len(changedPaths), "policy_version": policy.Classification.Version})
		return false, nil, nil
	}
	installs, err := store.Installations()
	if err != nil {
		return false, nil, err
	}
	baselines := map[string]Installation{}
	for _, install := range installs {
		baselines[filepath.Clean(install.TargetPath)] = install
	}

	affected := map[string]string{}
	baselineCandidates := 0
	for _, agent := range inventory.Agents {
		for _, skill := range agent.Skills {
			install, managed := baselines[filepath.Clean(skill.Path)]
			if !managed || install.Manifest.ContentSignature == "" {
				// Older clients may have a trusted observation but no surviving
				// client_installs row (for example after a prior quarantine). Reuse
				// that persisted trusted signature for immediate local enforcement.
				previous, observationErr := store.Observation(skill.Path)
				if observationErr != nil || previous.TrustedSignature == "" {
					continue
				}
				install = Installation{TargetPath: skill.Path, Manifest: releaseManifest{ContentSignature: previous.TrustedSignature}}
			}
			baselineCandidates++
			physical, err := filepath.EvalSymlinks(skill.Path)
			if err != nil {
				continue
			}
			for _, changed := range changedPaths {
				if pathWithinLexical(changed, skill.Path) || pathWithinLexical(changed, physical) {
					affected[filepath.Clean(physical)] = install.Manifest.ContentSignature
					break
				}
			}
		}
	}
	if len(affected) == 0 {
		reason := "path_not_matched"
		if baselineCandidates == 0 {
			reason = "baseline_missing"
		}
		store.LogDiagnostic("info", "watcher", "fast_action_skipped", map[string]any{"reason": reason, "changed_paths": len(changedPaths), "policy_version": policy.Classification.Version})
		return false, nil, nil
	}

	currentSignatures := map[string]string{}
	for physical, trusted := range affected {
		value, err := manifest.Build(physical, DefaultManifestOptions())
		if err != nil {
			store.LogDiagnostic("warn", "watcher", "fast_action_skipped", map[string]any{"reason": "signature_build_failed", "path": physical, "error": err.Error(), "policy_version": policy.Classification.Version})
			return false, nil, nil // Let the complete discovery path classify malformed or disappearing content.
		}
		current := manifest.ContentSignature(value.Files)
		if current == trusted {
			continue
		}
		currentSignatures[physical] = current
	}
	if len(currentSignatures) == 0 {
		return false, nil, nil
	}
	affectedRoots := make([]string, 0, len(currentSignatures))
	for root := range currentSignatures {
		affectedRoots = append(affectedRoots, root)
	}

	targeted := inventory
	targeted.Agents = nil
	for _, agent := range inventory.Agents {
		filtered := agent
		filtered.Skills = nil
		for _, skill := range agent.Skills {
			physical, err := filepath.EvalSymlinks(skill.Path)
			if err != nil {
				continue
			}
			if signature := currentSignatures[filepath.Clean(physical)]; signature != "" {
				skill.Signature = signature
				filtered.Skills = append(filtered.Skills, skill)
			}
		}
		if len(filtered.Skills) > 0 {
			targeted.Agents = append(targeted.Agents, filtered)
		}
	}
	if len(targeted.Agents) == 0 {
		return false, nil, nil
	}
	// Immediate actions already queue their audit events locally, so online=false
	// only skips Compare; it does not weaken or omit the configured file action.
	if err := patrolClassified(ctx, home, targeted, policy, api, store, false); err != nil {
		return true, affectedRoots, err
	}

	for agentIndex := range inventory.Agents {
		skills := inventory.Agents[agentIndex].Skills[:0]
		for _, skill := range inventory.Agents[agentIndex].Skills {
			if _, err := os.Stat(skill.Path); err == nil {
				skills = append(skills, skill)
			}
		}
		inventory.Agents[agentIndex].Skills = skills
		clearSharingAnnotations(&inventory.Agents[agentIndex])
	}
	config, _ := LoadConfig(home)
	annotateDiscoverySharing(&inventory, config)
	if err := store.EnrichInventory(&inventory); err != nil {
		return true, affectedRoots, err
	}
	if err := store.SaveInventory(inventory); err != nil {
		return true, affectedRoots, err
	}
	if err := store.EmitUIStateEvent(home, "local_state_changed", map[string]any{"action": action, "changed_paths": len(changedPaths)}); err != nil {
		return true, affectedRoots, err
	}
	store.LogDiagnostic("info", "watcher", "fast_action_completed", map[string]any{
		"action": action, "changed_paths": len(changedPaths), "affected_skills": len(currentSignatures),
		"duration_ms": time.Since(started).Milliseconds(),
	})
	// Reconcile every derived field and platform comparison in the background.
	_ = RequestFullScan(home)
	return true, affectedRoots, nil
}

func clearSharingAnnotations(agent *Agent) {
	delete(agent.Capabilities, "shared_skill_readers_by_path")
	delete(agent.Capabilities, "shared_skill_readers_by_root")
	if agent.AgentType != "global-skills" {
		delete(agent.Capabilities, "shared_skill_readers")
		delete(agent.Capabilities, "shared_skills")
	}
}
