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
	policy, err := api.Heartbeat(ctx, Inventory{ClientID: clientIDForHome(home), ClientVersion: Version})
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

func syncInventoryOnce(ctx context.Context, home string, api API, store *Store) error {
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
	return api.ReportInventory(ctx, inventory)
}

// RunDaemon separates liveness, task receipt, discovery and file work. Only
// the worker executes actions, while network synchronization keeps running.
func RunDaemon(ctx context.Context, home string, api API, store *Store, interval time.Duration, watcher *SkillWatcher) error {
	api = api.WithDiagnostics(store)
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	startup := map[string]any{"client_id": clientIDForHome(home), "patrol_interval_ms": interval.Milliseconds(), "version": Version, "pid": os.Getpid(), "started_at": time.Now().Format(time.RFC3339Nano)}
	if data, err := json.Marshal(startup); err == nil {
		_ = store.SetState("diagnostics:daemon", string(data))
	}
	store.LogDiagnostic("info", "daemon", "started", startup)
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
	var inventorySync sync.Mutex
	registered := false
	synchronizeInventory := func(request context.Context) error {
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
		return syncInventoryOnce(request, home, api, store)
	}
	wake := make(chan struct{}, 1)
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
				syncError(store, kind, err)
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
	periodic(10*time.Second, "scan_progress", func(request context.Context) error {
		changed, terminal, err := refreshBackgroundScans(request, api, store)
		if err != nil {
			return err
		}
		if !changed {
			return nil
		}
		if terminal {
			if err := store.SetState("patrol:force", "1"); err != nil {
				return err
			}
			signal()
		}
		return synchronizeInventory(request)
	})
	periodic(10*time.Second, "task_reports", func(request context.Context) error {
		taskErr := flushTaskResults(request, clientIDForHome(home), api, store)
		return errors.Join(taskErr, flushEvents(request, api, store))
	})
	workers.Add(1)
	go func() {
		defer workers.Done()
		var afterID int64
		backoff := time.Second
		for ctx.Err() == nil {
			started := time.Now()
			request, stop := context.WithTimeout(ctx, 40*time.Second)
			tasks, err := api.WaitTasks(request, clientIDForHome(home), afterID)
			stop()
			if err == nil {
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
		pendingDiscovery := false
		var changes <-chan struct{}
		if watcher != nil {
			changes = watcher.Changes()
		}
		for {
			if !time.Now().Before(due) {
				request, cancel := context.WithTimeout(ctx, 30*time.Second)
				err := synchronizeInventory(request)
				cancel()
				syncError(store, "inventory", err)
				if watcher != nil {
					_ = watcher.Refresh(home, store)
				}
				signal()
				due = time.Now().Add(interval)
				pendingDiscovery = false
			}
			select {
			case <-ctx.Done():
				return
			case <-changes:
				if !pendingDiscovery {
					due = time.Now().Add(750 * time.Millisecond)
					pendingDiscovery = true
				}
			case <-ticker.C:
				trigger := filepath.Join(RuntimeRoot(home), "run-now")
				if _, err := os.Stat(trigger); err == nil && os.Remove(trigger) == nil {
					_ = store.SetState("patrol:force", "1")
					due = time.Now()
				}
			}
		}
	}()
	// An interrupted task is reevaluated against current state after restart.
	_, _ = store.db.Exec(`UPDATE client_tasks SET status='pending' WHERE status='running'`)
	defer workers.Wait()
	defer cancel()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-wake:
		}
		body, ok, err := store.State("inventory")
		if err != nil || !ok {
			continue
		}
		var inventory Inventory
		if json.Unmarshal([]byte(body), &inventory) != nil {
			continue
		}
		policy := cachedPolicy(store)
		request, stop := context.WithTimeout(ctx, 3*time.Minute)
		tasks, err := store.PendingTasks()
		didWork := false
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
			syncError(store, "inventory", synchronizeInventory(request))
		}
		stop()
	}
}
