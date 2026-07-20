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
	item, err := store.PendingItem(id)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	skillRoot, err := filepath.EvalSymlinks(item.PendingPath)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	value, err := manifest.Build(skillRoot, DefaultManifestOptions())
	if err != nil {
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
	api := scannerclient.New(server, token, 30*time.Second)
	for index := range items {
		if items[index].SkillID == "" || items[index].Status == "APPROVED" || items[index].Status == "REJECTED" {
			continue
		}
		result, err := api.GetImport(ctx, items[index].SkillID)
		if err != nil {
			return nil, err
		}
		if err := store.UpdatePendingStatus(items[index].ID, result.Status); err != nil {
			return nil, err
		}
		items[index].Status = result.Status
	}
	return items, nil
}

func clientIDForHome(home string) string {
	inventory, err := Discover(home)
	if err != nil {
		return ""
	}
	return inventory.ClientID
}
