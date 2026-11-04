package managedclient

import (
	"context"
	"encoding/json"
	"errors"
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
	return submitPendingRequested(ctx, home, server, token, store, id, false)
}

func submitPendingRequested(ctx context.Context, home, server, token string, store *Store, id string, retryTerminal bool) (scannerclient.SubmitResult, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	release, err := submissionLock(ctx, home, "pending:"+id)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	defer release()
	return submitPendingLocked(ctx, home, server, token, store, id, retryTerminal)
}

func submitPendingLocked(ctx context.Context, home, server, token string, store *Store, id string, retryTerminal bool) (scannerclient.SubmitResult, error) {
	if retryTerminal {
		item, err := store.PendingItem(id)
		if err != nil {
			return scannerclient.SubmitResult{}, err
		}
		if pendingStatusTerminal(item.Status) {
			if err := store.resetPendingForRescan(id); err != nil {
				return scannerclient.SubmitResult{}, err
			}
		}
	}
	forceRescan, _, err := store.State("pending:force-rescan:" + id)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	return submitPending(ctx, home, server, token, store, id, forceRescan == "1")
}

func submitPending(ctx context.Context, home, server, token string, store *Store, id string, forceRescan bool) (scannerclient.SubmitResult, error) {
	items, err := store.PendingItems()
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	if !forceRescan {
		items, err = linkPendingGroups(store, items)
		if err != nil {
			return scannerclient.SubmitResult{}, err
		}
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
		if forceRescan {
			if err := store.SetState("pending:force-rescan:"+id, ""); err != nil {
				return scannerclient.SubmitResult{}, err
			}
		}
		return scannerclient.SubmitResult{
			AlreadySubmitted: true,
			SkillID:          item.SkillID,
			VersionID:        item.VersionID,
			VersionNo:        item.VersionNo,
			SourceVersion:    item.SourceVersion,
			Name:             item.SkillName,
			Status:           item.Status,
			Message:          "相同内容的 Skill 已提交平台检测",
		}, nil
	}
	_, releaseFiles, err := withFileLocks(ctx, home, item.PendingPath)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	defer releaseFiles()
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
	tmp, err := os.MkdirTemp("", "agent-manager-pending-")
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	defer os.RemoveAll(tmp)
	zipPath := filepath.Join(tmp, "skill.zip")
	if err := packager.CreateZip(skillRoot, value, zipPath); err != nil {
		return scannerclient.SubmitResult{}, err
	}
	// The platform rebuilds file hashes from the ZIP and checks this fingerprint.
	// Keep the multipart field small even for Skills with many template files.
	releaseFiles()
	if err := fingerprintPendingPeers(home, store, items, item); err != nil {
		return scannerclient.SubmitResult{}, err
	}
	releaseUpload, err := submissionLock(ctx, home, "content:"+value.Fingerprint)
	if err != nil {
		return scannerclient.SubmitResult{}, err
	}
	defer releaseUpload()
	// Another foreground/background submission may have completed while waiting.
	peers, e := store.PendingItems()
	if e != nil {
		return scannerclient.SubmitResult{}, e
	}
	if !forceRescan {
		peers, e = linkPendingGroups(store, peers)
		if e != nil {
			return scannerclient.SubmitResult{}, e
		}
	}
	for _, peer := range peers {
		if peer.ID == id && peer.SkillID != "" {
			if forceRescan {
				if err := store.SetState("pending:force-rescan:"+id, ""); err != nil {
					return scannerclient.SubmitResult{}, err
				}
			}
			return scannerclient.SubmitResult{AlreadySubmitted: true, SkillID: peer.SkillID, VersionID: peer.VersionID, Status: peer.Status}, nil
		}
	}
	submissionManifest := value
	submissionManifest.Files = nil
	submissionManifest.Root = ""
	payload, err := json.Marshal(submissionManifest)
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
		ForceRescan:     forceRescan,
	})
	if err != nil {
		return result, err
	}
	if err := store.MarkPendingSubmitted(item, result.SkillID, result.VersionID); err != nil {
		return result, err
	}
	if err := store.UpdatePendingVersionMetadata(result.SkillID, result.VersionID, result.VersionNo, result.SourceVersion); err != nil {
		return result, err
	}
	if forceRescan {
		if err := store.SetState("pending:force-rescan:"+id, ""); err != nil {
			return result, err
		}
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
		items[index].VersionNo = result.VersionNo
		items[index].SourceVersion = result.SourceVersion
		if err := store.UpdatePendingVersionMetadata(items[index].SkillID, items[index].VersionID, result.VersionNo, result.SourceVersion); err != nil {
			return nil, err
		}
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

func pendingOriginalPath(item PendingItem, agent Agent) string {
	if item.OriginalPath != "" {
		return item.OriginalPath
	}
	if item.Reason != "legacy_pending" || !validInstallComponent(item.SkillName) {
		return ""
	}
	roots := map[string]string{}
	for _, root := range agentSkillRoots(agent) {
		if filepath.IsAbs(root) {
			roots[canonicalExistingPath(root)] = root
		}
	}
	if len(roots) == 1 {
		for _, root := range roots {
			return filepath.Join(root, item.SkillName)
		}
	}
	return ""
}

func installApprovedPending(ctx context.Context, home string, inventory Inventory, policy Policy, api API, store *Store, item PendingItem, managedAgentID string) error {
	agent, ok := findAgent(inventory, item.AgentType)
	if !ok {
		return fmt.Errorf("skill_target_unavailable")
	}
	if item.OriginalPath == "" {
		item.OriginalPath = pendingOriginalPath(item, agent)
		if item.OriginalPath != "" {
			if _, err := store.db.Exec(`UPDATE client_pending SET original_path=? WHERE id=? AND original_path=''`, item.OriginalPath, item.ID); err != nil {
				return err
			}
		}
	}
	if item.OriginalPath == "" {
		return fmt.Errorf("skill_target_unavailable")
	}
	ctx, release, err := withFileLocks(ctx, home, item.OriginalPath, filepath.Join(ManagedSkillsRoot(home), item.SkillID), item.PendingPath)
	if err != nil {
		return err
	}
	defer release()
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
	var prepared *preparedInstallPackage
	if item.Reason == "quarantine_rescan" {
		var cleanup func()
		var err error
		prepared, cleanup, err = prepareApprovedLocalCopy(ctx, home, api, inventory.ClientID, agent, managedAgentID, item)
		if err != nil {
			return err
		}
		defer cleanup()
	}
	return installApprovedSkillVersionWithPackage(ctx, home, local, policy, api, store, item.AgentType, managedAgentID, item.SkillID, item.VersionID, false,
		[]map[string]any{{"expected_root": root, "expected_path": item.OriginalPath, "expected_targets": targets}}, prepared, &item)
}

// Only missing or mismatched local content falls back to the signed package.
// Transport and authorization failures leave the recovery pending.
func prepareApprovedLocalCopy(ctx context.Context, home string, api API, clientID string, agent Agent, managedAgentID string, item PendingItem) (*preparedInstallPackage, func(), error) {
	noop := func() {}
	if !validInstallComponent(item.SkillName) || item.VersionID == "" {
		return nil, noop, fmt.Errorf("recovery_verdict_unavailable")
	}
	snapshot, err := inspectInstallTarget(item.PendingPath)
	if os.IsNotExist(err) {
		return nil, noop, nil
	}
	if err != nil {
		return nil, noop, err
	}
	if snapshot.signature == "" {
		return nil, noop, nil
	}
	agent.Skills = []Skill{{Name: item.SkillName, Path: item.OriginalPath, Signature: snapshot.signature, SkillID: item.SkillID, VersionID: item.VersionID}}
	items, err := api.Compare(ctx, Inventory{ClientID: clientID, Agents: []Agent{agent}}, map[string]string{agent.AgentType: managedAgentID})
	if err != nil {
		return nil, noop, err
	}
	var verdict *CompareItem
	for i := range items {
		candidate := &items[i]
		if candidate.AgentType == item.AgentType && candidate.LocalPath == item.OriginalPath && candidate.LocalSignature == snapshot.signature {
			verdict = candidate
			break
		}
	}
	if verdict == nil {
		return nil, noop, fmt.Errorf("recovery_verdict_unavailable")
	}
	if verdict.Reason == "signature_mismatch" || (verdict.Certified && verdict.VersionID != item.VersionID) {
		return nil, noop, nil
	}
	if !verdict.Certified || !verdict.Allowed || verdict.Malicious || verdict.Rejected || verdict.SkillID != item.SkillID || verdict.VersionID != item.VersionID || verdict.ExpectedSignature != snapshot.signature {
		return nil, noop, fmt.Errorf("recovery_not_certified")
	}
	staging, err := newInstallStaging(home)
	if err != nil {
		return nil, noop, err
	}
	cleanup := func() { _ = os.RemoveAll(staging) }
	root := filepath.Join(staging, "release")
	err = copyObservedSnapshot(Skill{Path: item.PendingPath, Signature: snapshot.signature}, root)
	var contents manifest.Manifest
	if err == nil {
		contents, err = manifest.Build(root, DefaultManifestOptions())
		if err == nil && manifest.ContentSignature(contents.Files) != snapshot.signature {
			err = fmt.Errorf("skill_content_changed")
		}
	}
	if err != nil {
		cleanup()
		if os.IsNotExist(err) || err.Error() == "skill_content_changed" {
			return nil, noop, nil
		}
		return nil, noop, err
	}
	files := make([]releaseFile, 0, len(contents.Files))
	for _, file := range contents.Files {
		files = append(files, releaseFile{Path: file.Path, Size: file.Size, SHA256: file.SHA256})
	}
	return &preparedInstallPackage{root: root, manifest: releaseManifest{
		Version: 1, Files: files,
		SkillID: item.SkillID, VersionID: item.VersionID, VersionNo: item.VersionNo, SourceVersion: item.SourceVersion,
		Name: item.SkillName, ContentSignature: snapshot.signature, ContentFingerprint: item.Fingerprint,
	}}, cleanup, nil
}

func fingerprintPendingPeers(home string, store *Store, items []PendingItem, submitted PendingItem) error {
	for index := range items {
		candidate := &items[index]
		if candidate.ID == submitted.ID || candidate.Fingerprint != "" || candidate.SkillName != submitted.SkillName {
			continue
		}
		release, err := tryFileLocks(home, fileLockPaths([]string{candidate.PendingPath}))
		if err != nil {
			if errors.Is(err, ErrSkillActionBusy) {
				continue
			}
			return err
		}
		root, err := filepath.EvalSymlinks(candidate.PendingPath)
		if err != nil {
			release()
			continue
		}
		value, err := manifest.Build(root, DefaultManifestOptions())
		release()
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
		if err := store.LinkPendingGroup(fingerprint, source.Status, source.SkillID, source.VersionID, source.VersionNo, source.SourceVersion, source.SubmittedAt); err != nil {
			return nil, err
		}
		for _, index := range indexes {
			items[index].Status = source.Status
			items[index].SkillID = source.SkillID
			items[index].VersionID = source.VersionID
			items[index].VersionNo = source.VersionNo
			items[index].SourceVersion = source.SourceVersion
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

// flushObservedSubmissions retries snapshots created by the local-first
// watcher. The snapshot and pending row survive process restarts; only this
// background sync performs the platform upload.
func flushObservedSubmissions(ctx context.Context, home string, api API, store *Store) (bool, error) {
	items, err := store.PendingItems()
	if err != nil {
		return false, err
	}
	changed := false
	for _, item := range items {
		if item.Reason != "observed_scan" || item.SkillID != "" || pendingStatusTerminal(item.Status) {
			continue
		}
		if _, err := SubmitPending(ctx, home, api.server, api.token, store, item.ID); err != nil {
			return changed, err
		}
		changed = true
	}
	return changed, nil
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
