package upload

import (
	"context"
	"errors"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

type Root struct{ Agent, Path, File, UnavailableCode string }
type WorkerOptions struct {
	Roots             []Root
	Since             time.Time
	Interval          time.Duration
	HeartbeatInterval time.Duration
	DiscoveryInterval time.Duration
	// Zero reports every intake round; positive intervals also throttle the query.
	StatusInterval time.Duration
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
	if len(o.Roots) < 1 || len(o.Roots) > 64 || o.Interval < time.Second || o.Interval > time.Minute || o.HeartbeatInterval < time.Second || o.HeartbeatInterval > time.Minute || o.DiscoveryInterval < time.Second || o.DiscoveryInterval > 5*time.Minute || o.StatusInterval < 0 {
		return errors.New("aidr_upload_worker_options_invalid")
	}
	seenRoots := map[Root]bool{}
	roots := make([]Root, 0, len(o.Roots))
	for _, root := range o.Roots {
		root.Path = filepath.Clean(root.Path)
		if root.File != "" {
			root.File = filepath.Clean(root.File)
		}
		if !seenRoots[root] {
			roots = append(roots, root)
			seenRoots[root] = true
		}
	}
	o.Roots = roots
	if err := c.Bind(ctx, s); err != nil {
		return err
	}
	if err := s.LoadPolicy(ctx); err != nil {
		return err
	}
	c.policySupported = s.Policy().Version != "0"
	var nextPolicy time.Time
	var discovery []Discovery
	var nextHeartbeat, nextUpload, nextStatus time.Time
	heartbeatCode := ""
	capabilities := map[string]Capability{}
	crawlers := map[int]*localstore.Crawler{}
	for i, root := range o.Roots {
		if root.UnavailableCode != "" {
			continue
		}
		if root.File == "" {
			crawler, err := s.NewCrawler(root.Agent, root.Path)
			if err != nil {
				return err
			}
			crawler.RescanInterval = o.DiscoveryInterval
			_ = crawler.WatchChanges()
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
		// Drain durable backlog before intake consumes the remaining store space.
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
				if root.UnavailableCode != "" {
					srcKey, _ := agentlog.NewSource(root.Agent, root.Path, root.Path)
					discovery = append(discovery, Discovery{SourceID: srcKey.ID, Agent: root.Agent, Status: "unavailable", Reasons: []string{root.UnavailableCode}})
					continue
				}
				if crawler := crawlers[i]; crawler != nil {
					progress, err := crawler.Step(ctx, 64, 10000, 300*time.Millisecond)
					if errors.Is(err, localstore.ErrCapacity) {
						progress.Status = "partial"
						progress.Reasons = []string{"aidr_store_capacity"}
					} else if err != nil {
						return err
					}
					srcKey, _ := agentlog.NewSource(root.Agent, root.Path, root.Path)
					discovery = append(discovery, Discovery{SourceID: srcKey.ID, Agent: root.Agent, Status: progress.Status, Reasons: progress.Reasons, Progress: &progress})
				} else {
					srcKey, _ := agentlog.NewSource(root.Agent, root.Path, root.Path)
					discovery = append(discovery, Discovery{SourceID: srcKey.ID, Agent: root.Agent, Status: "complete", Reasons: []string{}})
				}
			}
			// Reserve a separate intake slice for recent activity and historical work.
			for _, recent := range []bool{true, false} {
				for i, root := range o.Roots {
					if root.UnavailableCode != "" {
						continue
					}
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
						collect := s.Collect
						if crawler != nil {
							collect = crawler.Collect
						}
						checkpoint, err := collect(ctx, src, budget, o.Since)
						if err != nil {
							if ctx.Err() != nil {
								return ctx.Err()
							}
							if errors.Is(err, localstore.ErrCapacity) || errors.Is(err, context.DeadlineExceeded) {
								break
							}
							if strings.HasPrefix(err.Error(), "aidr_log_") {
								discovery[i].Status = "partial"
								if !slices.Contains(discovery[i].Reasons, err.Error()) && len(discovery[i].Reasons) < 16 {
									discovery[i].Reasons = append(discovery[i].Reasons, err.Error())
								}
								continue
							}
							return err
						}
						{
							state := "available"
							if checkpoint.Coverage.Status != "complete" {
								state = "unavailable"
							}
							capabilities[src.ID] = Capability{Agent: src.Agent, Version: checkpoint.Cursor.AgentVersion, Status: state, ParserStatus: parserStatus(checkpoint.Coverage), ParserVersion: agentlog.ParserVersion}
						}
					}
					if crawler != nil {
						if err := crawler.FlushReadProgress(ctx); err != nil {
							return err
						}
					}
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
			heartbeatCode = result.Code
			nextHeartbeat = time.Now().Add(o.HeartbeatInterval)
		}
		if (o.Observer != nil || o.StatusObserver != nil) && !time.Now().Before(nextStatus) {
			status, err := s.Status(ctx)
			if err != nil {
				return err
			}
			if heartbeatCode != "" {
				status.UploadCode = heartbeatCode
				status.NextRetryAt = utcTime(nextHeartbeat)
			} else if status.UploadCode != "" {
				status.NextRetryAt = utcTime(nextUpload)
			}
			if o.Observer != nil {
				o.Observer(status)
			}
			if o.StatusObserver != nil {
				if err := o.StatusObserver(status); err != nil {
					return err
				}
			}
			nextStatus = time.Now().Add(o.StatusInterval)
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

// Parser support describes observed records; host release numbers are metadata.
func parserStatus(coverage agentlog.Coverage) string {
	for _, reason := range coverage.Reasons {
		if reason == "aidr_log_schema_unsupported" || reason == "aidr_log_invalid_json" || reason == "aidr_log_optional_record_skipped" || reason == "aidr_log_context_invalidated" {
			return "unverified"
		}
	}
	return "available"
}
