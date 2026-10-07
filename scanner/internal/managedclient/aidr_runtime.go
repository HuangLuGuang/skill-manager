package managedclient

import (
	"context"
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
	Enabled             bool                       `json:"enabled"`
	Hosts               []string                   `json:"hosts"`
	AllowUserEnrollment *bool                      `json:"allow_user_enrollment,omitempty"`
	LogSources          []string                   `json:"log_sources,omitempty"`
	Installation        string                     `json:"installation"`
	AccessMode          string                     `json:"access_mode"`
	Updates             string                     `json:"updates"`
	Retry               ReceiverRetryPolicy        `json:"retry"`
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
func AIDRMutationLock(ctx context.Context, home string) (context.Context, func(), error) {
	key := canonicalExistingPath(home)
	if ctx.Value(mutationLockContextKey{}) == key {
		return ctx, func() {}, nil
	}
	release, err := AcquireMutationLockWithTimeout(home, 5*time.Second)
	if err != nil {
		return ctx, nil, err
	}
	return context.WithValue(ctx, mutationLockContextKey{}, key), release, nil
}

// The product CLI supplies the existing installer; the managed task worker
// owns claiming, durable task results and retries, just as for other tasks.
var AIDRTaskHandler func(context.Context, string, Task) (map[string]any, error)
var AIDRRuntimeSnapshot func(string) map[string]any
var AIDRRuntimeInspect func(context.Context, string, Policy) error

// Runs inside the existing user worker, with the same cancellation lifetime.
// The callback supplies its durable policy cache; pages never drive intake.
var AIDRLogRunner func(context.Context, string, func() Policy)
