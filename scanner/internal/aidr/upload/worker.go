package upload

import (
	"context"
	"errors"
	"sort"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

type Root struct{ Agent, Path, File string }
type WorkerOptions struct {
	Roots             []Root
	Since             time.Time
	Interval          time.Duration
	HeartbeatInterval time.Duration
	DiscoveryInterval time.Duration
	// Observer receives codes and counts, never raw logs or credentials.
	Observer       func(localstore.Status)
	StatusObserver func(localstore.Status) error
	// Runtime collection is independent of the audit policy and upload permit.
	// False stops discovery/intake but keeps the frozen outbox uploader alive.
	IntakeEnabled func() bool
	IntakeVersion func() string
}

// Run is explicitly invoked and owns no service installation. Source discovery,
// intake and upload each have bounded work; network failures retain the outbox.
func Run(ctx context.Context, s *localstore.Store, c *Client, o WorkerOptions) error {
	if len(o.Roots) < 1 || len(o.Roots) > 2 || o.Interval < time.Second || o.Interval > time.Minute || o.HeartbeatInterval < time.Second || o.HeartbeatInterval > time.Minute || o.DiscoveryInterval < time.Second || o.DiscoveryInterval > 5*time.Minute {
		return errors.New("aidr_upload_worker_options_invalid")
	}
	if err := c.Bind(ctx, s); err != nil {
		return err
	}
	if err := s.LoadPolicy(ctx); err != nil {
		return err
	}
	c.policySupported = s.Policy().Version != "0"
	var nextPolicy time.Time
	var discovery []Discovery
	var nextHeartbeat, nextUpload time.Time
	capabilities := map[string]Capability{}
	crawlers := map[int]*localstore.Crawler{}
	for i, root := range o.Roots {
		if root.File == "" {
			crawler, err := s.NewCrawler(root.Agent, root.Path)
			if err != nil {
				return err
			}
			crawler.RescanInterval = o.DiscoveryInterval
			crawlers[i] = crawler
			defer crawler.Close()
		}
	}
	failures := 0
	ticker := time.NewTicker(o.Interval)
	defer ticker.Stop()
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		if !time.Now().Before(nextPolicy) {
			if err := c.RefreshPolicy(ctx, s); err != nil {
				return err
			}
			nextPolicy = time.Now().Add(30 * time.Second)
		}
		discovery = nil
		version := ""
		if o.IntakeVersion != nil {
			version = o.IntakeVersion()
		}
		intakeEnabled := o.IntakeEnabled == nil || o.IntakeEnabled()
		if o.IntakeEnabled != nil {
			if err := s.SetRuntimeTarget(ctx, intakeEnabled, version); err != nil {
				return err
			}
		}
		if intakeEnabled {
			for i, root := range o.Roots {
				if crawler := crawlers[i]; crawler != nil {
					progress, err := crawler.Step(ctx, 64, 10000, 300*time.Millisecond)
					if errors.Is(err, localstore.ErrCapacity) {
						progress.Status = "partial"
						progress.Reasons = []string{"aidr_store_capacity"}
					} else if err != nil {
						return err
					}
					discovery = append(discovery, Discovery{Agent: root.Agent, Status: progress.Status, Reasons: progress.Reasons, Progress: &progress})
				} else {
					discovery = append(discovery, Discovery{Agent: root.Agent, Status: "complete", Reasons: []string{}})
				}
			}
			// Reserve a separate intake slice for recent activity and historical work.
			for _, recent := range []bool{true, false} {
				for i, root := range o.Roots {
					deadline := time.Now().Add(time.Second / time.Duration(len(o.Roots)))
					var sources []agentlog.Source
					crawler := crawlers[i]
					if crawler != nil {
						var err error
						sources, err = crawler.Ready(ctx, recent, 32)
						if err != nil {
							return err
						}
					} else if recent {
						src, err := agentlog.NewSource(root.Agent, root.Path, root.File)
						if err != nil {
							return err
						}
						sources = []agentlog.Source{src}
					}
					for _, src := range sources {
						if o.IntakeEnabled != nil && !o.IntakeEnabled() {
							break
						}
						if time.Now().After(deadline) {
							break
						}
						// Time-limit parsing cooperatively; do not abort SQLite mid-transaction
						// merely because this source's scheduling slice ended.
						budget := agentlog.DefaultBudget()
						budget.Duration = time.Until(deadline)
						if budget.Duration <= 0 {
							break
						}
						checkpoint, err := s.Collect(ctx, src, budget, o.Since)
						if err != nil {
							if ctx.Err() != nil {
								return ctx.Err()
							}
							if errors.Is(err, localstore.ErrCapacity) || errors.Is(err, context.DeadlineExceeded) {
								break
							}
							return err
						}
						if crawler != nil {
							if err = crawler.ReadDone(ctx, src, checkpoint.Cursor.Offset); err != nil {
								return err
							}
						}
						if checkpoint.Cursor.AgentVersion != "" {
							state := "available"
							for _, reason := range checkpoint.Cursor.Gaps {
								if reason == "aidr_log_version_unverified" {
									state = "unverified"
								}
							}
							if checkpoint.Coverage.Status != "complete" {
								state = "unavailable"
							}
							capabilities[src.ID] = Capability{Agent: src.Agent, Version: checkpoint.Cursor.AgentVersion, Status: state, ParserStatus: agentlog.VersionSupport(src.Agent, checkpoint.Cursor.AgentVersion), ParserVersion: agentlog.ParserVersion}
						}
					}
				}
			}
		}
		if !time.Now().Before(nextUpload) {
			for batch := 0; batch < 4; batch++ {
				result, err := c.SendOne(ctx, s)
				if err != nil {
					return err
				}
				if result.Code != "" {
					if !result.Retryable {
						return errors.New(result.Code)
					}
					nextUpload = time.Now().Add(RetryDelay(failures))
					failures = min(failures+1, 6)
					break
				}
				failures = 0
				nextUpload = time.Time{}
				if !result.Uploaded {
					break
				}
			}
		}
		if !time.Now().Before(nextHeartbeat) {
			caps := summarizeCapabilities(capabilities)
			result, err := c.Heartbeat(ctx, s, caps, discovery)
			if err != nil {
				return err
			}
			if result.Code != "" && !result.Retryable {
				return errors.New(result.Code)
			}
			nextHeartbeat = time.Now().Add(o.HeartbeatInterval)
		}
		if o.Observer != nil || o.StatusObserver != nil {
			status, err := s.Status(ctx)
			if err != nil {
				return err
			}
			if o.Observer != nil {
				o.Observer(status)
			}
			if o.StatusObserver != nil {
				if err := o.StatusObserver(status); err != nil {
					return err
				}
			}
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}

func summarizeCapabilities(sources map[string]Capability) []Capability {
	unique := map[string]Capability{}
	rank := map[string]int{"available": 0, "unverified": 1, "unavailable": 2}
	for _, capability := range sources {
		key := capability.Agent + ":" + capability.Version
		if old, ok := unique[key]; !ok || rank[capability.Status] > rank[old.Status] {
			unique[key] = capability
		}
	}
	keys := make([]string, 0, len(unique))
	for key := range unique {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	caps := make([]Capability, 0, min(len(keys), 16))
	for _, key := range keys {
		if len(caps) == 16 {
			break
		}
		caps = append(caps, unique[key])
	}
	return caps
}
