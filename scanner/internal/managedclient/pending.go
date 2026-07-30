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
	return refreshPending(ctx, server, token, store, false)
}

// RefreshPendingIncludingTerminal rechecks versions that previously reached a
// terminal result. The platform can rescan the same immutable version and an
// administrator can approve it afterwards, so a user-initiated refresh must
// not treat REJECTED or CANCELLED as permanently final.
func RefreshPendingIncludingTerminal(ctx context.Context, server, token string, store *Store) ([]PendingItem, error) {
	return refreshPending(ctx, server, token, store, true)
}

func refreshPending(ctx context.Context, server, token string, store *Store, includeTerminal bool) ([]PendingItem, error) {
	items, err := store.PendingItems()
	if err != nil {
		return nil, err
	}
	items, err = linkPendingGroups(store, items)
	if err != nil {
		return nil, err
	}
	api := scannerclient.New(server, token, 30*time.Second)
	statuses := map[string]string{}
	for index := range items {
		if items[index].SkillID == "" || (!includeTerminal && pendingStatusTerminal(items[index].Status)) {
			continue
		}
		statusID := items[index].VersionID
		if statusID == "" {
			statusID = items[index].SkillID
		}
		status, ok := statuses[statusID]
		if !ok {
			result, err := api.GetImport(ctx, statusID)
			if err != nil {
				return nil, err
			}
			status = result.Status
			statuses[statusID] = status
			if err := store.UpdatePendingStatus(items[index].SkillID, items[index].VersionID, status); err != nil {
				return nil, err
			}
		}
		items[index].Status = status
	}
	return items, nil
}

func ReconcileApprovedPending(ctx context.Context, home string, api API, store *Store, inventory Inventory, policy Policy) (bool, error) {
	items, err := RefreshPending(ctx, api.server, api.token, store)
	if err != nil {
		return false, err
	}
	changed := false
	for _, item := range items {
		if item.Status != "APPROVED" || item.SkillID == "" {
			continue
		}
		managedAgentID := strings.TrimSpace(policy.AgentBindings[item.AgentType])
		if policy.GovernanceMode == "strict" && managedAgentID == "" {
			continue
		}
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
		if err := InstallApprovedSkillVersion(
			ctx, home, inventory, policy, api, store,
			item.AgentType, managedAgentID, item.SkillID, item.VersionID,
		); err != nil {
			if notificationErr := store.RecordNotification(LocalNotification{
				Severity:  "warning",
				EventType: "skill_auto_install_failed",
				AgentType: item.AgentType,
				SkillName: item.SkillName,
				Title:     "Skill 自动安装失败",
				Message:   "平台已批准，但客户端自动安装失败；将稍后重试，也可以在待处理区手动安装。",
			}); notificationErr != nil {
				return changed, notificationErr
			}
			continue
		}
		if err := store.RemovePending(item.ID); err != nil {
			return changed, err
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
