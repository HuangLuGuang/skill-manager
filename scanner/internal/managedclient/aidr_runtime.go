package managedclient

import (
	"context"
	"errors"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/catalog"
	"time"
)

type ReceiverRetryPolicy struct {
	Mode               string `json:"mode"`
	Retries            int    `json:"retries"`
	MaxIntervalSeconds int    `json:"max_interval_seconds"`
}
type RuntimeGovernancePolicy struct {
	Modes               *RuntimeProtectionModes    `json:"modes,omitempty"`
	Channels            *RuntimeCollectionChannels `json:"channels,omitempty"`
	SystemTargets       *SystemCollectionTargets   `json:"system_targets,omitempty"`
	Enabled             bool                       `json:"enabled"`
	Hosts               []string                   `json:"hosts"`
	AllowUserEnrollment *bool                      `json:"allow_user_enrollment,omitempty"`
	LogSources          []string                   `json:"log_sources,omitempty"`
	Installation        string                     `json:"installation"`
	AccessMode          string                     `json:"access_mode"`
	Updates             string                     `json:"updates"`
	Retry               ReceiverRetryPolicy        `json:"retry"`
}

type SystemCollectionTargets struct {
	SelectionMode string   `json:"selection_mode"`
	Products      []string `json:"products"`
}

type RuntimeProtectionModes struct {
	Hooks  string `json:"hooks"`
	System string `json:"system"`
}

// Absence is an older Hook-only policy, not permission to start new channels.
type RuntimeCollectionChannels struct {
	Logs   bool `json:"logs"`
	Hooks  bool `json:"hooks"`
	System bool `json:"system"`
}

func (p RuntimeGovernancePolicy) CollectLogs() bool {
	return p.Enabled && p.Channels != nil && p.Channels.Logs
}

func (p RuntimeGovernancePolicy) CollectHooks() bool {
	return p.Enabled && (p.Channels == nil || p.Channels.Hooks)
}

func (p RuntimeGovernancePolicy) Valid() bool {
	if p.SystemTargets != nil {
		if p.SystemTargets.SelectionMode != "client" && p.SystemTargets.SelectionMode != "platform" {
			return false
		}
		seen := map[string]bool{}
		for _, product := range p.SystemTargets.Products {
			if (product != "codex" && product != "claude" && product != "workbuddy" && product != "custom") || seen[product] {
				return false
			}
			seen[product] = true
		}
	}
	if p.Modes != nil && ((p.Modes.Hooks != "" && p.Modes.Hooks != "audit" && p.Modes.Hooks != "intercept") || (p.Modes.System != "" && p.Modes.System != "audit" && p.Modes.System != "intercept")) {
		return false
	}
	if len(p.Hosts) > 32 || len(p.LogSources) > 32 || (p.LogSources != nil && len(p.LogSources) == 0) || (p.Installation != "manual" && p.Installation != "automatic") || (p.AccessMode != "ordinary" && p.AccessMode != "managed") || (p.Updates != "manual" && p.Updates != "automatic") {
		return false
	}
	seen := map[string]bool{}
	for _, h := range p.Hosts {
		product, _ := catalog.Get(h)
		if !catalog.Hook(h) || seen[h] || (p.AccessMode == "managed" && !product.Managed) {
			return false
		}
		seen[h] = true
	}
	seen = map[string]bool{}
	for _, source := range p.LogSources {
		if !catalog.Log(source) || seen[source] {
			return false
		}
		seen[source] = true
	}
	r := p.Retry
	return (r.Mode == "none" || r.Mode == "fixed" || r.Mode == "continuous") && r.Retries >= 0 && r.Retries <= 20 && r.MaxIntervalSeconds >= 10 && r.MaxIntervalSeconds <= 3600
}

// The same lock and context are used by policy reconciliation and individual
// installer actions, so nested actions don't release the transaction's lock.
type aidrMutationLockContextKey struct{}

func AIDRMutationLock(ctx context.Context, home string) (context.Context, func(), error) {
	key := canonicalExistingPath(home)
	if ctx.Value(aidrMutationLockContextKey{}) == key {
		return ctx, func() {}, nil
	}
	wait, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	for {
		if err := ctx.Err(); err != nil {
			return ctx, nil, err
		}
		release, err := acquireClientLock(home, "aidr-mutation.lock")
		if err == nil {
			return context.WithValue(ctx, aidrMutationLockContextKey{}, key), release, nil
		}
		if !errors.Is(err, ErrAlreadyRunning) {
			return ctx, nil, err
		}
		select {
		case <-wait.Done():
			if ctx.Err() != nil {
				return ctx, nil, ctx.Err()
			}
			return ctx, nil, &fileLockConflict{Resource: filepath.Join(home, ".agent-manager", "aidr-mutation.lock"), Mode: "exclusive"}
		case <-time.After(25 * time.Millisecond):
		}
	}
}

// The product CLI supplies the existing installer; the managed task worker
// owns claiming, durable task results and retries, just as for other tasks.
var AIDRTaskHandler func(context.Context, string, Task) (map[string]any, error)
var AIDRRuntimeSnapshot func(string) map[string]any
var AIDRRuntimeInspect func(context.Context, string, Policy) error

// Runs inside the existing user worker, with the same cancellation lifetime.
// The callback supplies its durable policy cache; pages never drive intake.
var AIDRLogRunner func(context.Context, string, func() Policy)

// Runs the shared Hook receiver inside the user daemon, independent of the UI.
var AIDRHookRunner func(context.Context, string)

// A configured receiver must answer local IPC before an upgraded worker is ready.
var AIDRHookReady func(context.Context, string) bool

// Prepare installed bridges and bound their wait across a planned worker switch.
var AIDRPrepareServiceUpgrade func(string) (func(), error)
