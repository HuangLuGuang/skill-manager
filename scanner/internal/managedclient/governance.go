package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"skill-manager/scanner/internal/manifest"
)

type ClassificationPolicy struct {
	Protocol int               `json:"protocol"`
	Enabled  bool              `json:"enabled"`
	Version  string            `json:"version"`
	Rules    map[string]string `json:"rules"`
	Sources  map[string]string `json:"sources"`
}

type SkillObservation struct {
	Scan             *SkillScanObservation `json:"scan,omitempty"`
	Signature        string                `json:"signature"`
	TrustedSignature string                `json:"trusted_signature,omitempty"`
	TrustedSkillID   string                `json:"trusted_skill_id,omitempty"`
	TrustedVersionID string                `json:"trusted_version_id,omitempty"`
	Certification    string                `json:"certification"`
	Trigger          string                `json:"trigger,omitempty"`
	Malicious        bool                  `json:"malicious"`
	Action           string                `json:"action"`
	PolicyVersion    string                `json:"policy_version"`
	LastSeenAt       string                `json:"last_seen_at"`
	LastConfirmedAt  string                `json:"last_confirmed_at,omitempty"`
	ActionKey        string                `json:"action_key,omitempty"`
	ActionStatus     string                `json:"action_status,omitempty"`
	ErrorCode        string                `json:"error_code,omitempty"`
	Count            int                   `json:"count"`
	PendingID        string                `json:"pending_id,omitempty"`
	QuarantineID     string                `json:"quarantine_id,omitempty"`
}

type SkillScanObservation struct {
	Status    string       `json:"status"`
	SkillID   string       `json:"skill_id,omitempty"`
	VersionID string       `json:"version_id,omitempty"`
	Progress  ScanProgress `json:"progress"`
}

var classificationActions = map[string]map[string]bool{
	"trusted_scan_rejected":      {"record_only": true, "record": true, "quarantine": true, "restore_trusted": true},
	"unverified_scan_rejected":   {"record_only": true, "record": true, "quarantine": true},
	"unverified":                 {"record_only": true, "record": true, "submit_scan": true, "quarantine": true},
	"malicious":                  {"record_only": true, "record": true, "quarantine": true, "uninstall": true},
	"trusted_content_changed":    {"record_only": true, "record": true, "submit_scan": true, "quarantine": true, "restore_trusted": true},
	"unverified_content_changed": {"record_only": true, "record": true, "submit_scan": true, "quarantine": true},
}

func DefaultClassificationPolicy() *ClassificationPolicy {
	return &ClassificationPolicy{Protocol: 2, Enabled: true, Version: "default", Rules: map[string]string{
		"trusted_scan_rejected": "record", "unverified_scan_rejected": "record",
		"unverified": "record", "malicious": "record", "trusted_content_changed": "record", "unverified_content_changed": "record",
	}}
}

func classificationEnabled(policy Policy) bool {
	return policy.Classification != nil && policy.Classification.Enabled && (policy.Classification.Protocol == 1 || policy.Classification.Protocol == 2)
}

func observationKey(path string) string {
	sum := sha256.Sum256([]byte(filepath.Clean(path)))
	return "observation:" + hex.EncodeToString(sum[:])
}

func (store *Store) Observation(path string) (SkillObservation, error) {
	var value SkillObservation
	body, exists, err := store.State(observationKey(path))
	if err != nil || !exists {
		return value, err
	}
	err = json.Unmarshal([]byte(body), &value)
	return value, err
}

func (store *Store) SaveObservation(path string, value SkillObservation) error {
	body, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return store.SetState(observationKey(path), string(body))
}

// classifyObservation retains the trusted baseline through repeated edits. A
// verdict is used only for the precise content returned by Compare.
func classifyObservation(previous SkillObservation, skill Skill, comparison *CompareItem) SkillObservation {
	value := previous
	value.Signature = skill.Signature
	value.LastSeenAt = time.Now().UTC().Format(time.RFC3339Nano)
	value.Count++
	if previous.Signature != skill.Signature {
		value.Malicious = false
		value.PendingID = ""
		value.QuarantineID = ""
	}
	confirmed := comparison != nil && comparison.LocalSignature == skill.Signature && skill.Signature != ""
	if confirmed {
		value.Malicious = comparison.Malicious
		value.LastConfirmedAt = value.LastSeenAt
	}
	switch {
	case value.Malicious:
		value.Trigger = "malicious"
		value.Certification = "unverified"
	case confirmed && comparison.Certified:
		value.TrustedSignature = skill.Signature
		value.TrustedSkillID = comparison.SkillID
		value.TrustedVersionID = comparison.VersionID
		value.Trigger = ""
		value.Certification = "certified"
	case confirmed && comparison.ExpectedSignature == skill.Signature && comparison.Status == "REJECTED" && comparison.Rejected && value.PendingID != "":
		value.Certification = "unverified"
		value.Trigger = "unverified_scan_rejected"
		if value.TrustedSignature != "" && value.TrustedSignature != skill.Signature {
			value.Certification = "changed"
			value.Trigger = "trusted_scan_rejected"
		}
	case value.TrustedSignature != "" && value.TrustedSignature != skill.Signature:
		value.Trigger = "trusted_content_changed"
		value.Certification = "changed"
	case !confirmed && value.TrustedSignature != "" && value.TrustedSignature == skill.Signature:
		value.Trigger = ""
		value.Certification = "confirmation_pending"
	case previous.Signature != "" && (previous.Signature != skill.Signature || previous.Trigger == "unverified_content_changed"):
		value.Trigger = "unverified_content_changed"
		value.Certification = "unverified"
	default:
		value.Trigger = "unverified"
		value.Certification = "unverified"
	}
	if !confirmed && value.Certification == "unverified" {
		value.Certification = "confirmation_pending"
	}
	return value
}

func patrolClassified(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, online bool) error {
	compared := map[string]CompareItem{}
	if online {
		items, err := api.Compare(ctx, inventory, policy.AgentBindings)
		if err != nil {
			online = false
		} else {
			for _, item := range items {
				compared[comparisonKey(item.AgentType, item.Name, item.LocalPath, item.LocalSignature)] = item
			}
		}
	}
	installs, err := store.Installations()
	if err != nil {
		return err
	}
	baselines := map[string]Installation{}
	for _, install := range installs {
		baselines[filepath.Clean(install.TargetPath)] = install
	}
	physicalPaths := map[string]string{}
	representatives := map[string]string{}
	for _, agent := range inventory.Agents {
		if !agent.SkillManagementSupported {
			continue
		}
		for _, skill := range agent.Skills {
			physical := canonicalSkillRoot(skill.Path)
			physicalPaths[skill.Path] = physical
			if representatives[physical] == "" {
				representatives[physical] = skill.Path
			}
			// Prefer the discovered directory over a Skill symlink so one
			// physical quarantine also disables its other Agent readers.
			if info, err := os.Lstat(skill.Path); err == nil && info.IsDir() {
				representatives[physical] = skill.Path
			}
		}
	}
	handled := map[string]bool{}
	var failures []error
	for _, agent := range inventory.Agents {
		if !agent.SkillManagementSupported {
			continue
		}
		for _, skill := range agent.Skills {
			key := physicalPaths[skill.Path]
			if representatives[key] != skill.Path {
				continue
			}
			if handled[key] {
				continue
			}
			handled[key] = true
			previous, err := store.Observation(skill.Path)
			if err != nil {
				failures = append(failures, err)
				continue
			}
			if previous.TrustedSignature == "" {
				if install, ok := baselines[filepath.Clean(skill.Path)]; ok {
					previous.TrustedSignature = install.Manifest.ContentSignature
					previous.TrustedSkillID = install.SkillID
					previous.TrustedVersionID = install.Manifest.VersionID
				}
			}
			var comparison *CompareItem
			if item, ok := compared[comparisonKey(agent.AgentType, skill.Name, skill.Path, skill.Signature)]; ok {
				comparison = &item
			}
			value := classifyObservation(previous, skill, comparison)
			var recoveryIDs map[string]string
			value.PolicyVersion = policy.Classification.Version
			value.Action = policy.Classification.Rules[value.Trigger]
			if value.Trigger != "" && !classificationActions[value.Trigger][value.Action] {
				value.Action = "record"
			}
			actionKey := skill.Signature + ":" + value.Trigger + ":" + value.Action + ":" + value.PolicyVersion
			if value.Trigger != "" {
				counterKey := "observation-count:" + observationKey(skill.Path+":"+actionKey)
				if err := store.db.QueryRow(`INSERT INTO client_state(key,value,updated_at) VALUES(?,'1',?)
					ON CONFLICT(key) DO UPDATE SET value=CAST(client_state.value AS INTEGER)+1, updated_at=excluded.updated_at
					RETURNING value`, counterKey, value.LastSeenAt).Scan(&value.Count); err != nil {
					failures = append(failures, err)
					continue
				}
			}
			// An active path discovered after successful removal is a new
			// installation occurrence even when its content is unchanged.
			reappeared := previous.ActionStatus == "completed" && (value.Action == "quarantine" || value.Action == "uninstall")
			if actionKey != previous.ActionKey || reappeared {
				value.ActionKey = actionKey
				value.ActionStatus = "pending"
				value.ErrorCode = ""
			}
			if value.Trigger != "" {
				eventType := "skill_governance_detected"
				if value.Action == "record_only" {
					eventType = "skill_governance_recorded"
				}
				if err := reportEvent(ctx, api, store, inventory.ClientID, eventType, agent.AgentType, skill.Name, map[string]any{
					"path": skill.Path, "signature": skill.Signature, "trigger": value.Trigger, "action": value.Action,
					"policy_version": value.PolicyVersion, "event_key": observationKey(skill.Path) + ":" + actionKey,
					"observation_count": value.Count, "last_seen_at": value.LastSeenAt,
				}); err != nil {
					failures = append(failures, err)
				}
			}
			if value.Trigger == "" {
				value.ActionStatus = "completed"
			} else if value.ActionStatus != "completed" {
				if value.Action == "record" || value.Action == "record_only" {
					value.ActionStatus = "completed"
				} else if skill.Signature == "" {
					value.ActionStatus, value.ErrorCode = "failed", "skill_content_unavailable"
				} else if !online && (value.Action == "submit_scan" || value.Action == "restore_trusted") {
					value.ActionStatus, value.ErrorCode = "waiting", "platform_unavailable"
				} else {
					actionInventory := inventory
					actionInventory.Agents = nil
					for _, reader := range inventory.Agents {
						reader.Skills = append([]Skill(nil), reader.Skills...)
						matching := reader.Skills[:0]
						for _, alias := range reader.Skills {
							if physicalPaths[alias.Path] == key {
								matching = append(matching, alias)
							}
						}
						reader.Skills = matching
						if len(matching) > 0 {
							actionInventory.Agents = append(actionInventory.Agents, reader)
						}
					}
					var err error
					recoveryIDs, err = applyAutomaticObservedAction(ctx, home, actionInventory, agent, skill, key, policy, api, store, &value)
					if err != nil {
						value.ActionStatus = "failed"
						if value.ErrorCode == "" {
							value.ErrorCode = "skill_action_failed"
						}
						failures = append(failures, err)
					} else {
						value.ActionStatus, value.ErrorCode = "completed", ""
					}
					_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_governance_action", agent.AgentType, skill.Name, map[string]any{
						"path": skill.Path, "signature": skill.Signature, "trigger": value.Trigger, "action": value.Action,
						"policy_version": value.PolicyVersion, "status": value.ActionStatus, "error_code": value.ErrorCode,
						"quarantine_id": value.QuarantineID, "pending_id": value.PendingID,
						"quarantine_ids_by_path": recoveryIDs,
					})
				}
			}
			for _, reader := range inventory.Agents {
				for _, alias := range reader.Skills {
					if physicalPaths[alias.Path] == key && alias.Signature == skill.Signature {
						aliasValue := value
						if recoveryIDs != nil {
							aliasValue.QuarantineID = recoveryIDs[alias.Path]
						}
						if err := store.SaveObservation(alias.Path, aliasValue); err != nil {
							failures = append(failures, err)
						}
					}
				}
			}
		}
	}
	return errors.Join(failures...)
}

func checkObservedContent(skill Skill) error {
	root, err := filepath.EvalSymlinks(skill.Path)
	if err != nil {
		return err
	}
	value, err := manifest.Build(root, DefaultManifestOptions())
	if err != nil {
		return err
	}
	if skill.Signature == "" || manifest.ContentSignature(value.Files) != skill.Signature {
		return fmt.Errorf("skill_content_changed")
	}
	return nil
}

func copyObservedSnapshot(skill Skill, target string) error {
	value, err := manifest.Build(skill.Path, DefaultManifestOptions())
	if err != nil {
		return err
	}
	if manifest.ContentSignature(value.Files) != skill.Signature {
		return fmt.Errorf("skill_content_changed")
	}
	for _, entry := range value.Files {
		path := filepath.Join(skill.Path, filepath.FromSlash(entry.Path))
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("skill_content_changed")
		}
		destination := filepath.Join(target, filepath.FromSlash(entry.Path))
		if err := os.MkdirAll(filepath.Dir(destination), 0700); err != nil {
			return err
		}
		source, err := os.Open(path)
		if err != nil {
			return err
		}
		output, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, info.Mode().Perm())
		if err != nil {
			source.Close()
			return err
		}
		copied, copyErr := io.Copy(output, io.LimitReader(source, entry.Size+1))
		source.Close()
		closeErr := output.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
		if copied != entry.Size {
			return fmt.Errorf("skill_content_changed")
		}
	}
	return nil
}

func submitObservedSkill(ctx context.Context, home string, agent Agent, skill Skill, api API, store *Store) (string, error) {
	id := observationKey(skill.Path + ":" + skill.Signature)[len("observation:"):]
	target := filepath.Join(PendingRoot(home), "observed-"+id)
	if _, err := os.Stat(target); os.IsNotExist(err) {
		if err := os.MkdirAll(PendingRoot(home), 0700); err != nil {
			return "", err
		}
		staging, err := os.MkdirTemp(PendingRoot(home), ".snapshot-")
		if err != nil {
			return "", err
		}
		defer os.RemoveAll(staging)
		if err := copyObservedSnapshot(skill, staging); err != nil {
			return "", err
		}
		snapshot := skill
		snapshot.Path = staging
		if err := checkObservedContent(snapshot); err != nil {
			return "", err
		}
		if err := os.Rename(staging, target); err != nil {
			return "", err
		}
	}
	snapshot := skill
	snapshot.Path = target
	if err := checkObservedContent(snapshot); err != nil {
		return "", err
	}
	pending := PendingItem{ID: id, AgentType: agent.AgentType, SkillName: skill.Name, OriginalPath: skill.Path, PendingPath: target, Reason: "observed_scan"}
	if err := store.SavePending(pending); err != nil {
		return "", err
	}
	_, err := SubmitPending(ctx, home, api.server, api.token, store, id)
	return id, err
}

// SubmitDiscoveredSkill snapshots the exact content selected in the desktop.
// The scanner upload endpoint authorizes submission with the client credential.
func SubmitDiscoveredSkill(ctx context.Context, home string, api API, store *Store, agentType, path, expectedSignature string) (string, error) {
	release, err := AcquireMutationLock(home)
	if err != nil {
		return "", err
	}
	defer release()
	inventory, err := Discover(home)
	if err != nil {
		return "", err
	}
	for _, agent := range inventory.Agents {
		if agent.AgentType != agentType || !agent.SkillManagementSupported {
			continue
		}
		for _, skill := range agent.Skills {
			if filepath.Clean(skill.Path) != filepath.Clean(path) {
				continue
			}
			if expectedSignature == "" || skill.Signature != expectedSignature {
				return "", fmt.Errorf("skill_content_changed")
			}
			if err := checkObservedContent(skill); err != nil {
				return "", err
			}
			id, submitErr := submitObservedSkill(ctx, home, agent, skill, api, store)
			if id != "" {
				value, err := store.Observation(skill.Path)
				if err != nil {
					return id, err
				}
				if value.Signature != skill.Signature {
					value = classifyObservation(value, skill, nil)
				}
				value.PendingID = id
				if err := store.SaveObservation(skill.Path, value); err != nil {
					return id, err
				}
				_ = RequestFullScan(home)
			}
			if submitErr == nil {
				_ = reportEvent(ctx, api, store, inventory.ClientID, "skill_scan_submitted", agent.AgentType, skill.Name, map[string]any{
					"path": skill.Path, "signature": skill.Signature, "pending_id": id, "source": "manual",
				})
			}
			return id, submitErr
		}
	}
	return "", fmt.Errorf("skill_target_unavailable")
}

func executeObservedTask(ctx context.Context, home string, policy Policy, api API, store *Store, task Task) error {
	if task.ID <= 0 {
		return fmt.Errorf("skill_action_task_required")
	}
	receiptKey := fmt.Sprintf("skill-action-receipt:%d", task.ID)
	if _, exists, err := store.State(receiptKey); err != nil || exists {
		return err
	}
	inventory, err := Discover(home)
	if err != nil {
		return err
	}
	action := stringValue(task.Payload, "action")
	path := stringValue(task.Payload, "path")
	expected := stringValue(task.Payload, "expected_signature")
	for _, agent := range inventory.Agents {
		if agent.AgentType != stringValue(task.Payload, "agent_type") || !agent.SkillManagementSupported {
			continue
		}
		if localID := stringValue(task.Payload, "local_agent_id"); localID != "" && agent.LocalAgentID != localID {
			continue
		}
		if action == "restore_quarantine" || action == "restore_backup" {
			return restoreQuarantineTask(ctx, home, inventory, agent, api, store, task)
		}
		for _, skill := range agent.Skills {
			if filepath.Clean(skill.Path) != filepath.Clean(path) {
				continue
			}
			if expected == "" || skill.Signature != expected {
				return fmt.Errorf("skill_content_changed")
			}
			value := SkillObservation{
				Signature: expected, Trigger: "manual", Action: action,
				TrustedSkillID:   stringValue(task.Payload, "skill_id"),
				TrustedVersionID: stringValue(task.Payload, "version_id"),
				TrustedSignature: stringValue(task.Payload, "trusted_signature"),
				PolicyVersion:    stringValue(task.Payload, "policy_version"),
			}
			if err := applyObservedAction(ctx, home, inventory, agent, skill, policy, api, store, &value); err != nil {
				return err
			}
			if action == "submit_scan" {
				observation, err := store.Observation(skill.Path)
				if err != nil {
					return err
				}
				if observation.Signature != skill.Signature {
					observation = classifyObservation(observation, skill, nil)
				}
				observation.PendingID = value.PendingID
				if err := store.SaveObservation(skill.Path, observation); err != nil {
					return err
				}
				_ = RequestFullScan(home)
			}
			body, _ := json.Marshal(value)
			if err := store.SetState(receiptKey, string(body)); err != nil {
				return err
			}
			return reportEvent(ctx, api, store, inventory.ClientID, "skill_governance_action", agent.AgentType, skill.Name, map[string]any{
				"path": skill.Path, "signature": expected, "action": action, "source": "manual",
				"actor": task.Payload["actor"], "task_id": task.ID, "status": "completed",
				"policy_version": value.PolicyVersion, "quarantine_id": value.QuarantineID, "pending_id": value.PendingID,
			})
		}
	}
	return fmt.Errorf("skill_target_unavailable")
}

func applyObservedAction(ctx context.Context, home string, inventory Inventory, agent Agent, skill Skill, policy Policy, api API, store *Store, value *SkillObservation) error {
	release, err := AcquireMutationLock(home)
	if err != nil {
		value.ErrorCode = "skill_action_busy"
		return err
	}
	defer release()
	if err := checkObservedContent(skill); err != nil {
		value.ErrorCode = "skill_content_changed"
		return err
	}
	switch value.Action {
	case "submit_scan":
		id, err := submitObservedSkill(ctx, home, agent, skill, api, store)
		value.PendingID = id
		return err
	case "quarantine", "uninstall":
		item, err := quarantineSkill(home, store, agent.AgentType, skill.Name, skill.Path, value.Trigger, skill.Signature)
		value.QuarantineID = item.ID
		if err != nil {
			return err
		}
		if _, err := store.db.Exec(`DELETE FROM client_installs WHERE target_path=?`, skill.Path); err != nil {
			return err
		}
		if value.Action == "uninstall" {
			// Uninstall removes the active copy; the stored copy remains an
			// explicit recovery record, with its distinct disposition.
			_, err = store.db.Exec(`UPDATE client_quarantine SET status='uninstalled' WHERE id=?`, item.ID)
		}
		return err
	case "restore_trusted":
		if value.TrustedSkillID == "" || value.TrustedVersionID == "" {
			value.ErrorCode = "trusted_version_unavailable"
			return fmt.Errorf("trusted_version_unavailable")
		}
		if policy.GovernanceMode == "strict" && policy.AgentBindings[agent.AgentType] == "" {
			value.ErrorCode = "agent_binding_required"
			return fmt.Errorf("agent_binding_required")
		}
		body, err := api.DownloadPackageVersion(ctx, inventory.ClientID, value.TrustedSkillID, value.TrustedVersionID, agent.AgentType, policy.AgentBindings[agent.AgentType])
		if err != nil {
			return err
		}
		staging, err := os.MkdirTemp(RuntimeRoot(home), "restore-")
		if err != nil {
			return err
		}
		defer os.RemoveAll(staging)
		release, err := VerifyAndExtractPackage(body, policy.ReleasePublicKey, staging)
		if err != nil {
			return err
		}
		if release.ContentSignature != value.TrustedSignature || release.VersionID != value.TrustedVersionID {
			value.ErrorCode = "trusted_version_mismatch"
			return fmt.Errorf("trusted_version_mismatch")
		}
		item, err := quarantineSkill(home, store, agent.AgentType, skill.Name, skill.Path, "before_restore_trusted", skill.Signature)
		value.QuarantineID = item.ID
		if err != nil {
			return err
		}
		if err := copyDir(staging, skill.Path); err != nil {
			_ = os.RemoveAll(skill.Path)
			_ = copyDir(item.QuarantinePath, skill.Path)
			return err
		}
		return store.SaveInstall(Installation{AgentType: agent.AgentType, ManagedAgentID: policy.AgentBindings[agent.AgentType], SkillID: value.TrustedSkillID, SkillName: skill.Name, TargetPath: skill.Path, Manifest: release})

	default:
		return fmt.Errorf("invalid_governance_action")
	}
}
