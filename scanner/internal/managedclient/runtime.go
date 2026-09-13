package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

func RunOnce(ctx context.Context, home string, api API, store *Store) error {
	return runOnce(ctx, home, api, store, false)
}

func RunFullScan(ctx context.Context, home string, api API, store *Store) error {
	return runOnce(ctx, home, api, store, true)
}

func runOnce(ctx context.Context, home string, api API, store *Store, forceFullScan bool) error {
	api = api.WithDiagnostics(store)
	if err := store.ResetPatrolFindings(); err != nil {
		return err
	}
	discoveryBefore, _ := json.Marshal(discoveryCatalog(home))
	inventory, err := Discover(home)
	if err != nil {
		return err
	}
	if err := store.EnrichInventory(&inventory); err != nil {
		return err
	}
	if err := store.SaveInventory(inventory); err != nil {
		return err
	}
	policy, heartbeatErr := api.Heartbeat(ctx, inventory)
	online := heartbeatErr == nil
	if online {
		if policy.Mode == "" {
			policy, err = api.Policy(ctx, inventory.ClientID)
			online = err == nil
		}
		if online {
			body, _ := json.Marshal(policy)
			if err := store.SetState("policy", string(body)); err != nil {
				return err
			}
			if err := flushEvents(ctx, api, store); err != nil {
				online = false
			}
		}
	}
	discoveryAfter, _ := json.Marshal(discoveryCatalog(home))
	if string(discoveryBefore) != string(discoveryAfter) {
		inventory, err = Discover(home)
		if err != nil {
			return err
		}
		if err := store.EnrichInventory(&inventory); err != nil {
			return err
		}
		if err := store.SaveInventory(inventory); err != nil {
			return err
		}
	}
	if !online {
		body, ok, stateErr := store.State("policy")
		if stateErr != nil {
			return stateErr
		}
		if !ok || json.Unmarshal([]byte(body), &policy) != nil {
			policy = Policy{Mode: "audit", Classification: DefaultClassificationPolicy()}
		}
	}
	tasks := []Task{}
	if online {
		if err := flushTaskResults(ctx, inventory.ClientID, api, store); err != nil {
			return err
		}
		tasks, err = api.Tasks(ctx, inventory.ClientID)
		if err != nil {
			online = false
		}
	}
	if err := executeTasks(ctx, home, inventory, policy, api, store, tasks); err != nil {
		return err
	}
	if online {
		_, _ = ReconcileApprovedPending(ctx, home, api, store, inventory, policy)
		_, restoreErr := ReconcileCertifiedQuarantine(ctx, home, api, store, inventory)
		syncError(store, "auto_restore", restoreErr)
	}
	fullInterval := time.Duration(policy.FullScanSeconds) * time.Second
	if fullInterval <= 0 {
		fullInterval = 30 * time.Minute
	}
	fullScan := forceFullScan
	if !fullScan {
		fullScan, err = store.Due("patrol:full", fullInterval)
		if err != nil {
			return err
		}
	}
	if err := patrol(ctx, home, inventory, policy, api, store, fullScan, online); err != nil {
		return err
	}
	if online {
		fresh, discoverErr := Discover(home)
		if discoverErr == nil {
			_ = store.EnrichInventory(&fresh)
			_ = store.SaveInventory(fresh)
			_ = api.ReportInventory(ctx, fresh)
		}
	}
	if fullScan {
		return store.MarkSchedule("patrol:full")
	}
	return nil
}

func PollTasks(ctx context.Context, home string, api API, store *Store) error {
	due, err := store.Due("tasks:poll", 10*time.Second)
	if err != nil || !due {
		return err
	}
	if err := store.MarkSchedule("tasks:poll"); err != nil {
		return err
	}
	body, ok, err := store.State("inventory")
	if err != nil || !ok {
		return err
	}
	var cached Inventory
	if err := json.Unmarshal([]byte(body), &cached); err != nil || cached.ClientID == "" {
		return err
	}
	policyBody, policyOK, err := store.State("policy")
	if err != nil {
		return err
	}
	policy, policyErr := api.Heartbeat(ctx, cached)
	if policyErr == nil && policy.Mode == "" {
		policy, policyErr = api.Policy(ctx, cached.ClientID)
	}
	if policyErr == nil {
		freshBody, _ := json.Marshal(policy)
		if err := store.SetState("policy", string(freshBody)); err != nil {
			return err
		}
		if !policyOK || policyBody != string(freshBody) {
			if err := RequestFullScan(home); err != nil {
				return err
			}
		}
	} else if !policyOK || json.Unmarshal([]byte(policyBody), &policy) != nil {
		return policyErr
	}
	tasks, err := api.Tasks(ctx, cached.ClientID)
	if err != nil {
		return err
	}
	inventory := cached
	if len(tasks) > 0 {
		inventory, err = Discover(home)
		if err != nil {
			return err
		}
		if err := store.EnrichInventory(&inventory); err != nil {
			return err
		}
	}
	if err := executeTasks(ctx, home, inventory, policy, api, store, tasks); err != nil {
		return err
	}
	pendingChanged, pendingErr := ReconcileApprovedPending(ctx, home, api, store, inventory, policy)
	if pendingErr != nil {
		return pendingErr
	}
	restored, restoreErr := ReconcileCertifiedQuarantine(ctx, home, api, store, inventory)
	syncError(store, "auto_restore", restoreErr)
	if len(tasks) == 0 && !pendingChanged && !restored {
		return nil
	}
	fresh, err := Discover(home)
	if err != nil {
		return err
	}
	_ = store.EnrichInventory(&fresh)
	_ = store.SaveInventory(fresh)
	return api.ReportInventory(ctx, fresh)
}

func executeTasks(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, tasks []Task) error {
	for _, task := range tasks {
		ctx = context.WithValue(ctx, diagnosticContextKey{}, map[string]any{"task_id": task.ID, "task_type": task.TaskType})
		completed, err := store.TaskCompleted(task.ID)
		if err != nil {
			return err
		}
		if completed {
			_ = api.ReportExecutedTask(ctx, inventory.ClientID, task, "succeeded", "")
			continue
		}
		accepted, remoteStatus, err := api.StartTask(ctx, inventory.ClientID, task.ID)
		if err != nil {
			return err
		}
		if !accepted {
			if err := store.SaveTask(task, remoteStatus, ""); err != nil {
				return err
			}
			continue
		}
		if err := store.SaveTask(task, "running", ""); err != nil {
			return err
		}
		taskErr := executeTask(ctx, home, inventory, policy, api, store, task)
		if taskErr == nil && task.TaskType == "sync_policy" {
			policy = cachedPolicy(store)
		}
		status := "succeeded"
		message := ""
		if taskErr != nil {
			status = "failed"
			message = taskErr.Error()
		}
		if err := store.SaveTask(task, status, message); err != nil {
			return err
		}
		if err := api.ReportExecutedTask(ctx, inventory.ClientID, task, status, message); err != nil {
			return err
		}
		if err := store.SetState(fmt.Sprintf("task:reported:%d", task.ID), status); err != nil {
			return err
		}
	}
	return nil
}

// ConfigureAgentModel requests an authorized model switch and executes the
// returned task immediately. The task-bound runtime credential is fetched by
// the sidecar and never exposed to the desktop renderer.
func ConfigureAgentModel(ctx context.Context, home string, inventory Inventory, api API, store *Store, localAgentID, agentType, managedAgentID, model string) error {
	task, err := api.RequestModelConfiguration(ctx, inventory.ClientID, localAgentID, agentType, managedAgentID, model)
	if err != nil {
		return err
	}
	if task.ID == 0 || task.TaskType != "apply_model_config" {
		return fmt.Errorf("Agent Manager returned an invalid model configuration task")
	}
	if err := store.SaveTask(task, "running", ""); err != nil {
		return err
	}
	taskErr := executeTask(ctx, home, inventory, Policy{}, api, store, task)
	status := "succeeded"
	message := ""
	if taskErr != nil {
		status = "failed"
		message = taskErr.Error()
	}
	if err := store.SaveTask(task, status, message); err != nil {
		return err
	}
	if err := api.ReportExecutedTask(ctx, inventory.ClientID, task, status, message); err != nil {
		return err
	}
	return taskErr
}

func executeTask(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, task Task) error {
	switch task.TaskType {
	case "skill_action":
		return executeObservedTask(ctx, home, policy, api, store, task)
	case "sync_policy":
		fresh, err := api.Policy(ctx, inventory.ClientID)
		if err != nil {
			return err
		}
		target := stringValue(task.Payload, "target_version")
		if target != "" && (fresh.Classification == nil || fresh.Classification.Version != target) {
			return fmt.Errorf("policy_superseded")
		}
		body, err := json.Marshal(fresh)
		if err != nil {
			return err
		}
		if err := store.SetState("policy", string(body)); err != nil {
			return err
		}
		return RequestFullScan(home)
	case "rescan":
		fresh, err := Discover(home)
		if err != nil {
			return err
		}
		if err := store.EnrichInventory(&fresh); err != nil {
			return err
		}
		if err := api.ReportInventory(ctx, fresh); err != nil {
			return err
		}
		return RequestFullScan(home)
	case "apply_model_config":
		agentType := stringValue(task.Payload, "agent_type")
		localAgentID := stringValue(task.Payload, "local_agent_id")
		model := stringValue(task.Payload, "model")
		if agentType == "" || localAgentID == "" || model == "" {
			return fmt.Errorf("model config task is missing target Agent or model")
		}
		credential := ""
		if boolValue(task.Payload, "auto_issue_credential") {
			issued, err := api.IssueAgentCredential(ctx, inventory.ClientID, task.ID)
			if err != nil {
				return fmt.Errorf("issue Agent runtime credential: %w", err)
			}
			credential = issued.Token
			if credential == "" {
				return fmt.Errorf("Agent Manager returned an empty Agent runtime credential")
			}
		}
		return ApplyModelConfig(home, api.server, localAgentID, agentType, model, credential)
	case "install_skill", "repair_skill":
		agentType := stringValue(task.Payload, "agent_type")
		managedAgentID := stringValue(task.Payload, "managed_agent_id")
		skillID := stringValue(task.Payload, "skill_id")
		versionID := stringValue(task.Payload, "version_id")
		if agentType == "" || skillID == "" || (policy.GovernanceMode == "strict" && managedAgentID == "") {
			return fmt.Errorf("install task is missing required agent or skill information")
		}
		return installApprovedSkillVersion(ctx, home, inventory, policy, api, store, agentType, managedAgentID, skillID, versionID, task.TaskType == "repair_skill", task.Payload)
	case "remove_skill":
		return executeRemovalTask(ctx, home, policy, api, store, task)
	default:
		return fmt.Errorf("unsupported task type %s", task.TaskType)
	}
}

func InstallApprovedSkill(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, agentType, managedAgentID, skillID string) error {
	return InstallApprovedSkillVersion(ctx, home, inventory, policy, api, store, agentType, managedAgentID, skillID, "")
}

func InstallApprovedSkillVersion(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, agentType, managedAgentID, skillID, versionID string) error {
	return installApprovedSkillVersion(ctx, home, inventory, policy, api, store, agentType, managedAgentID, skillID, versionID, false)
}

func installApprovedSkillVersion(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, agentType, managedAgentID, skillID, versionID string, repair bool, taskPayload ...map[string]any) error {
	if !validInstallComponent(skillID) || (versionID != "" && !validInstallComponent(versionID)) {
		return fmt.Errorf("invalid install identifier")
	}
	ctx, releaseMutation, err := withMutationLock(ctx, home)
	if err != nil {
		return err
	}
	defer releaseMutation()
	if agentType == "" || skillID == "" || (policy.GovernanceMode == "strict" && managedAgentID == "") {
		return fmt.Errorf("install requires agent and skill information")
	}
	if classificationEnabled(policy) {
		action := policy.Classification.Rules["malicious"]
		if action == "quarantine" || action == "uninstall" {
			preview, err := api.SkillPreview(ctx, inventory.ClientID, skillID, versionID, agentType, managedAgentID)
			if err != nil {
				return err
			}
			if preview.RiskLevel == "malicious" {
				return fmt.Errorf("skill_install_malicious")
			}
		}
	}
	agent, ok := findAgent(inventory, agentType)
	if !ok || !agent.SkillManagementSupported || agent.SkillsPath == "" {
		return fmt.Errorf("agent %s does not support managed skills", agentType)
	}
	targetsBeforeDownload, err := captureInstallTargets(agent.SkillsPath)
	if err != nil {
		return err
	}
	currentAlias := filepath.Join(ManagedSkillsRoot(home), skillID, "release")
	aliasBeforeDownload := map[string]installTargetState{}
	if state, err := inspectInstallTarget(currentAlias); err == nil {
		aliasBeforeDownload[currentAlias] = state
	} else if !os.IsNotExist(err) {
		return err
	}
	body, err := api.DownloadPackageVersion(ctx, inventory.ClientID, skillID, versionID, agentType, managedAgentID)
	if err != nil {
		return err
	}
	incoming := filepath.Join(ManagedSkillsRoot(home), skillID, fmt.Sprintf(".incoming-%d", time.Now().UnixNano()))
	manifest, err := VerifyAndExtractPackage(body, policy.ReleasePublicKey, incoming)
	if err != nil {
		return err
	}
	defer os.RemoveAll(incoming)
	resolvedVersionID := manifest.VersionID
	if resolvedVersionID == "" {
		resolvedVersionID = skillID
	}
	target := filepath.Join(ManagedSkillsRoot(home), skillID, "versions", resolvedVersionID, "release")
	link := filepath.Join(agent.SkillsPath, filepath.Base(manifest.Name))
	if err := checkPatrolSnapshot(ctx, link); err != nil {
		return err
	}
	if len(taskPayload) > 0 {
		if err := checkQueuedInstallTarget(link, agent.SkillsPath, taskPayload[0]); err != nil {
			return err
		}
	}
	if err := os.MkdirAll(agent.SkillsPath, 0o755); err != nil {
		return err
	}
	if info, err := os.Lstat(link); err == nil {
		sameInstall := false
		if len(taskPayload) > 0 && stringValue(taskPayload[0], "expected_path") == link {
			sameInstall = targetsBeforeDownload[link].signature == manifest.ContentSignature
		}
		if info.Mode()&os.ModeSymlink != 0 {
			resolved, resolveErr := filepath.EvalSymlinks(link)
			resolvedTarget, targetErr := filepath.EvalSymlinks(target)
			sameInstall = resolveErr == nil && targetErr == nil && filepath.Clean(resolved) == filepath.Clean(resolvedTarget)
			if resolveErr != nil && brokenManagedSymlink(home, link) {
				sameInstall = true
			}
		}
		if !sameInstall {
			installs, listErr := store.Installations()
			if listErr != nil {
				return listErr
			}
			for _, install := range installs {
				if install.AgentType == agentType && install.SkillID == skillID && filepath.Clean(install.TargetPath) == filepath.Clean(link) {
					sameInstall = true
					break
				}
			}
		}
		if !sameInstall {
			return fmt.Errorf("agent %s already has a different skill named %s", agentType, manifest.Name)
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := checkInstallTarget(link, targetsBeforeDownload); err != nil {
		return err
	}
	// Keep edited shared releases in place; install a verified independent copy.
	preserveAlias := false
	if !repair {
		if _, err := os.Stat(target); err == nil {
			if err := checkObservedContent(Skill{Path: target, Signature: manifest.ContentSignature}); err != nil {
				copyRoot, err := os.MkdirTemp(filepath.Dir(target), "copy-")
				if err != nil {
					return err
				}
				defer os.Remove(copyRoot) // Remove the reservation only if it remains empty.
				target = filepath.Join(copyRoot, "release")
				_, preserveAlias = aliasBeforeDownload[currentAlias]
			}
		} else if !os.IsNotExist(err) {
			return err
		}
	}
	backupPaths := []string{}
	backedUpSource := ""
	policyVersion := ""
	if policy.Classification != nil {
		policyVersion = policy.Classification.Version
	}
	if err := checkInstallTarget(currentAlias, aliasBeforeDownload); err != nil {
		return err
	}
	if before, exists := aliasBeforeDownload[currentAlias]; exists && before.mode.IsDir() {
		backup, err := retainInstallBackup(home, currentAlias, link, agentType, manifest.Name, policyVersion)
		if err != nil {
			return err
		}
		backupPaths = append(backupPaths, backup)
	}
	if before, exists := targetsBeforeDownload[link]; exists && before.signature != "" && before.signature != manifest.ContentSignature {
		backup, err := retainInstallBackup(home, link, link, agentType, manifest.Name, policyVersion)
		if err != nil {
			return err
		}
		backupPaths = append(backupPaths, backup)
		backedUpSource, _ = filepath.EvalSymlinks(link)
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		_ = os.RemoveAll(incoming)
		return err
	}
	if _, err := os.Stat(target); os.IsNotExist(err) {
		if err := os.Rename(incoming, target); err != nil {
			_ = os.RemoveAll(incoming)
			return err
		}
	} else if err != nil {
		_ = os.RemoveAll(incoming)
		return err
	} else if checkObservedContent(Skill{Path: target, Signature: manifest.ContentSignature}) == nil {
		_ = os.RemoveAll(incoming)
	} else {
		if !repair {
			return fmt.Errorf("skill_content_changed")
		}
		resolvedTarget, err := filepath.EvalSymlinks(target)
		if err != nil {
			return err
		}
		if resolvedTarget != backedUpSource {
			backup, err := retainInstallBackup(home, target, link, agentType, manifest.Name, policyVersion)
			if err != nil {
				return err
			}
			backupPaths = append(backupPaths, backup)
		}
		previous := target + fmt.Sprintf(".previous-%d", time.Now().UnixNano())
		if err := os.Rename(target, previous); err != nil {
			_ = os.RemoveAll(incoming)
			return err
		}
		if err := os.Rename(incoming, target); err != nil {
			_ = os.Rename(previous, target)
			_ = os.RemoveAll(incoming)
			return err
		}
		_ = os.RemoveAll(previous)
	}
	if !preserveAlias {
		if err := removeInstallAlias(currentAlias, aliasBeforeDownload); err != nil {
			return err
		}
		if err := os.Symlink(target, currentAlias); err != nil {
			return err
		}
	}
	if err := os.RemoveAll(link); err != nil {
		return err
	}
	if err := os.Symlink(target, link); err != nil {
		if err := copyDir(target, link); err != nil {
			return err
		}
	}
	if err := store.SaveInstall(Installation{
		AgentType:      agentType,
		ManagedAgentID: managedAgentID,
		SkillID:        skillID,
		SkillName:      manifest.Name,
		TargetPath:     link,
		Manifest:       manifest,
	}); err != nil {
		return err
	}
	if _, configured, err := store.State("governance_enabled"); err != nil {
		return err
	} else if !configured {
		if err := store.SetGovernanceEnabled(true); err != nil {
			return err
		}
	}
	if err := store.ResolveQuarantine(agentType, manifest.Name); err != nil {
		return err
	}
	if err := store.ResolvePendingForInstall(agentType, manifest.Name, link); err != nil {
		return err
	}
	if classificationEnabled(policy) {
		installed := Skill{Name: manifest.Name, Path: link, Signature: manifest.ContentSignature}
		if err := checkObservedContent(installed); err != nil {
			return err
		}
		agent.Skills = []Skill{installed}
		checkInventory := inventory
		checkInventory.Agents = []Agent{agent}
		comparisons, compareErr := api.Compare(ctx, checkInventory, map[string]string{agentType: managedAgentID})
		confirmed := false
		if compareErr == nil {
			for _, comparison := range comparisons {
				if comparison.AgentType != agentType || comparison.LocalPath != link || comparison.LocalSignature != installed.Signature {
					continue
				}
				if err := checkObservedContent(installed); err != nil {
					return err
				}
				previous, err := store.Observation(link)
				if err != nil {
					return err
				}
				value := classifyObservation(SkillObservation{
					TrustedSignature: previous.TrustedSignature,
					TrustedSkillID:   previous.TrustedSkillID,
					TrustedVersionID: previous.TrustedVersionID,
				}, installed, &comparison)
				value.PolicyVersion = policy.Classification.Version
				if err := store.SaveObservation(link, value); err != nil {
					return err
				}
				confirmed = value.Certification == "certified"
				break
			}
		}
		if !confirmed {
			if err := RequestFullScan(home); err != nil {
				return err
			}
		}
	}
	_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_installed", agentType, manifest.Name, map[string]any{
		"skill_id": skillID, "version_id": manifest.VersionID, "version_no": manifest.VersionNo,
		"backup_paths": backupPaths, "policy_version": policyVersion,
	})
	return nil
}

func brokenManagedSymlink(home, link string) bool {
	target, err := os.Readlink(link)
	if err != nil {
		return false
	}
	if !filepath.IsAbs(target) {
		target = filepath.Join(filepath.Dir(link), target)
	}
	for _, managedRoot := range managedSkillsRoots(home) {
		if pathWithinLexical(target, managedRoot) {
			return true
		}
	}
	return false
}

func patrol(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, fullScan, online bool) (patrolErr error) {
	started := time.Now()
	defer func() {
		fields := map[string]any{"client_id": inventory.ClientID, "full_scan": fullScan, "online": online, "duration_ms": time.Since(started).Milliseconds(), "status": "succeeded"}
		level := "info"
		if patrolErr != nil {
			level = "error"
			fields["status"] = "failed"
			fields["error"] = patrolErr.Error()
		}
		store.LogDiagnostic(level, "patrol", "finished", fields)
	}()
	if classificationEnabled(policy) {
		return patrolClassified(ctx, home, inventory, policy, api, store, online)
	}
	governanceEnabled, err := store.GovernanceEnabled()
	if err != nil || !governanceEnabled {
		return err
	}
	ctx, releaseMutation, err := withMutationLock(ctx, home)
	if err != nil {
		return err
	}
	defer releaseMutation()
	installs, err := store.Installations()
	if err != nil {
		return err
	}
	installs, err = reconcileDuplicateInstallPaths(home, store, installs)
	if err != nil {
		return err
	}
	ctx, err = withPatrolSnapshot(ctx, installs)
	if err != nil {
		return err
	}
	for _, install := range installs {
		if installPathPresent(install) && verifyManagedInstall(home, install) {
			if err := store.ResolvePendingForInstall(install.AgentType, install.SkillName, install.TargetPath); err != nil {
				return err
			}
		}
	}
	knownPaths := map[string]bool{}
	mappings := map[string]string{}
	for agentType, managedAgentID := range policy.AgentBindings {
		mappings[agentType] = managedAgentID
	}
	for _, install := range installs {
		knownPaths[filepath.Clean(install.TargetPath)] = true
		if mappings[install.AgentType] == "" {
			mappings[install.AgentType] = install.ManagedAgentID
		}
	}
	unknownPaths := map[string]Skill{}
	unknownAgents := map[string]string{}
	for _, agent := range inventory.Agents {
		if !agent.SkillManagementSupported {
			continue
		}
		for _, skill := range agent.Skills {
			if skill.Status == "external_link" {
				continue
			}
			if knownPaths[filepath.Clean(skill.Path)] {
				continue
			}
			excluded, err := store.IsExcluded(skill.Path)
			if err != nil {
				return err
			}
			if excluded {
				continue
			}
			unknownKey := agent.AgentType + "\x00" + filepath.Clean(skill.Path)
			unknownPaths[unknownKey] = skill
			unknownAgents[unknownKey] = agent.AgentType
			key := "unmanaged:" + agent.AgentType + ":" + filepath.Clean(skill.Path)
			first, err := store.MarkSeen(key)
			if err != nil {
				return err
			}
			if first {
				_ = reportEvent(ctx, api, store, inventory.ClientID, "unmanaged_skill_found", agent.AgentType, skill.Name, map[string]any{
					"path": skill.Path, "mode": policy.Mode,
				})
			}
			if !online && policy.Mode == "block" {
				item, quarantineErr := quarantineCurrentSkill(ctx, home, store, agent.AgentType, skill.Name, skill.Path, "unmanaged_skill", skill.Signature)
				if quarantineErr != nil {
					return quarantineErr
				}
				_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_quarantined", agent.AgentType, skill.Name, map[string]any{
					"reason": "unmanaged_skill", "quarantine_id": item.ID,
				})
			}
		}
	}
	if !online {
		return patrolLocalChanges(ctx, home, inventory, policy, api, store, installs, fullScan)
	}
	comparisons, err := api.Compare(ctx, inventory, mappings)
	if err != nil {
		return err
	}
	platform := map[string]CompareItem{}
	for _, item := range comparisons {
		platform[comparisonKey(item.AgentType, item.Name, item.LocalPath, item.LocalSignature)] = item
	}
	if policy.Mode == "block" {
		for _, item := range comparisons {
			unknownKey := item.AgentType + "\x00" + filepath.Clean(item.LocalPath)
			skill, unknown := unknownPaths[unknownKey]
			if !unknown {
				continue
			}
			if item.Allowed {
				_ = reportEvent(ctx, api, store, inventory.ClientID, "unmanaged_skill_verified", item.AgentType, skill.Name, map[string]any{"path": skill.Path, "skill_id": item.SkillID})
				continue
			}
			quarantined, quarantineErr := quarantineCurrentSkill(ctx, home, store, unknownAgents[unknownKey], skill.Name, skill.Path, item.Reason, skill.Signature)
			if quarantineErr != nil {
				return quarantineErr
			}
			_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_quarantined", item.AgentType, skill.Name, map[string]any{"reason": item.Reason, "quarantine_id": quarantined.ID})
		}
	}
	handledSharedInstalls := map[string]bool{}
	for _, install := range installs {
		if handledSharedInstalls[filepath.Clean(install.TargetPath)] {
			continue
		}
		item, ok := platform[comparisonKey(
			install.AgentType,
			install.SkillName,
			install.TargetPath,
			install.Manifest.ContentSignature,
		)]
		if !ok {
			item, ok = platform[comparisonKey(install.AgentType, install.SkillName, "", "")]
		}
		if ok &&
			!item.Allowed && item.Reason != "signature_mismatch" {
			quarantined, err := quarantineCurrentSkill(ctx, home, store, install.AgentType, install.SkillName, install.TargetPath, item.Reason, "")
			if err != nil {
				return err
			}
			if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
				return err
			}
			_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_quarantined", install.AgentType, install.SkillName, map[string]any{
				"reason": item.Reason, "quarantine_id": quarantined.ID,
			})
			continue
		}
		pathPresent := installPathPresent(install)
		if !fullScan && pathPresent {
			continue
		}
		if pathPresent && verifyManagedInstall(home, install) {
			if err := store.ResolveQuarantine(install.AgentType, install.SkillName); err != nil {
				return err
			}
			continue
		}
		if releasePath, group := sharedInstallGroup(home, install, installs); len(group) > 1 {
			for _, affected := range group {
				handledSharedInstalls[filepath.Clean(affected.TargetPath)] = true
			}
			if err := handleSharedInstallMismatch(ctx, home, inventory, policy, api, store, releasePath, group, true); err != nil {
				return err
			}
			continue
		}
		_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_modified", install.AgentType, install.SkillName, map[string]any{
			"mode": policy.Mode,
			"path": install.TargetPath,
		})
		if !pathPresent {
			if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
				return err
			}
			continue
		}
		switch policy.Mode {
		case "repair":
			task := Task{TaskType: "repair_skill", Payload: map[string]any{
				"agent_type":       install.AgentType,
				"managed_agent_id": install.ManagedAgentID,
				"skill_id":         install.SkillID,
				"version_id":       install.Manifest.VersionID,
			}}
			if err := executeTask(ctx, home, inventory, policy, api, store, task); err != nil {
				return err
			}
			_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_repaired", install.AgentType, install.SkillName, nil)
		case "block":
			quarantined, err := quarantineCurrentSkill(ctx, home, store, install.AgentType, install.SkillName, install.TargetPath, "signature_mismatch", "")
			if err != nil {
				return err
			}
			if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
				return err
			}
			_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_quarantined", install.AgentType, install.SkillName, map[string]any{"reason": "signature_mismatch", "quarantine_id": quarantined.ID})
		}
	}
	return nil
}

func patrolLocalChanges(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, installs []Installation, fullScan bool) error {
	ctx, releaseMutation, err := withMutationLock(ctx, home)
	if err != nil {
		return err
	}
	defer releaseMutation()
	ctx, err = withPatrolSnapshot(ctx, installs)
	if err != nil {
		return err
	}
	handledSharedInstalls := map[string]bool{}
	for _, install := range installs {
		if handledSharedInstalls[filepath.Clean(install.TargetPath)] {
			continue
		}
		pathPresent := installPathPresent(install)
		if !fullScan && pathPresent || pathPresent && verifyManagedInstall(home, install) {
			continue
		}
		if releasePath, group := sharedInstallGroup(home, install, installs); len(group) > 1 {
			for _, affected := range group {
				handledSharedInstalls[filepath.Clean(affected.TargetPath)] = true
			}
			if err := handleSharedInstallMismatch(ctx, home, inventory, policy, api, store, releasePath, group, false); err != nil {
				return err
			}
			continue
		}
		_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_modified", install.AgentType, install.SkillName, map[string]any{"mode": policy.Mode, "offline": true})
		if !pathPresent {
			if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
				return err
			}
			continue
		}
		if policy.Mode == "block" {
			item, err := quarantineCurrentSkill(ctx, home, store, install.AgentType, install.SkillName, install.TargetPath, "signature_mismatch", "")
			if err != nil {
				return err
			}
			if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
				return err
			}
			_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_quarantined", install.AgentType, install.SkillName, map[string]any{"reason": "signature_mismatch", "offline": true, "quarantine_id": item.ID})
		}
	}
	return nil
}

func sharedInstallGroup(home string, current Installation, installs []Installation) (string, []Installation) {
	releasePath, ok := managedSymlinkTarget(home, current)
	if !ok {
		return "", nil
	}
	group := []Installation{}
	for _, install := range installs {
		target, shared := managedSymlinkTarget(home, install)
		if shared && filepath.Clean(target) == filepath.Clean(releasePath) {
			group = append(group, install)
		}
	}
	return releasePath, group
}

func managedSymlinkTarget(home string, install Installation) (string, bool) {
	info, err := os.Lstat(install.TargetPath)
	if err != nil || info.Mode()&os.ModeSymlink == 0 {
		return "", false
	}
	target, err := os.Readlink(install.TargetPath)
	if err != nil {
		return "", false
	}
	if !filepath.IsAbs(target) {
		target = filepath.Join(filepath.Dir(install.TargetPath), target)
	}
	for _, root := range managedSkillsRoots(home) {
		candidates := []string{filepath.Join(root, install.SkillID, "release")}
		if install.Manifest.VersionID != "" {
			candidates = append(candidates, filepath.Join(root, install.SkillID, "versions", install.Manifest.VersionID, "release"))
		}
		if install.Manifest.ContentSignature != "" {
			candidates = append(candidates, filepath.Join(root, install.SkillID, install.Manifest.ContentSignature))
		}
		for _, expected := range candidates {
			if filepath.Clean(target) == filepath.Clean(expected) {
				return expected, true
			}
		}
	}
	return "", false
}

func verifyManagedInstall(home string, install Installation) bool {
	if info, err := os.Lstat(install.TargetPath); err == nil && info.Mode()&os.ModeSymlink != 0 {
		if _, expected := managedSymlinkTarget(home, install); !expected {
			return false
		}
	}
	return verifyInstalled(install)
}

func reconcileDuplicateInstallPaths(home string, store *Store, installs []Installation) ([]Installation, error) {
	groups := map[string][]Installation{}
	order := []string{}
	for _, install := range installs {
		key := install.AgentType + "\x00" + filepath.Clean(install.TargetPath)
		if _, exists := groups[key]; !exists {
			order = append(order, key)
		}
		groups[key] = append(groups[key], install)
	}
	result := make([]Installation, 0, len(installs))
	for _, key := range order {
		group := groups[key]
		if len(group) == 1 {
			result = append(result, group[0])
			continue
		}
		validIndex := -1
		for index, install := range group {
			if !installPathPresent(install) || !verifyManagedInstall(home, install) {
				continue
			}
			if validIndex < 0 || (group[validIndex].Manifest.VersionID == "" && install.Manifest.VersionID != "") {
				validIndex = index
			}
		}
		if validIndex < 0 {
			// Preserve all evidence when no registration verifies. The normal
			// tamper path remains responsible for the policy decision.
			result = append(result, group...)
			continue
		}
		valid := group[validIndex]
		for index, stale := range group {
			if index == validIndex {
				continue
			}
			if err := store.RemoveInstall(stale.AgentType, stale.SkillID); err != nil {
				return nil, err
			}
		}
		result = append(result, valid)
	}
	return result, nil
}

func handleSharedInstallMismatch(
	ctx context.Context,
	home string,
	inventory Inventory,
	policy Policy,
	api API,
	store *Store,
	releasePath string,
	installs []Installation,
	online bool,
) error {
	clientID := inventory.ClientID
	primary := installs[0]
	agents := make([]string, 0, len(installs))
	paths := make([]string, 0, len(installs))
	for _, install := range installs {
		agents = append(agents, install.AgentType)
		paths = append(paths, install.TargetPath)
	}
	details := map[string]any{
		"mode": policy.Mode, "path": releasePath, "shared_skill": true,
		"affected_agents": agents, "affected_paths": paths,
	}
	if !online {
		details["offline"] = true
	}
	_ = reportEvent(ctx, api, store, clientID, "skill_modified", primary.AgentType, primary.SkillName, details)
	for _, install := range installs {
		if err := checkPatrolSnapshot(ctx, install.TargetPath); err != nil {
			return err
		}
	}

	if _, err := os.Stat(releasePath); os.IsNotExist(err) {
		return removeSharedInstalls(store, installs, releasePath)
	} else if err != nil {
		return err
	}
	if online && policy.Mode == "repair" {
		task := Task{TaskType: "repair_skill", Payload: map[string]any{
			"agent_type": primary.AgentType, "managed_agent_id": primary.ManagedAgentID,
			"skill_id": primary.SkillID, "version_id": primary.Manifest.VersionID,
		}}
		if err := executeTask(ctx, home, inventory, policy, api, store, task); err != nil {
			return err
		}
		_ = reportEvent(ctx, api, store, clientID, "skill_repaired", primary.AgentType, primary.SkillName, details)
		return nil
	}
	if policy.Mode != "block" {
		return nil
	}
	item, err := quarantineCurrentSkill(ctx, home, store, primary.AgentType, primary.SkillName, releasePath, "signature_mismatch", "")
	if err != nil {
		return err
	}
	if err := removeSharedInstalls(store, installs, releasePath); err != nil {
		return err
	}
	details["reason"] = "signature_mismatch"
	details["quarantine_id"] = item.ID
	_ = reportEvent(ctx, api, store, clientID, "skill_quarantined", primary.AgentType, primary.SkillName, details)
	return nil
}

func removeSharedInstalls(store *Store, installs []Installation, releasePath string) error {
	for _, install := range installs {
		link, err := os.Readlink(install.TargetPath)
		if os.IsNotExist(err) {
			if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
				return err
			}
			continue
		}
		if err != nil {
			return fmt.Errorf("skill_content_changed")
		}
		if !filepath.IsAbs(link) {
			link = filepath.Join(filepath.Dir(install.TargetPath), link)
		}
		// Resolve the parent because the quarantined release may already be absent.
		link = filepath.Join(canonicalExistingPath(filepath.Dir(link)), filepath.Base(link))
		expected := filepath.Join(canonicalExistingPath(filepath.Dir(releasePath)), filepath.Base(releasePath))
		if link != expected {
			return fmt.Errorf("skill_content_changed")
		}
		if err := os.Remove(install.TargetPath); err != nil {
			return err
		}
		if err := store.RemoveInstall(install.AgentType, install.SkillID); err != nil {
			return err
		}
	}
	return nil
}

func reportEvent(ctx context.Context, api API, store *Store, clientID, eventType, agentType, skillName string, details map[string]any) error {
	if details == nil {
		details = map[string]any{}
	}
	if _, ok := details["last_seen_at"]; !ok {
		details["last_seen_at"] = time.Now().UTC().Format(time.RFC3339Nano)
	}
	store.LogDiagnostic("info", "governance", eventType, map[string]any{"client_id": clientID, "agent_type": agentType, "skill_name": skillName, "details": details})
	if notification, ok := notificationForEvent(eventType, agentType, skillName, details); ok {
		_ = store.RecordNotification(notification)
	}
	if eventType == "skill_modified" || eventType == "unmanaged_skill_found" || eventType == "skill_quarantined" {
		if err := store.RecordPatrolFinding(PatrolFinding{EventType: eventType, AgentType: agentType, SkillName: skillName}); err != nil {
			return err
		}
	}
	if err := api.ReportEvent(ctx, clientID, eventType, agentType, skillName, details); err == nil {
		return nil
	}
	return store.QueueEvent(QueuedEvent{ClientID: clientID, EventType: eventType, AgentType: agentType, SkillName: skillName, Details: details})
}

func flushEvents(ctx context.Context, api API, store *Store) error {
	items, err := store.QueuedEvents()
	if err != nil {
		return err
	}
	for _, item := range items {
		if err := api.ReportEvent(ctx, item.ClientID, item.EventType, item.AgentType, item.SkillName, item.Details); err != nil {
			return err
		}
		if err := store.DeleteQueuedEvent(item.ID); err != nil {
			return err
		}
	}
	return nil
}

func installPathPresent(install Installation) bool {
	root, err := filepath.EvalSymlinks(install.TargetPath)
	if err != nil {
		root = install.TargetPath
	}
	info, err := os.Stat(root)
	return err == nil && info.IsDir()
}

func verifyInstalled(install Installation) bool {
	root, err := filepath.EvalSymlinks(install.TargetPath)
	if err != nil {
		root = install.TargetPath
	}
	expected := map[string]struct{}{}
	for _, item := range install.Manifest.Files {
		expected[filepath.Clean(filepath.FromSlash(item.Path))] = struct{}{}
		data, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(item.Path)))
		if err != nil {
			return false
		}
		sum := sha256.Sum256(data)
		if int64(len(data)) != item.Size || hex.EncodeToString(sum[:]) != item.SHA256 {
			return false
		}
	}
	valid := true
	_ = filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			valid = false
			return filepath.SkipAll
		}
		if path == root || entry.IsDir() || entry.Type()&os.ModeSymlink != 0 {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			valid = false
			return filepath.SkipAll
		}
		if _, ok := expected[filepath.Clean(rel)]; !ok {
			valid = false
			return filepath.SkipAll
		}
		return nil
	})
	return valid
}

func findAgent(inventory Inventory, agentType string) (Agent, bool) {
	for _, agent := range inventory.Agents {
		if agent.AgentType == agentType {
			return agent, true
		}
	}
	return Agent{}, false
}

func stringValue(payload map[string]any, key string) string {
	value, _ := payload[key].(string)
	return value
}

func boolValue(payload map[string]any, key string) bool {
	value, _ := payload[key].(bool)
	return value
}
