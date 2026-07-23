package managedclient

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
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
	items, err = synchronizePendingGroups(store, items)
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
			SkillID: item.SkillID,
			Name:    item.SkillName,
			Status:  item.Status,
			Message: "相同内容的 Skill 已提交平台检测",
		}, nil
	}
	skillRoot, err := filepath.EvalSymlinks(item.PendingPath)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	value, err := manifest.Build(skillRoot, DefaultManifestOptions())
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	item.Fingerprint = value.Fingerprint
	if err := store.UpdatePendingFingerprint(item.ID, item.Fingerprint); err != nil {
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
		NoCache:         true,
		ManifestJSON:    string(payload),
		ScannerVersion:  "agent-manager-client",
		HostID:          clientIDForHome(home),
	})
	if err != nil {
		return result, err
	}
	if err := store.MarkPendingSubmitted(item, result.SkillID); err != nil {
		return result, err
	}
	return result, nil
}

func RefreshPending(ctx context.Context, server, token string, store *Store) ([]PendingItem, error) {
	items, err := store.PendingItems()
	if err != nil {
		return nil, err
	}
	items, err = synchronizePendingGroups(store, items)
	if err != nil {
		return nil, err
	}
	api := scannerclient.New(server, token, 30*time.Second)
	statuses := map[string]string{}
	for index := range items {
		if items[index].SkillID == "" || pendingStatusTerminal(items[index].Status) {
			continue
		}
		status, ok := statuses[items[index].SkillID]
		if !ok {
			result, err := api.GetImport(ctx, items[index].SkillID)
			if err != nil {
				return nil, err
			}
			status = result.Status
			statuses[items[index].SkillID] = status
			if err := store.UpdatePendingStatusBySkillID(items[index].SkillID, status); err != nil {
				return nil, err
			}
		}
		items[index].Status = status
	}
	return items, nil
}

func synchronizePendingGroups(store *Store, items []PendingItem) ([]PendingItem, error) {
	groups := map[string][]int{}
	for index := range items {
		if items[index].Fingerprint == "" {
			root, err := filepath.EvalSymlinks(items[index].PendingPath)
			if err != nil {
				continue
			}
			value, err := manifest.Build(root, DefaultManifestOptions())
			if err != nil {
				continue
			}
			items[index].Fingerprint = value.Fingerprint
			if err := store.SavePending(items[index]); err != nil {
				return nil, err
			}
		}
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
		if err := store.LinkPendingGroup(fingerprint, source.Status, source.SkillID, source.SubmittedAt); err != nil {
			return nil, err
		}
		for _, index := range indexes {
			items[index].Status = source.Status
			items[index].SkillID = source.SkillID
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
	inventory, err := Discover(home)
	if err != nil {
		return ""
	}
	return inventory.ClientID
}
