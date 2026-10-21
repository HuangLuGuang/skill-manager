package managedclient

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

func cachedPolicy(store *Store) Policy {
	var policy Policy
	if body, ok, err := store.State("policy"); err == nil && ok {
		if json.Unmarshal([]byte(body), &policy) == nil {
			return policy
		}
	}
	return Policy{Mode: "audit", Classification: DefaultClassificationPolicy()}
}

func inventoryRevision(inventory Inventory) string {
	values := []string{}
	for _, agent := range inventory.Agents {
		values = append(values, agent.AgentType, agent.SkillsPath)
		for _, skill := range agent.Skills {
			values = append(values, skill.Path, skill.Signature, skill.Error)
		}
	}
	body, _ := json.Marshal(values)
	return fmt.Sprintf("%x", sha256.Sum256(body))
}

func syncError(store *Store, kind string, err error) {
	logSyncTransition(store, kind, err)
	detail := ""
	if err != nil {
		detail = err.Error()
	}
	_ = store.SetState("sync:"+kind+":error", detail)
	if err == nil {
		_ = store.SetState("sync:"+kind+":success", time.Now().UTC().Format(time.RFC3339Nano))
	}
}

func heartbeatOnce(ctx context.Context, home string, api API, store *Store) error {
	policy, err := api.Heartbeat(ctx, Inventory{ClientID: clientIDForHome(home), ClientVersion: Version}, home)
	if err != nil {
		return err
	}
	if policy.Mode == "" {
		policy, err = api.Policy(ctx, clientIDForHome(home))
		if err != nil {
			return err
		}
	}
	body, err := json.Marshal(policy)
	if err != nil {
		return err
	}
	previous, _, _ := store.State("policy")
	if err := store.SetState("policy", string(body)); err != nil {
		return err
	}
	if previous != string(body) {
		_ = RequestFullScan(home)
	}
	return nil
}

func flushTaskResults(ctx context.Context, clientID string, api API, store *Store) error {
	// Persisted terminal results are retried even when an earlier POST was
	// lost. The platform task may otherwise remain running indefinitely.
	history, err := store.UnreportedTasks()
	if err != nil {
		return err
	}
	var firstError error
	for _, task := range history {
		key := fmt.Sprintf("task:reported:%d", task.ID)
		if err := api.ReportExecutedTask(ctx, clientID, task.Task, task.Status, task.Error); err != nil {
			if firstError == nil {
				firstError = err
			}
			continue
		}
		if err := store.SetState(key, task.Status); err != nil {
			return err
		}
	}
	return firstError
}

func syncInventoryOnce(ctx context.Context, home string, api API, store *Store, localReady func()) error {
	previousBody, previousExists, err := store.State("inventory")
	if err != nil {
		return err
	}
	inventory, err := Discover(home)
	if err != nil {
		return err
	}
	if err = store.EnrichInventory(&inventory); err != nil {
		return err
	}
	if err = store.SaveInventory(inventory); err != nil {
		return err
	}
	var previous Inventory
	if !previousExists || json.Unmarshal([]byte(previousBody), &previous) != nil || inventoryRevision(previous) != inventoryRevision(inventory) {
		if err := store.EmitUIStateEvent(home, "local_state_changed", map[string]any{"source": "inventory"}); err != nil {
			return err
		}
	}
	if localReady != nil {
		localReady()
	}
	return api.ReportInventory(ctx, inventory)
}

func applyPlatformScanEvents(store *Store, events []PlatformScanEvent, currentRevision int64) (int64, bool, error) {
	sort.SliceStable(events, func(left, right int) bool { return events[left].Revision < events[right].Revision })
	changed := false
	for _, event := range events {
		if event.Revision <= currentRevision {
			continue
		}
		if event.Status == "" || event.VersionID == "" {
			store.LogDiagnostic("info", "platform", "platform_event_ignored", map[string]any{
				"pending_id": event.PendingID, "skill_id": event.SkillID, "version_id": event.VersionID,
				"status": event.Status, "revision": event.Revision, "reason": "invalid_event",
			})
			currentRevision = event.Revision
			continue
		}
		found, previous, err := store.PendingStatus(event.SkillID, event.VersionID)
		if err != nil {
			return currentRevision, changed, err
		}
		if !found {
			store.LogDiagnostic("info", "platform", "platform_event_ignored", map[string]any{
				"pending_id": event.PendingID, "skill_id": event.SkillID, "version_id": event.VersionID,
				"status": event.Status, "revision": event.Revision, "reason": ErrPendingNotFound.Error(),
			})
			currentRevision = event.Revision
			continue
		}
		if previous == event.Status {
			currentRevision = event.Revision
			continue
		}
		if err := store.UpdatePendingStatus(event.SkillID, event.VersionID, event.Status); err != nil {
			if errors.Is(err, ErrPendingNotFound) {
				store.LogDiagnostic("info", "platform", "platform_event_ignored", map[string]any{
					"pending_id": event.PendingID, "skill_id": event.SkillID, "version_id": event.VersionID,
					"status": event.Status, "revision": event.Revision, "reason": ErrPendingNotFound.Error(),
				})
				currentRevision = event.Revision
				continue
			}
			return currentRevision, changed, err
		}
		store.LogDiagnostic("info", "platform", "platform_event_received", map[string]any{
			"pending_id": event.PendingID, "skill_id": event.SkillID, "version_id": event.VersionID,
			"status": event.Status, "revision": event.Revision,
		})
		currentRevision = event.Revision
		changed = true
	}
	return currentRevision, changed, nil
}

// RunDaemon separates liveness, task receipt, discovery and file work. Only
// the worker executes actions, while network synchronization keeps running.
func RunDaemon(ctx context.Context, home string, api API, store *Store, interval time.Duration, watcher SkillMonitor) error {
	api = api.WithDiagnostics(store)
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	startup := map[string]any{"client_id": clientIDForHome(home), "patrol_interval_ms": interval.Milliseconds(), "version": Version, "pid": os.Getpid(), "started_at": time.Now().Format(time.RFC3339Nano)}
	if data, err := json.Marshal(startup); err == nil {
		_ = store.SetState("diagnostics:daemon", string(data))
	}
	store.LogDiagnostic("info", "daemon", "started", startup)
	if err := store.ReplayLatestUIEvent(home); err != nil {
		store.LogDiagnostic("warn", "daemon", "ui_event_replay_failed", map[string]any{"error": err.Error()})
	}
	defer func() {
		startup["stopped_at"] = time.Now().Format(time.RFC3339Nano)
		if data, err := json.Marshal(startup); err == nil {
			_ = store.SetState("diagnostics:daemon", string(data))
		}
		store.LogDiagnostic("info", "daemon", "stopped", startup)
	}()
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var workers sync.WaitGroup
	defer func() { cancel(); workers.Wait() }()
	workers.Add(1)
	go func() {
		defer workers.Done()
		if err := ServeDesktop(ctx, home); err != nil {
			store.LogDiagnostic("error", "desktop", "desktop_ipc_failed", map[string]any{"error": err.Error()})
		}
	}()
	if AIDRHookRunner != nil {
		workers.Add(1)
		go func() {
			defer workers.Done()
			AIDRHookRunner(ctx, home)
		}()
	}
	if AIDRLogRunner != nil {
		workers.Add(1)
		go func() {
			defer workers.Done()
			AIDRLogRunner(ctx, home, func() Policy { return cachedPolicy(store) })
		}()
	}
	var inventorySync sync.Mutex
	registered := false
	synchronizeInventory := func(request context.Context, localReady func()) error {
		inventorySync.Lock()
		defer inventorySync.Unlock()
		if err := request.Err(); err != nil {
			return err
		}
		if !registered {
			inventory, err := Discover(home)
			if err != nil {
				return err
			}
			if err := store.EnrichInventory(&inventory); err != nil {
				return err
			}
			if err := api.Register(request, inventory); err != nil {
				return err
			}
			err = heartbeatOnce(request, home, api, store)
			syncError(store, "heartbeat", err)
			if err != nil {
				return err
			}
			registered = true
		}
		return syncInventoryOnce(request, home, api, store, localReady)
	}
	wake := make(chan struct{}, 1)
	fastChanges := make(chan []string, 64)
	refreshInventory := make(chan struct{}, 1)
	enqueueFastChanges := func(paths []string) {
		select {
		case fastChanges <- paths:
			return
		default:
		}
		// Do not turn a full fast-path queue into a synchronous full patrol.
		// Persist the coalesced paths so a restart or later drain can resume it.
		body, _, _ := store.State("watcher:pending-paths")
		var pending []string
		_ = json.Unmarshal([]byte(body), &pending)
		seen := map[string]bool{}
		for _, path := range pending {
			seen[path] = true
		}
		for _, path := range paths {
			if !seen[path] {
				pending = append(pending, path)
				seen[path] = true
			}
		}
		if encoded, err := json.Marshal(pending); err == nil {
			_ = store.SetState("watcher:pending-paths", string(encoded))
		}
		store.LogDiagnostic("warn", "watcher", "fast_action_queued", map[string]any{"reason": "event_queue_persisted", "changed_paths": len(paths)})
	}
	if body, ok, _ := store.State("watcher:pending-paths"); ok {
		var pending []string
		if json.Unmarshal([]byte(body), &pending) == nil && len(pending) > 0 {
			select {
			case fastChanges <- pending:
				_ = store.SetState("watcher:pending-paths", "[]")
			default:
			}
		}
	}
	signal := func() {
		select {
		case wake <- struct{}{}:
		default:
		}
	}
	periodic := func(period time.Duration, kind string, callback func(context.Context) error) {
		workers.Add(1)
		go func() {
			defer workers.Done()
			ticker := time.NewTicker(period)
			defer ticker.Stop()
			for {
				request, cancel := context.WithTimeout(ctx, 30*time.Second)
				err := callback(request)
				cancel()
				if kind != "events" {
					syncError(store, kind, err)
				}
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
				}
			}
		}()
	}
	heartbeatInterval := interval
	if heartbeatInterval > 10*time.Second {
		heartbeatInterval = 10 * time.Second
	}
	periodic(heartbeatInterval, "heartbeat", func(request context.Context) error { return heartbeatOnce(request, home, api, store) })
	if AIDRRuntimeInspect != nil {
		periodic(5*time.Minute, "aidr_runtime_inspect", func(request context.Context) error {
			return AIDRRuntimeInspect(request, home, cachedPolicy(store))
		})
	}
	periodic(10*time.Second, "task_reports", func(request context.Context) error {
		taskErr := flushTaskResults(request, clientIDForHome(home), api, store)
		return taskErr
	})
	workers.Add(1)
	go func() {
		defer workers.Done()
		runEventUploader(ctx, api, store)
	}()
	workers.Add(1)
	go func() {
		defer workers.Done()
		var afterID int64
		backoff := time.Second
		for ctx.Err() == nil {
			started := time.Now()
			pending, _ := store.PendingItems()
			scanIDs := make([]string, 0, len(pending))
			seenScanIDs := map[string]bool{}
			for _, item := range pending {
				if item.VersionID != "" && !seenScanIDs[item.VersionID] {
					scanIDs = append(scanIDs, item.VersionID)
					seenScanIDs[item.VersionID] = true
				}
			}
			scanRevisionValue, _, _ := store.State("platform:scan-revision")
			var scanRevision int64
			_, _ = fmt.Sscan(scanRevisionValue, &scanRevision)
			request, stop := context.WithTimeout(ctx, 40*time.Second)
			tasks, updateVersions, scanEvents, err := api.WaitTasksWithUpdatesAndScans(request, clientIDForHome(home), afterID, scanIDs, scanRevision)
			stop()
			if err == nil {
				if updateVersions.Stable != "" || updateVersions.Preview != "" {
					body, marshalErr := json.Marshal(updateVersions)
					if marshalErr != nil {
						err = marshalErr
					} else if previous, exists, stateErr := store.State("client:update-versions"); stateErr != nil {
						err = stateErr
					} else if !exists || previous != string(body) {
						err = store.SetState("client:update-versions", string(body))
					}
				}
				if err == nil {
					nextRevision, changed, applyErr := applyPlatformScanEvents(store, scanEvents, scanRevision)
					if applyErr != nil {
						store.LogDiagnostic("warn", "platform", "platform_event_apply_failed", map[string]any{"revision": scanRevision, "error": applyErr.Error()})
						err = applyErr
					} else {
						scanRevision = nextRevision
						if nextRevision > 0 {
							_ = store.SetState("platform:scan-revision", fmt.Sprintf("%d", scanRevision))
						}
						if changed {
							signal()
						}
					}
					for _, task := range tasks {
						body, marshalErr := json.Marshal(task)
						if marshalErr != nil {
							err = marshalErr
							break
						}
						_, err = store.db.Exec(`INSERT OR IGNORE INTO client_tasks(task_id,status,error,updated_at,task_json) VALUES(?,'pending','',?,?)`, task.ID, time.Now().UTC().Format(time.RFC3339Nano), string(body))
						if err != nil {
							break
						}
						if task.ID > afterID {
							afterID = task.ID
						}
					}
				}
				if len(tasks) > 0 {
					signal()
				}
			}
			syncError(store, "tasks", err)
			delay := time.Duration(0)
			if err != nil {
				delay = backoff + time.Duration(rand.Intn(500))*time.Millisecond
				backoff *= 2
				if backoff > 30*time.Second {
					backoff = 30 * time.Second
				}
			} else {
				backoff = time.Second
				if elapsed := time.Since(started); elapsed < time.Second {
					delay = time.Second - elapsed
				}
			}
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
		}
	}()

	workers.Add(1)
	go func() {
		defer workers.Done()
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		due := time.Now()
		var changes <-chan []string
		if watcher != nil {
			changes = watcher.Changes()
		}
		for {
			if !time.Now().Before(due) {
				request, cancel := context.WithTimeout(ctx, 30*time.Second)
				localSignaled := false
				err := synchronizeInventory(request, func() {
					localSignaled = true
					signal()
				})
				cancel()
				syncError(store, "inventory", err)
				if watcher != nil {
					_ = watcher.Refresh(home, store)
				}
				if !localSignaled {
					signal()
				}
				due = time.Now().Add(interval)
			}
			select {
			case <-ctx.Done():
				return
			case paths, ok := <-changes:
				if !ok {
					changes = nil
					due = time.Now()
					continue
				}
				store.LogDiagnostic("info", "watcher", "change_detected", map[string]any{
					"debounce_ms": skillWatchDebounce.Milliseconds(), "path_count": len(paths),
				})
				if len(paths) > 0 {
					enqueueFastChanges(paths)
				} else {
					due = time.Now()
				}
			case <-refreshInventory:
				due = time.Now()
			case <-ticker.C:
				workerWake := filepath.Join(RuntimeRoot(home), "worker-wake")
				if _, err := os.Stat(workerWake); err == nil && os.Remove(workerWake) == nil {
					signal()
				}
				trigger := filepath.Join(RuntimeRoot(home), "run-now")
				if _, err := os.Stat(trigger); err == nil && os.Remove(trigger) == nil {
					_ = store.SetState("patrol:force", "1")
					due = time.Now()
				}
			}
		}
	}()
	// An interrupted task is reevaluated against current state after restart.
	// Native plugin installation may have partially completed. Report that
	// uncertainty explicitly, preserving the task and queues for an explicit retry.
	if err := store.InterruptAIDRTasks(); err != nil {
		return err
	}
	_, _ = store.db.Exec(`UPDATE client_tasks SET status='pending' WHERE status='running'`)
	periodic(time.Second, "daemon_health", func(ctx context.Context) error {
		if AIDRHookReady != nil && !AIDRHookReady(ctx, home) {
			return errors.New("client_hook_not_ready")
		}
		return writeDaemonHealth(home)
	})
	for {
		var changedPaths []string
		select {
		case <-ctx.Done():
			return nil
		case <-wake:
		case changedPaths = <-fastChanges:
		}
		body, ok, err := store.State("inventory")
		if err != nil || !ok {
			store.LogDiagnostic("warn", "watcher", "fast_action_skipped", map[string]any{"reason": "inventory_snapshot_missing", "changed_paths": changedPaths})
			if len(changedPaths) > 0 {
				select {
				case refreshInventory <- struct{}{}:
				default:
				}
			}
			continue
		}
		var inventory Inventory
		if json.Unmarshal([]byte(body), &inventory) != nil {
			store.LogDiagnostic("warn", "watcher", "fast_action_skipped", map[string]any{"reason": "inventory_snapshot_missing", "changed_paths": changedPaths})
			if len(changedPaths) > 0 {
				select {
				case refreshInventory <- struct{}{}:
				default:
				}
			}
			continue
		}
		policy := cachedPolicy(store)
		request, stop := context.WithTimeout(ctx, 3*time.Minute)
		if len(changedPaths) > 0 {
			handled, affectedRoots, fastErr := fastPatrolTrustedChanges(request, home, inventory, policy, api, store, changedPaths)
			if handled && watcher != nil && len(affectedRoots) > 0 {
				watcher.SuppressRoots(affectedRoots, 2*time.Second)
			}
			syncError(store, "fast_patrol", fastErr)
			if !handled || fastErr != nil {
				select {
				case refreshInventory <- struct{}{}:
				default:
				}
			}
			stop()
			continue
		}
		tasks, err := store.PendingTasks()
		didWork := false
		if submitted, submitErr := flushObservedSubmissions(request, home, api, store); submitErr != nil {
			syncError(store, "observed_submission", submitErr)
		} else {
			didWork = didWork || submitted
		}
		if err == nil {
			for _, task := range tasks {
				if task.Status == "pending" {
					didWork = true
					err = executeTasks(request, home, inventory, policy, api, store, []Task{task.Task})
					if err != nil {
						break
					}
				}
			}
		}
		sharingChanged, sharingErr := ReconcileSharedManagedInstalls(request, home, store)
		syncError(store, "shared_installs", sharingErr)
		didWork = didWork || sharingChanged
		autoChanged, autoErr := ReconcileApprovedPending(request, home, api, store, inventory, policy)
		syncError(store, "auto_install", autoErr)
		restored, restoreErr := ReconcileCertifiedQuarantine(request, home, api, store, inventory)
		syncError(store, "auto_restore", restoreErr)
		didWork = didWork || autoChanged || restored
		if err == nil {
			policy = cachedPolicy(store)
			due, _ := store.Due("patrol:light", interval)
			force, _, _ := store.State("patrol:force")
			current := inventoryRevision(inventory)
			observed, _, _ := store.State("patrol:inventory")
			if due || force == "1" || current != observed {
				didWork = true
				fullSeconds := policy.FullScanSeconds
				if fullSeconds <= 0 {
					fullSeconds = 1800
				}
				full, _ := store.Due("patrol:full", time.Duration(fullSeconds)*time.Second)
				heartbeatError, _, _ := store.State("sync:heartbeat:error")
				err = patrol(request, home, inventory, policy, api, store, full || force == "1", heartbeatError == "")
				if err == nil {
					_ = store.MarkSchedule("patrol:light")
					_ = store.SetState("patrol:inventory", current)
					_ = store.SetState("patrol:force", "0")
					if full || force == "1" {
						_ = store.MarkSchedule("patrol:full")
					}
				}
			}
		}
		syncError(store, "worker", err)
		if didWork {
			var signalErr error
			syncError(store, "inventory", synchronizeInventory(request, func() {
				// The cached inventory is now authoritative for the completed
				// action. Wake the desktop before waiting for platform upload.
				signalErr = store.EmitUIStateEvent(home, "local_state_changed", map[string]any{"source": "worker"})
			}))
			syncError(store, "desktop_event", signalErr)
		}
		stop()
	}
}
