package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
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
	if _, err := ReconcileSharedManagedInstalls(ctx, home, store); err != nil {
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
	if _, err := ReconcileInstalledRecoveryCopies(home, store); err != nil {
		return err
	}
	policy, heartbeatErr := api.Heartbeat(ctx, inventory, home)
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
			_ = flushEvents(ctx, api, store)
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
	policy, policyErr := api.Heartbeat(ctx, cached, home)
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
	sharingChanged, err := ReconcileSharedManagedInstalls(ctx, home, store)
	if err != nil {
		return err
	}
	recoveryChanged, err := ReconcileInstalledRecoveryCopies(home, store)
	if err != nil {
		return err
	}
	pendingChanged, pendingErr := ReconcileApprovedPending(ctx, home, api, store, inventory, policy)
	if pendingErr != nil {
		return pendingErr
	}
	restored, restoreErr := ReconcileCertifiedQuarantine(ctx, home, api, store, inventory)
	syncError(store, "auto_restore", restoreErr)
	if len(tasks) == 0 && !pendingChanged && !restored && !recoveryChanged && !sharingChanged {
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
			if task.TaskType == "aidr_plugin_action" || task.TaskType == "aidr_skill_observe" {
				saved, err := store.StoredTask(task.ID)
				if err != nil {
					return err
				}
				if err := api.ReportExecutedTask(ctx, inventory.ClientID, saved.Task, saved.Status, saved.Error); err != nil {
					return err
				}
				continue
			}
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
		if taskErr == nil {
			taskErr = verifyTaskLocalCompletion(home, store, task)
		}
		if taskErr == nil && task.TaskType == "sync_policy" {
			policy = cachedPolicy(store)
		}
		status := "succeeded"
		message := ""
		if taskErr != nil {
			status = "failed"
			message = taskErr.Error()
		}
		if err := saveTerminalTaskAndNotify(home, store, task, status, message); err != nil {
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

func saveTerminalTaskAndNotify(home string, store *Store, task Task, status, message string) error {
	if err := store.SaveTask(task, status, message); err != nil {
		return err
	}
	// Local completion is the point at which the desktop can update safely.
	// Platform reporting remains durable and retryable, so it must not delay
	// the visible result of an action already applied on this client.
	if err := store.EmitUIStateEvent(home, "local_task_completed", map[string]any{
		"task_id":   task.ID,
		"task_type": task.TaskType,
		"status":    status,
	}); err != nil {
		store.LogDiagnostic("warn", "desktop", "desktop_state_signal_failed", map[string]any{
			"task_id":   task.ID,
			"task_type": task.TaskType,
			"status":    status,
			"error":     err.Error(),
		})
	}
	return nil
}

func verifyTaskLocalCompletion(home string, store *Store, task Task) error {
	if task.TaskType == "skill_action" {
		action := stringValue(task.Payload, "action")
		path := stringValue(task.Payload, "path")
		switch action {
		case "uninstall", "quarantine":
			if path == "" {
				return fmt.Errorf("skill_target_unavailable")
			}
			if _, err := os.Lstat(path); !os.IsNotExist(err) {
				if err == nil {
					return fmt.Errorf("skill_action_not_applied")
				}
				return err
			}
			items, err := store.QuarantineItems()
			if err != nil {
				return err
			}
			for _, item := range items {
				if filepath.Clean(item.OriginalPath) == filepath.Clean(path) && (item.Status == "quarantined" || item.Status == "uninstalled") {
					return nil
				}
			}
			return fmt.Errorf("recovery_copy_not_persisted")
		case "restore_quarantine", "restore_backup":
			if path == "" {
				return fmt.Errorf("skill_target_unavailable")
			}
			if _, err := os.Stat(path); err != nil {
				return fmt.Errorf("skill_restore_not_applied: %w", err)
			}
		}
	}
	if task.TaskType == "install_skill" || task.TaskType == "repair_skill" {
		agentType := stringValue(task.Payload, "agent_type")
		skillID := stringValue(task.Payload, "skill_id")
		if agentType == "" || skillID == "" {
			return fmt.Errorf("skill_target_unavailable")
		}
		installs, err := store.Installations()
		if err != nil {
			return err
		}
		for _, install := range installs {
			if install.AgentType == agentType && install.SkillID == skillID {
				if _, err := os.Stat(install.TargetPath); err == nil {
					return nil
				} else if !os.IsNotExist(err) {
					return err
				}
			}
		}
		return fmt.Errorf("skill_install_not_persisted")
	}
	return nil
}

// ConfigureAgentModel requests an authorized model switch and executes the
// returned task immediately. The task-bound runtime credential is fetched by
// the sidecar and never exposed to the desktop renderer.
func ConfigureAgentModel(ctx context.Context, home string, inventory Inventory, api API, store *Store, localAgentID, agentType, managedAgentID, model string, options ...map[string]any) error {
	if len(options) > 0 {
		if parameters, ok := options[0]["parameters"].(map[string]any); ok && len(parameters) > 0 {
			fresh, err := Discover(home)
			if err != nil {
				return err
			}
			fresh.ClientID = inventory.ClientID
			if err := api.ReportInventory(ctx, fresh); err != nil {
				return err
			}
			inventory = fresh
		}
	}
	task, err := api.RequestModelConfiguration(ctx, inventory.ClientID, localAgentID, agentType, managedAgentID, model, options...)
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
	if err := saveTerminalTaskAndNotify(home, store, task, status, message); err != nil {
		return err
	}
	if err := api.ReportExecutedTask(ctx, inventory.ClientID, task, status, message); err != nil {
		return err
	}
	return taskErr
}

func executeTask(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, task Task) error {
	switch task.TaskType {
	case "aidr_skill_observe":
		return executeSkillObservation(ctx, home, inventory, api, task)
	case "aidr_plugin_action":
		if AIDRTaskHandler == nil {
			return fmt.Errorf("aidr_desktop_version_unsupported")
		}
		if action := stringValue(task.Payload, "action"); action == "enable" || action == "disable" {
			fresh, err := api.Policy(ctx, inventory.ClientID)
			if err != nil {
				return fmt.Errorf("aidr_desktop_policy_unavailable")
			}
			if fresh.Classification != nil && fresh.Classification.RuntimeGovernanceConfigured {
				return fmt.Errorf("aidr_desktop_task_superseded")
			}
		}
		if stringValue(task.Payload, "action") == "reconcile" {
			fresh, err := api.Policy(ctx, inventory.ClientID)
			if err != nil {
				return fmt.Errorf("aidr_desktop_policy_unavailable")
			}
			if fresh.Classification == nil || !fresh.Classification.RuntimeGovernanceConfigured || fresh.Classification.RuntimeGovernanceVersion != stringValue(task.Payload, "policy_version") {
				return fmt.Errorf("aidr_desktop_task_superseded")
			}
			target, _ := json.Marshal(task.Payload["target"])
			current, _ := json.Marshal(fresh.Classification.RuntimeGovernance)
			var a, b map[string]any
			if json.Unmarshal(target, &a) != nil || json.Unmarshal(current, &b) != nil {
				return fmt.Errorf("aidr_desktop_task_invalid")
			}
			// Nullable legacy fields are omitted when the typed API policy is
			// marshaled. Their null wire form carries the same policy meaning.
			for _, field := range []string{"modes", "channels", "log_sources", "system_targets"} {
				if a[field] == nil {
					delete(a, field)
				}
				if b[field] == nil {
					delete(b, field)
				}
			}
			// A nullable channel mode preserves its current behavior. Go's
			// string fields encode that same value as an empty string.
			for _, target := range []map[string]any{a, b} {
				if modes, ok := target["modes"].(map[string]any); ok {
					for _, channel := range []string{"hooks", "system"} {
						if modes[channel] == nil {
							modes[channel] = ""
						}
					}
				}
			}
			canonicalA, _ := json.Marshal(a)
			canonicalB, _ := json.Marshal(b)
			if string(canonicalA) != string(canonicalB) {
				return fmt.Errorf("aidr_desktop_policy_content_mismatch")
			}
		}
		result, err := AIDRTaskHandler(ctx, home, task)
		if result != nil {
			task.Payload["aidr_result"] = result
		}
		return err
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
	case "verify_model_config", "restore_model_config":
		kind, localID := stringValue(task.Payload, "agent_type"), stringValue(task.Payload, "local_agent_id")
		state := InspectModelConfig(home, kind)
		if state.ChangeID != stringValue(task.Payload, "change_id") || state.Revision != stringValue(task.Payload, "expected_revision") {
			return fmt.Errorf("model_config.conflict")
		}
		if task.TaskType == "restore_model_config" {
			if err := RestoreModelConfig(home, state.ChangeID); err != nil {
				return err
			}
			task.Payload["applied_model"] = InspectModelConfig(home, kind).Model
			return nil
		}
		evidence, err := VerifyModelConfig(ctx, home, kind, localID, api, inventory)
		if err != nil && state.VerificationMode == "client_call" {
			if restoreErr := RestoreModelConfig(home, state.ChangeID); restoreErr != nil {
				return fmt.Errorf("%w; model_config.auto_restore_failed: %v", err, restoreErr)
			}
			task.Payload["restored_after_failure"] = true
		}
		ids := []string{}
		for _, request := range evidence {
			if request.Status == "success" {
				ids = append(ids, request.RequestID)
			}
		}
		task.Payload["verification_request_ids"] = ids
		task.Payload["applied_model"] = state.Model
		if boolValue(task.Payload, "restored_after_failure") {
			task.Payload["applied_model"] = InspectModelConfig(home, kind).Model
		}
		return err
	case "apply_model_config":
		agentType := stringValue(task.Payload, "agent_type")
		localAgentID := stringValue(task.Payload, "local_agent_id")
		model := stringValue(task.Payload, "model")
		if agentType == "" || localAgentID == "" || model == "" {
			return fmt.Errorf("model config task is missing target Agent or model")
		}
		for _, key := range []string{"api_key", "token", "credential", "token_value"} {
			if strings.TrimSpace(stringValue(task.Payload, key)) != "" {
				return fmt.Errorf("model_config.secret_in_payload")
			}
		}
		gatewaySource := strings.TrimSpace(stringValue(task.Payload, "gateway_source"))
		credentialSource := strings.TrimSpace(stringValue(task.Payload, "credential_source"))
		verificationMode := strings.TrimSpace(stringValue(task.Payload, "verification_mode"))
		modelBaseURL := strings.TrimRight(strings.TrimSpace(stringValue(task.Payload, "model_base_url")), "/")
		if gatewaySource == "external" || gatewaySource == "external_gateway" {
			gatewaySource = "external"
			if modelBaseURL == "" || credentialSource != "external_gateway" || verificationMode != "client_call" {
				return fmt.Errorf("model_config.external_contract_invalid")
			}
		} else {
			modelBaseURL = api.server
		}
		if id, found, err := store.State(fmt.Sprintf("model-change:%d", task.ID)); err != nil {
			return err
		} else if found && id != "" {
			state := InspectModelConfig(home, agentType)
			if state.ChangeID == id && state.Model == model && state.Revision == state.AppliedRevision && state.CanRestore && (state.Status == "pending_restart" || state.Status == "verified") {
				return nil
			}
			return fmt.Errorf("model_config.retry_conflict")
		}
		parameters, _ := task.Payload["parameters"].(map[string]any)
		if err := ValidateModelParameters(agentType, parameters); err != nil {
			return err
		}
		if len(parameters) > 0 {
			binary, _ := exec.LookPath(modelAdapters[agentType].Binary)
			if err := validateModelParameterVersion(agentType, discoverModelVersion(home, agentType, binary), parameters); err != nil {
				return err
			}
		}
		revision, err := ModelConfigRevision(home, agentType)
		if err != nil {
			return err
		}
		expected := stringValue(task.Payload, "expected_revision")
		if expected != "" && revision != expected {
			return fmt.Errorf("model_config.conflict")
		}
		current, err := readModelParameters(home, agentType)
		if err != nil {
			return err
		}
		if err := api.PreflightModelTask(ctx, inventory.ClientID, task.ID, revision, current); err != nil {
			return err
		}
		credential := ""
		if boolValue(task.Payload, "auto_issue_credential") || credentialSource != "" {
			previousHash := ""
			if previous, err := nativeModelCredential(home, agentType); err == nil && previous != "" {
				hash := sha256.Sum256([]byte(previous))
				previousHash = hex.EncodeToString(hash[:])
			}
			issued, err := api.IssueTaskCredential(ctx, inventory.ClientID, task.ID, credentialSource, previousHash)
			if err != nil {
				return fmt.Errorf("issue Agent runtime credential: %w", err)
			}
			credential = issued.Token
			if gatewaySource == "external" && strings.TrimRight(strings.TrimSpace(issued.GatewayBaseURL), "/") != modelBaseURL {
				return fmt.Errorf("model_config.credential_gateway_mismatch")
			}
			if credential == "" {
				return fmt.Errorf("Agent Manager returned an empty Agent runtime credential")
			}
		}
		route := map[string]any{"gateway_source": gatewaySource, "credential_source": credentialSource, "verification_mode": verificationMode}
		change, err := ApplyModelConfigRevision(home, modelBaseURL, localAgentID, agentType, model, credential, revision, parameters, route)
		if change.ID != "" {
			_ = store.SetState(fmt.Sprintf("model-change:%d", task.ID), change.ID)
		}
		return err
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

type InstallTarget struct {
	AgentType      string `json:"agent_type"`
	ManagedAgentID string `json:"managed_agent_id,omitempty"`
}

type InstallTargetResult struct {
	AgentType string `json:"agent_type"`
	Success   bool   `json:"success"`
	Error     string `json:"error,omitempty"`
}

type InstallProgress struct {
	Stage     string `json:"stage"`
	AgentType string `json:"agent_type,omitempty"`
	Status    string `json:"status,omitempty"`
	Error     string `json:"error,omitempty"`
	Completed int    `json:"completed"`
	Total     int    `json:"total"`
}

type preparedInstallPackage struct {
	root     string
	manifest releaseManifest
}

// InstallApprovedSkillVersionBatch authorizes every selected Agent, downloads
// and verifies one immutable package, then binds that release into each Agent
// independently. A target failure does not prevent the remaining targets from
// being attempted.
func InstallApprovedSkillVersionBatch(
	ctx context.Context,
	home string,
	inventory Inventory,
	policy Policy,
	api API,
	store *Store,
	targets []InstallTarget,
	skillID string,
	versionID string,
	progress func(InstallProgress),
) ([]InstallTargetResult, error) {
	if !validInstallComponent(skillID) || (versionID != "" && !validInstallComponent(versionID)) {
		return nil, fmt.Errorf("invalid install identifier")
	}
	if len(targets) == 0 {
		return nil, fmt.Errorf("install requires at least one target Agent")
	}
	emit := func(value InstallProgress) {
		value.Total = len(targets)
		if progress != nil {
			progress(value)
		}
	}
	emit(InstallProgress{Stage: "validating", Status: "running"})
	eligible := make([]InstallTarget, 0, len(targets))
	results := make([]InstallTargetResult, 0, len(targets))
	completed := 0
	seen := map[string]struct{}{}
	for _, target := range targets {
		target.AgentType = strings.TrimSpace(target.AgentType)
		if target.AgentType == "" {
			completed++
			results = append(results, InstallTargetResult{Success: false, Error: "target Agent type is required"})
			emit(InstallProgress{Stage: "target", Status: "failed", Error: "target Agent type is required", Completed: completed})
			continue
		}
		if _, duplicate := seen[target.AgentType]; duplicate {
			completed++
			results = append(results, InstallTargetResult{AgentType: target.AgentType, Success: false, Error: "duplicate target Agent"})
			emit(InstallProgress{Stage: "target", AgentType: target.AgentType, Status: "failed", Error: "duplicate target Agent", Completed: completed})
			continue
		}
		seen[target.AgentType] = struct{}{}
		agent, ok := findAgent(inventory, target.AgentType)
		if !ok || !agent.SkillManagementSupported || agent.SkillsPath == "" {
			completed++
			errText := fmt.Sprintf("agent %s does not support managed skills", target.AgentType)
			results = append(results, InstallTargetResult{AgentType: target.AgentType, Success: false, Error: errText})
			emit(InstallProgress{Stage: "target", AgentType: target.AgentType, Status: "failed", Error: errText, Completed: completed})
			continue
		}
		if _, err := api.SkillPreview(ctx, inventory.ClientID, skillID, versionID, target.AgentType, target.ManagedAgentID); err != nil {
			completed++
			results = append(results, InstallTargetResult{AgentType: target.AgentType, Success: false, Error: err.Error()})
			emit(InstallProgress{Stage: "target", AgentType: target.AgentType, Status: "failed", Error: err.Error(), Completed: completed})
			continue
		}
		eligible = append(eligible, target)
	}
	if len(eligible) == 0 {
		emit(InstallProgress{Stage: "complete", Status: "failed", Completed: completed})
		return results, nil
	}

	emit(InstallProgress{Stage: "downloading", Status: "running", Completed: completed})
	packageTarget := eligible[0]
	body, err := api.DownloadPackageVersion(ctx, inventory.ClientID, skillID, versionID, packageTarget.AgentType, packageTarget.ManagedAgentID)
	if err != nil {
		return results, err
	}
	emit(InstallProgress{Stage: "verifying", Status: "running", Completed: completed})
	staging, err := newInstallStaging(home)
	if err != nil {
		return results, err
	}
	defer os.RemoveAll(staging)
	incoming := filepath.Join(staging, "release")
	manifest, err := VerifyAndExtractPackage(body, policy.ReleasePublicKey, incoming)
	if err != nil {
		return results, err
	}
	defer os.RemoveAll(incoming)
	prepared := preparedInstallPackage{root: incoming, manifest: manifest}
	emit(InstallProgress{Stage: "prepared", Status: "succeeded", Completed: completed})

	for _, target := range eligible {
		emit(InstallProgress{Stage: "target", AgentType: target.AgentType, Status: "running", Completed: completed})
		err := installApprovedSkillVersionWithPackage(ctx, home, inventory, policy, api, store, target.AgentType, target.ManagedAgentID, skillID, versionID, false, nil, &prepared)
		completed++
		result := InstallTargetResult{AgentType: target.AgentType, Success: err == nil}
		status := "succeeded"
		if err != nil {
			result.Error = err.Error()
			status = "failed"
		}
		results = append(results, result)
		emit(InstallProgress{Stage: "target", AgentType: target.AgentType, Status: status, Error: result.Error, Completed: completed})
	}
	status := "succeeded"
	for _, result := range results {
		if !result.Success {
			status = "partial"
			break
		}
	}
	emit(InstallProgress{Stage: "complete", Status: status, Completed: completed})
	return results, nil
}

func installApprovedSkillVersion(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, agentType, managedAgentID, skillID, versionID string, repair bool, taskPayload ...map[string]any) error {
	return installApprovedSkillVersionWithPackage(ctx, home, inventory, policy, api, store, agentType, managedAgentID, skillID, versionID, repair, taskPayload, nil)
}

func installApprovedSkillVersionWithPackage(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, agentType, managedAgentID, skillID, versionID string, repair bool, taskPayload []map[string]any, prepared *preparedInstallPackage) error {
	if !validInstallComponent(skillID) || (versionID != "" && !validInstallComponent(versionID)) {
		return fmt.Errorf("invalid install identifier")
	}
	if agentType == "" || skillID == "" || (policy.GovernanceMode == "strict" && managedAgentID == "") {
		return fmt.Errorf("install requires agent and skill information")
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
	var incoming string
	var manifest releaseManifest
	if prepared != nil {
		incoming = prepared.root
		manifest = prepared.manifest
	} else {
		body, err := api.DownloadPackageVersion(ctx, inventory.ClientID, skillID, versionID, agentType, managedAgentID)
		if err != nil {
			return err
		}
		staging, err := newInstallStaging(home)
		if err != nil {
			return err
		}
		defer os.RemoveAll(staging)
		incoming = filepath.Join(staging, "release")
		manifest, err = VerifyAndExtractPackage(body, policy.ReleasePublicKey, incoming)
		if err != nil {
			return err
		}
		defer os.RemoveAll(incoming)
	}
	resolvedVersionID := manifest.VersionID
	if resolvedVersionID == "" {
		resolvedVersionID = skillID
	}
	target := filepath.Join(ManagedSkillsRoot(home), skillID, "versions", resolvedVersionID, "release")
	link := filepath.Join(agent.SkillsPath, filepath.Base(manifest.Name))
	ctx, releaseMutation, err := withFileLocks(ctx, home, link, filepath.Join(ManagedSkillsRoot(home), skillID))
	if err != nil {
		return err
	}
	defer releaseMutation()
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
			sameInstall = sameInstall || (resolveErr == nil && targetErr == nil && filepath.Clean(resolved) == filepath.Clean(resolvedTarget))
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
		targetInfo, targetErr := os.Stat(target)
		if targetErr != nil && !os.IsNotExist(targetErr) {
			return targetErr
		}
		targetTrusted := targetErr == nil && targetInfo.IsDir() && checkObservedContent(Skill{Path: target, Signature: manifest.ContentSignature}) == nil
		if !targetTrusted {
			reusable, found, err := reusableManagedRelease(home, store, skillID, manifest)
			if err != nil {
				return err
			}
			if found {
				target = reusable
				_, preserveAlias = aliasBeforeDownload[currentAlias]
			} else if targetErr == nil {
				copyRoot, err := os.MkdirTemp(filepath.Dir(target), "copy-")
				if err != nil {
					return err
				}
				defer os.Remove(copyRoot) // Remove the reservation only if it remains empty.
				target = filepath.Join(copyRoot, "release")
				_, preserveAlias = aliasBeforeDownload[currentAlias]
			}
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
	if before, exists := aliasBeforeDownload[currentAlias]; exists && before.mode.IsDir() && before.signature != manifest.ContentSignature {
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
		if err := createManagedPath(target, currentAlias, managedAliasCopyFallback); err != nil {
			return err
		}
	}
	if err := os.RemoveAll(link); err != nil {
		return err
	}
	if err := createManagedPath(target, link, true); err != nil {
		return err
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
	if _, err := store.ResolveInstalledRecovery(agentType, manifest.Name, link, manifest.ContentSignature); err != nil {
		return err
	}
	if err := store.resolvePendingForInstall(ctx, agentType, manifest.Name, link); err != nil {
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

// ReconcileInstalledRecoveryCopies hides stale active recovery rows only when
// the exact recorded installation is present and still matches its signed
// release manifest.
func ReconcileInstalledRecoveryCopies(home string, store *Store) (bool, error) {
	installs, err := store.Installations()
	if err != nil {
		return false, err
	}
	changed := false
	for _, install := range installs {
		if !installPathPresent(install) || !verifyManagedInstall(home, install) {
			continue
		}
		resolved, err := store.ResolveInstalledRecovery(
			install.AgentType,
			install.SkillName,
			install.TargetPath,
			install.Manifest.ContentSignature,
		)
		if err != nil {
			return changed, err
		}
		if resolved {
			changed = true
			store.LogDiagnostic("info", "recovery", "installed_copy_resolved", map[string]any{
				"agent_type":  install.AgentType,
				"skill_name":  install.SkillName,
				"target_path": install.TargetPath,
			})
		}
	}
	return changed, nil
}

// ReconcileSharedManagedInstalls repairs duplicate physical copies left by
// older multi-Agent installs. Only exact, independently verified signed
// versions are consolidated; the redundant release directories are retained
// so the link change does not discard recoverable data.
func ReconcileSharedManagedInstalls(ctx context.Context, home string, store *Store) (bool, error) {
	if err := ctx.Err(); err != nil {
		return false, err
	}
	installs, err := store.Installations()
	if err != nil {
		return false, err
	}
	type verifiedInstall struct {
		install Installation
		target  string
	}
	groups := map[string][]verifiedInstall{}
	for _, install := range installs {
		if install.SkillID == "" || install.Manifest.ContentSignature == "" || !verifyManagedInstall(home, install) {
			continue
		}
		target, managed := managedSymlinkTarget(home, install)
		if !managed {
			continue
		}
		key := install.SkillID + "\x00" + install.Manifest.VersionID + "\x00" + install.Manifest.ContentSignature
		groups[key] = append(groups[key], verifiedInstall{install: install, target: target})
	}
	paths := []string{}
	for _, group := range groups {
		if len(group) > 1 {
			for _, candidate := range group {
				paths = append(paths, candidate.install.TargetPath, candidate.target)
			}
		}
	}
	if len(paths) == 0 {
		return false, nil
	}
	_, releaseMutation, err := withFileLocks(ctx, home, paths...)
	if err != nil {
		return false, err
	}
	defer releaseMutation()
	changed := false
	for _, group := range groups {
		if len(group) < 2 {
			continue
		}
		canonical := group[0]
		for _, candidate := range group[1:] {
			if filepath.Clean(candidate.target) == filepath.Clean(canonical.target) {
				continue
			}
			if err := ctx.Err(); err != nil {
				return changed, err
			}
			current, managed := managedSymlinkTarget(home, candidate.install)
			if !managed || filepath.Clean(current) != filepath.Clean(candidate.target) || !verifyManagedInstall(home, candidate.install) || !verifyManagedInstall(home, canonical.install) {
				continue
			}
			previous := candidate.install.TargetPath + fmt.Sprintf(".agent-manager-previous-%d", time.Now().UnixNano())
			if err := os.Rename(candidate.install.TargetPath, previous); err != nil {
				return changed, err
			}
			if err := os.Symlink(canonical.target, candidate.install.TargetPath); err != nil {
				_ = os.Rename(previous, candidate.install.TargetPath)
				return changed, err
			}
			if !verifyManagedInstall(home, candidate.install) {
				_ = os.Remove(candidate.install.TargetPath)
				_ = os.Rename(previous, candidate.install.TargetPath)
				return changed, fmt.Errorf("shared install verification failed")
			}
			if err := os.Remove(previous); err != nil {
				return changed, err
			}
			changed = true
			store.LogDiagnostic("info", "install", "shared_copy_reconciled", map[string]any{
				"agent_type":  candidate.install.AgentType,
				"skill_id":    candidate.install.SkillID,
				"target_path": candidate.install.TargetPath,
				"shared_with": canonical.install.AgentType,
			})
		}
	}
	return changed, nil
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
			if _, err := store.ResolveInstalledRecovery(install.AgentType, install.SkillName, install.TargetPath, install.Manifest.ContentSignature); err != nil {
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
	ctx, err := withPatrolSnapshot(ctx, installs)
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
		versionID := install.Manifest.VersionID
		if versionID == "" {
			versionID = install.SkillID
		}
		candidates = append(candidates, filepath.Join(root, install.SkillID, "versions", versionID, "release"))
		if install.Manifest.ContentSignature != "" {
			candidates = append(candidates, filepath.Join(root, install.SkillID, install.Manifest.ContentSignature))
		}
		for _, expected := range candidates {
			if filepath.Clean(target) == filepath.Clean(expected) {
				return expected, true
			}
		}
		versionRoot := filepath.Join(root, install.SkillID, "versions", versionID)
		if isManagedCopyRelease(versionRoot, target) {
			return filepath.Clean(target), true
		}
	}
	return "", false
}

func isManagedCopyRelease(versionRoot, target string) bool {
	relative, err := filepath.Rel(versionRoot, filepath.Clean(target))
	if err != nil {
		return false
	}
	parts := strings.Split(filepath.ToSlash(relative), "/")
	if len(parts) != 2 || parts[1] != "release" || !strings.HasPrefix(parts[0], "copy-") || len(parts[0]) == len("copy-") {
		return false
	}
	for _, value := range strings.TrimPrefix(parts[0], "copy-") {
		if value < '0' || value > '9' {
			return false
		}
	}
	return true
}

// Reuse an already verified local copy of the same signed version. This keeps
// multi-Agent installs physically shared even when an edited legacy release
// forced the first target onto an isolated copy-* directory.
func reusableManagedRelease(home string, store *Store, skillID string, release releaseManifest) (string, bool, error) {
	installs, err := store.Installations()
	if err != nil {
		return "", false, err
	}
	for _, install := range installs {
		if install.SkillID != skillID || install.Manifest.VersionID != release.VersionID || install.Manifest.ContentSignature != release.ContentSignature {
			continue
		}
		target, managed := managedSymlinkTarget(home, install)
		if !managed || !verifyInstalled(install) {
			continue
		}
		return target, true, nil
	}
	return "", false, nil
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
	pathsToLock := []string{releasePath}
	for _, install := range installs {
		pathsToLock = append(pathsToLock, install.TargetPath, filepath.Join(ManagedSkillsRoot(home), install.SkillID))
	}
	ctx, releaseMutation, err := withFileLocks(ctx, home, pathsToLock...)
	if err != nil {
		return err
	}
	defer releaseMutation()
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
	return reportEventWithLocalNotification(ctx, api, store, clientID, eventType, agentType, skillName, details, true)
}

func reportEventWithLocalNotification(ctx context.Context, api API, store *Store, clientID, eventType, agentType, skillName string, details map[string]any, notifyLocal bool) error {
	event, err := recordEventLocally(store, clientID, eventType, agentType, skillName, details, notifyLocal)
	if err != nil {
		return err
	}
	event.Server = api.server
	if err := store.QueueEvent(event); err != nil {
		return err
	}
	// Continuous observations are drained by the event worker, allowing coalescing.
	if observationIdentity(event) != "" {
		return nil
	}
	_ = flushEventsLimit(ctx, api, store, 2)
	return nil
}

func queueEventWithLocalNotification(store *Store, server, clientID, eventType, agentType, skillName string, details map[string]any, notifyLocal bool) error {
	event, err := recordEventLocally(store, clientID, eventType, agentType, skillName, details, notifyLocal)
	if err != nil {
		return err
	}
	event.Server = server
	return store.QueueEvent(event)
}

func recordEventLocally(store *Store, clientID, eventType, agentType, skillName string, details map[string]any, notifyLocal bool) (QueuedEvent, error) {
	if details == nil {
		details = map[string]any{}
	}
	if _, ok := details["last_seen_at"]; !ok {
		details["last_seen_at"] = time.Now().UTC().Format(time.RFC3339Nano)
	}
	store.LogDiagnostic("info", "governance", eventType, map[string]any{"client_id": clientID, "agent_type": agentType, "skill_name": skillName, "details": details})
	if notifyLocal {
		if notification, ok := notificationForEvent(eventType, agentType, skillName, details); ok {
			_ = store.RecordNotification(notification)
		}
	}
	if eventType == "skill_modified" || eventType == "unmanaged_skill_found" || eventType == "skill_quarantined" {
		if err := store.RecordPatrolFinding(PatrolFinding{EventType: eventType, AgentType: agentType, SkillName: skillName}); err != nil {
			return QueuedEvent{}, err
		}
	}
	return QueuedEvent{ClientID: clientID, EventType: eventType, AgentType: agentType, SkillName: skillName, Details: details}, nil
}

func flushEvents(ctx context.Context, api API, store *Store) error {
	return flushEventsLimit(ctx, api, store, 20)
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

func ConfigureModelOperation(ctx context.Context, home, kind, operation string, api API, inventory Inventory, store *Store) error {
	state := InspectModelConfig(home, kind)
	if err := api.ReportInventory(ctx, inventory); err != nil {
		return err
	}
	var task Task
	if err := api.postJSON(ctx, "/api/v1/clients/"+inventory.ClientID+"/model-operations", map[string]any{"task_type": operation, "payload": map[string]any{"agent_type": kind, "local_agent_id": kind, "change_id": state.ChangeID, "expected_revision": state.Revision}}, &task); err != nil {
		return err
	}
	if task.ID == 0 || task.TaskType != operation {
		return fmt.Errorf("model_config.operation_invalid")
	}
	claimed, _, err := api.StartTask(ctx, inventory.ClientID, task.ID)
	if err != nil {
		return err
	}
	if !claimed {
		return fmt.Errorf("model_config.locked")
	}

	if err := store.SaveTask(task, "running", ""); err != nil {
		return err
	}
	taskErr := executeTask(ctx, home, inventory, Policy{}, api, store, task)
	status, message := "succeeded", ""
	if taskErr != nil {
		status, message = "failed", taskErr.Error()
	}
	if err := saveTerminalTaskAndNotify(home, store, task, status, message); err != nil {
		return err
	}
	if err := api.ReportExecutedTask(ctx, inventory.ClientID, task, status, message); err != nil {
		return err
	}
	return taskErr
}
