package managedclient

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"time"
)

type BackupRestoreResult struct {
	Tasks  []Task   `json:"tasks"`
	Errors []string `json:"errors"`
}

func RequestBackupRestore(ctx context.Context, home, name, requestID string, api API, store *Store) (BackupRestoreResult, error) {
	result := BackupRestoreResult{Tasks: []Task{}, Errors: []string{}}
	if requestID == "" {
		return result, fmt.Errorf("backup_request_id_required")
	}
	_, exists, err := store.State("backup-restore-request:" + requestID)
	if err != nil {
		return result, err
	}
	paths := []string{filepath.Join(BackupsRoot(home), name)}
	if !exists {
		plan, err := PlanBackupRestore(home, name)
		if err != nil {
			return result, err
		}
		for _, item := range plan {
			paths = append(paths, item.Source, item.Target)
		}
	}
	_, release, err := withFileLocks(ctx, home, paths...)
	if err != nil {
		return result, err
	}
	defer func() {
		if release != nil {
			release()
		}
	}()
	requests, err := prepareBackupRestoreRequests(home, name, requestID, store)
	if err != nil {
		return result, err
	}
	inventory, err := Discover(home)
	if err != nil {
		return result, err
	}
	if err := store.EnrichInventory(&inventory); err != nil {
		return result, err
	}
	release()
	release = nil
	if err := api.ReportInventory(ctx, inventory); err != nil {
		return result, err
	}
	for _, request := range requests {
		task, err := api.RequestSkillAction(ctx, inventory.ClientID, request)
		if err != nil {
			result.Errors = append(result.Errors, request.Path+": "+err.Error())
			continue
		}
		result.Tasks = append(result.Tasks, task)
	}
	if len(result.Tasks) > 0 {
		_ = RequestFullScan(home)
	}
	return result, nil
}

// Resource locks must be held while capturing the batch. Retries reuse the
// original target fingerprints even after a previously accepted task completes.
func prepareBackupRestoreRequests(home, name, requestID string, store *Store) ([]SkillActionRequest, error) {
	key := "backup-restore-request:" + requestID
	var batch struct {
		Name     string               `json:"name"`
		Requests []SkillActionRequest `json:"requests"`
	}
	raw, exists, err := store.State(key)
	if err != nil {
		return nil, err
	}
	if exists {
		if err := json.Unmarshal([]byte(raw), &batch); err != nil {
			return nil, err
		}
		if batch.Name != name {
			return nil, fmt.Errorf("backup_request_conflict")
		}
		return batch.Requests, nil
	}
	plan, err := PlanBackupRestore(home, name)
	if err != nil {
		return nil, err
	}
	if len(plan) == 0 {
		return nil, fmt.Errorf("backup_content_unavailable")
	}
	tx, err := store.db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	now := time.Now().UTC().Format(time.RFC3339Nano)
	batch.Name = name
	for _, item := range plan {
		id := "backup-" + pendingID(item.Source+":"+item.Target+":"+item.Signature)
		_, err := tx.Exec(`INSERT INTO client_quarantine(id,agent_type,skill_name,original_path,quarantine_path,reason,status,created_at)
		 VALUES(?,?,?,?,?,'backup','backed_up',?) ON CONFLICT(id) DO UPDATE SET status='backed_up', restored_at=NULL`,
			id, item.AgentType, item.SkillName, item.Target, item.Source, now)
		if err != nil {
			return nil, err
		}
		batch.Requests = append(batch.Requests, SkillActionRequest{RequestID: requestID + ":" + id, Action: "restore_backup", AgentType: item.AgentType,
			Path: item.Target, ExpectedSignature: item.Signature, ExpectedTargetSignature: item.TargetSignature, QuarantineID: id})
	}
	encoded, err := json.Marshal(batch)
	if err != nil {
		return nil, err
	}
	if _, err := tx.Exec(`INSERT INTO client_state(key,value,updated_at) VALUES(?,?,?)`, key, string(encoded), now); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return batch.Requests, nil
}
