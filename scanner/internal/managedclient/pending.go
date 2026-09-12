package managedclient

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	scannerclient "skill-manager/scanner/internal/client"
	"skill-manager/scanner/internal/manifest"
	"skill-manager/scanner/internal/packager"
)

func SubmitPending(ctx context.Context, home, server, token string, store *Store, id string) (scannerclient.SubmitResult, error) {
	items, err := store.PendingItems()
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	items, err = linkPendingGroups(store, items)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	var item PendingItem
	for _, candidate := range items {
		if candidate.ID == id {
			item = candidate
			break
		}
	}
	if item.ID == "" {
		return scannerclient.SubmitResult{}, os.ErrNotExist
	}
	if item.SkillID != "" {
		return scannerclient.SubmitResult{
			SkillID:   item.SkillID,
			VersionID: item.VersionID,
			Name:      item.SkillName,
			Status:    item.Status,
			Message:   "相同内容的 Skill 已提交平台检测",
		}, nil
	}
	skillRoot, err := filepath.EvalSymlinks(item.PendingPath)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	if info, statErr := os.Stat(filepath.Join(skillRoot, "SKILL.md")); statErr != nil || info.IsDir() {
		return scannerclient.SubmitResult{}, fmt.Errorf("待处理 Skill 缺少 SKILL.md，目录可能已被移动或清空")
	}
	value, err := manifest.Build(skillRoot, DefaultManifestOptions())
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	item.Fingerprint = value.Fingerprint
	if err := store.UpdatePendingFingerprint(item.ID, item.Fingerprint); err != nil {
		return scannerclient.SubmitResult{}, err
	}
	if err := fingerprintPendingPeers(store, items, item); err != nil {
		return scannerclient.SubmitResult{}, err
	}
	tmp, err := os.MkdirTemp("", "agent-manager-pending-")
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	defer os.RemoveAll(tmp)
	zipPath := filepath.Join(tmp, "skill.zip")
	if err := packager.CreateZip(skillRoot, value, zipPath); err != nil {
		return scannerclient.SubmitResult{}, err
	}
	payload, err := json.Marshal(value)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	result, err := scannerclient.New(server, token, 2*time.Minute).SubmitZip(ctx, zipPath, scannerclient.SubmitOptions{
		UseBehavioral:   true,
		UseSkillspector: true,
		UseSandbox:      true,
		UseLLM:          true,
		ManifestJSON:    string(payload),
		ScannerVersion:  "agent-manager-client",
		HostID:          clientIDForHome(home),
	})
	if err != nil {
		return result, err
	}
	if err := store.MarkPendingSubmitted(item, result.SkillID, result.VersionID); err != nil {
		return result, err
	}
	return result, nil
}

func RefreshPending(ctx context.Context, server, token string, store *Store) ([]PendingItem, error) {
	return refreshPending(ctx, server, token, store, false, nil)
}

// RefreshPendingIncludingTerminal rechecks versions that previously reached a
// terminal result. The platform can rescan the same immutable version and an
// administrator can approve it afterwards, so a user-initiated refresh must
// not treat REJECTED or CANCELLED as permanently final.
func RefreshPendingIncludingTerminal(ctx context.Context, server, token string, store *Store) ([]PendingItem, error) {
	return refreshPending(ctx, server, token, store, true, nil)
}

// refreshPendingForReconciliation also rechecks terminal results that still
// protect an active quarantine item. An administrator can approve a previously
// rejected immutable version, and that approval must unblock automatic install
// without polling every historical terminal pending record forever.
func refreshPendingForReconciliation(ctx context.Context, server, token string, store *Store) ([]PendingItem, error) {
	quarantined, err := store.QuarantineItems()
	if err != nil {
		return nil, err
	}
	activePendingIDs := make(map[string]struct{}, len(quarantined))
	for _, item := range quarantined {
		if item.PendingID != "" {
			activePendingIDs[item.PendingID] = struct{}{}
		}
	}
	return refreshPending(ctx, server, token, store, false, activePendingIDs)
}

func refreshPending(ctx context.Context, server, token string, store *Store, includeTerminal bool, activePendingIDs map[string]struct{}) ([]PendingItem, error) {
	items, err := store.PendingItems()
	if err != nil {
		return nil, err
	}
	items, err = linkPendingGroups(store, items)
	if err != nil {
		return nil, err
	}
	api := scannerclient.New(server, token, 30*time.Second)
	results := map[string]scannerclient.SubmitResult{}
	for index := range items {
		_, activeQuarantine := activePendingIDs[items[index].ID]
		if items[index].SkillID == "" || (!includeTerminal && pendingStatusTerminal(items[index].Status) && !activeQuarantine) {
			continue
		}
		statusID := items[index].VersionID
		if statusID == "" {
			statusID = items[index].SkillID
		}
		result, ok := results[statusID]
		if !ok {
			var err error
			result, err = api.GetImport(ctx, statusID)
			if err != nil {
				if scannerclient.IsNotFound(err) || scannerclient.IsSubmissionNotOwned(err) {
					if resetErr := store.ResetPendingSubmission(items[index].ID); resetErr != nil {
						return nil, resetErr
					}
					items[index].Status = "pending"
					items[index].SkillID = ""
					items[index].VersionID = ""
					items[index].SubmittedAt = ""
					items[index].Progress = ScanProgress{}
					continue
				}
				return nil, err
			}
			results[statusID] = result
			if err := store.UpdatePendingStatus(items[index].SkillID, items[index].VersionID, result.Status); err != nil {
				return nil, err
			}
		}
		items[index].Status = result.Status
		items[index].Progress = ScanProgress{}
		if result.Status == "PENDING" {
			items[index].Progress = ScanProgress{Stage: result.ScanProgressStage, Analyzers: result.ScanProgressAnalyzers, VersionID: statusID, UpdatedAt: time.Now().UTC().Format(time.RFC3339Nano)}
		}
		progress, err := json.Marshal(items[index].Progress)
		if err != nil {
			return nil, err
		}
		if _, err := store.db.Exec(`UPDATE client_pending SET progress_json=? WHERE id=? AND COALESCE(NULLIF(version_id,''),skill_id)=?`, string(progress), items[index].ID, statusID); err != nil {
			return nil, err
		}
	}
	return items, nil
}

func ReconcileApprovedPending(ctx context.Context, home string, api API, store *Store, inventory Inventory, policy Policy) (bool, error) {
	items, err := refreshPendingForReconciliation(ctx, api.server, api.token, store)
	if err != nil {
		return false, err
	}
	changed := false
	for _, item := range items {
		if item.Status != "APPROVED" || item.SkillID == "" {
			continue
		}
		managedAgentID := strings.TrimSpace(policy.AgentBindings[item.AgentType])
		retryKey := "pending:auto-install:" + item.ID
		due, err := store.Due(retryKey, time.Minute)
		if err != nil {
			return changed, err
		}
		if !due {
			continue
		}
		if err := store.MarkSchedule(retryKey); err != nil {
			return changed, err
		}
		if err := installApprovedPending(
			ctx, home, inventory, policy, api, store,
			item, managedAgentID,
		); err != nil {
			if saveErr := store.SetState("pending:install-error:"+item.ID, err.Error()); saveErr != nil {
				return changed, saveErr
			}
			if notificationErr := store.RecordNotification(LocalNotification{
				Severity:  "warning",
				EventType: "skill_auto_install_failed",
				AgentType: item.AgentType,
				SkillName: item.SkillName,
				Title:     "Skill 自动安装失败",
				Message:   "平台已批准，但客户端自动安装失败；将稍后重试，也可以在待处理区手动安装。",
				Details:   map[string]string{"error_code": err.Error(), "path": item.OriginalPath},
			}); notificationErr != nil {
				return changed, notificationErr
			}
			continue
		}
		if err := store.RecordNotification(LocalNotification{
			Severity:  "info",
			EventType: "skill_auto_installed",
			AgentType: item.AgentType,
			SkillName: item.SkillName,
			Title:     "Skill 已自动启用",
			Message:   "已通过平台审批并自动安装可信版本。",
		}); err != nil {
			return changed, err
		}
		changed = true
	}
	return changed, nil
}

func installApprovedPending(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, item PendingItem, managedAgentID string) error {
	ctx, release, err := withMutationLock(ctx, home)
	if err != nil {
		return err
	}
	defer release()
	agent, ok := findAgent(inventory, item.AgentType)
	if !ok || item.OriginalPath == "" {
		return fmt.Errorf("skill_target_unavailable")
	}
	root := filepath.Dir(item.OriginalPath)
	allowed := false
	for _, candidate := range agentSkillRoots(agent) {
		if canonicalExistingPath(root) == canonicalExistingPath(candidate) {
			allowed = true
			break
		}
	}
	if !allowed {
		return fmt.Errorf("skill_target_unavailable")
	}
	targets := map[string]any{}
	if _, err := os.Lstat(item.OriginalPath); err == nil {
		snapshot, err := inspectInstallTarget(item.PendingPath)
		if err != nil {
			return err
		}
		if err := checkObservedContent(Skill{Path: item.OriginalPath, Signature: snapshot.signature}); err != nil {
			return err
		}
		targets[item.OriginalPath] = snapshot.signature
	} else if !os.IsNotExist(err) {
		return err
	}
	local := inventory
	local.Agents = append([]Agent(nil), inventory.Agents...)
	for index := range local.Agents {
		if local.Agents[index].AgentType == item.AgentType {
			local.Agents[index].SkillsPath = root
		}
	}
	return installApprovedSkillVersion(ctx, home, local, policy, api, store, item.AgentType, managedAgentID, item.SkillID, item.VersionID, false,
		map[string]any{"expected_root": root, "expected_path": item.OriginalPath, "expected_targets": targets})
}

func fingerprintPendingPeers(store *Store, items []PendingItem, submitted PendingItem) error {
	for index := range items {
		candidate := &items[index]
		if candidate.ID == submitted.ID || candidate.Fingerprint != "" || candidate.SkillName != submitted.SkillName {
			continue
		}
		root, err := filepath.EvalSymlinks(candidate.PendingPath)
		if err != nil {
			continue
		}
		value, err := manifest.Build(root, DefaultManifestOptions())
		if err != nil {
			continue
		}
		candidate.Fingerprint = value.Fingerprint
		if err := store.UpdatePendingFingerprint(candidate.ID, candidate.Fingerprint); err != nil {
			return err
		}
	}
	return nil
}

func linkPendingGroups(store *Store, items []PendingItem) ([]PendingItem, error) {
	groups := map[string][]int{}
	for index := range items {
		if items[index].Fingerprint != "" {
			groups[items[index].Fingerprint] = append(groups[items[index].Fingerprint], index)
		}
	}
	for fingerprint, indexes := range groups {
		anchor := -1
		for _, index := range indexes {
			if items[index].SkillID == "" {
				continue
			}
			if anchor < 0 || items[index].SubmittedAt > items[anchor].SubmittedAt {
				anchor = index
			}
		}
		if anchor < 0 {
			continue
		}
		source := items[anchor]
		if err := store.LinkPendingGroup(fingerprint, source.Status, source.SkillID, source.VersionID, source.SubmittedAt); err != nil {
			return nil, err
		}
		for _, index := range indexes {
			items[index].Status = source.Status
			items[index].SkillID = source.SkillID
			items[index].VersionID = source.VersionID
			items[index].SubmittedAt = source.SubmittedAt
		}
	}
	return items, nil
}

func pendingStatusTerminal(status string) bool {
	switch status {
	case "APPROVED", "REJECTED", "CANCELLED":
		return true
	default:
		return false
	}
}

func clientIDForHome(home string) string {
	hostname, _ := os.Hostname()
	return DeviceID(hostname, home)
}

// refreshBackgroundScans runs independently of the desktop and file worker.
func refreshBackgroundScans(ctx context.Context, api API, store *Store) (bool, bool, error) {
	before, err := store.PendingItems()
	if err != nil {
		return false, false, err
	}
	active := false
	statuses := map[string]string{}
	for _, item := range before {
		statuses[item.ID] = item.Status
		if item.SkillID != "" && !pendingStatusTerminal(item.Status) {
			active = true
		}
	}
	if !active {
		return false, false, nil
	}
	after, err := RefreshPending(ctx, api.server, api.token, store)
	if err != nil {
		return false, false, err
	}
	previous, err := json.Marshal(before)
	if err != nil {
		return false, false, err
	}
	current, err := json.Marshal(after)
	if err != nil {
		return false, false, err
	}
	transition := false
	for _, item := range after {
		if statuses[item.ID] != item.Status {
			transition = true
		}
	}
	return string(previous) != string(current), transition, nil
}
