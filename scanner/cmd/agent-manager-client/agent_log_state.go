package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

// The state commands are explicitly invoked local operations. They do not start
// the managed daemon, connect a platform or install a background watcher.
func agentLogState(command string, args []string, out io.Writer) (resultErr error) {
	fs := flag.NewFlagSet(command, flag.ContinueOnError)
	dir := fs.String("state-dir", "", "absolute private AIDR state directory")
	action := fs.String("action", "status", "status, events, prepare or prune (agent-log-state)")
	agent := fs.String("agent", "", "claude or codex (agent-log-collect)")
	root := fs.String("root", "", "absolute allowed log directory")
	file := fs.String("file", "", "absolute JSONL path within root")
	sinceText := fs.String("since", "", "initial lookback RFC3339; existing cursor retains its scope")
	after := fs.String("after", "", "exclusive event pagination cursor")
	limit := fs.Int("limit", 500, "maximum events or batch records, up to 500")
	dbMiB := fs.Int64("max-db-mib", 256, "database page quota in MiB; WAL uses additional bounded space")
	events := fs.Int("max-events", 100000, "logical identity capacity; includes retained deduplication IDs")
	evidence := fs.Int("max-evidence", 200000, "evidence identity capacity")
	days := fs.Int("retention-days", 7, "acknowledged payload retention, 1-365 days")
	if e := fs.Parse(args); e != nil {
		return e
	}
	if fs.NArg() != 0 || *dir == "" || *dbMiB < 1 || *dbMiB > 4096 || *days < 1 || *days > 365 || *limit < 1 || *limit > 500 {
		return errors.New("aidr_store_options_invalid")
	}
	since := time.Now().Add(-24 * time.Hour)
	if *sinceText != "" {
		var e error
		since, e = time.Parse(time.RFC3339, *sinceText)
		if e != nil {
			return errors.New("aidr_log_since_invalid")
		}
	}
	var src agentlog.Source
	if command == "agent-log-collect" {
		var e error
		src, e = agentlog.NewSource(*agent, *root, *file)
		if e != nil {
			return e
		}
	} else if command != "agent-log-state" || (*action != "status" && *action != "events" && *action != "prepare" && *action != "prune") {
		return errors.New("aidr_store_action_invalid")
	}
	l := localstore.DefaultLimits()
	l.DatabaseBytes = *dbMiB << 20
	l.LogicalEvents = *events
	l.Evidence = *evidence
	l.Retention = time.Duration(*days) * 24 * time.Hour
	s, e := localstore.Open(*dir, l)
	if e != nil {
		return e
	}
	defer func() { resultErr = errors.Join(resultErr, s.Close()) }()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	encoder := json.NewEncoder(out)
	if command == "agent-log-collect" {
		if e := s.LoadPolicy(ctx); e != nil {
			return e
		}
		checkpoint, e := s.Collect(ctx, src, agentlog.DefaultBudget(), since)
		if e != nil {
			return e
		}
		status, e := s.Status(ctx)
		if e != nil {
			return e
		}
		return encoder.Encode(struct {
			Checkpoint localstore.Checkpoint `json:"checkpoint"`
			Status     localstore.Status     `json:"status"`
		}{checkpoint, status})
	}
	switch *action {
	case "events":
		p, e := s.Events(ctx, *after, *limit)
		if e != nil {
			return e
		}
		return encoder.Encode(p)
	case "prepare":
		b, e := s.Prepare(ctx, *limit, 1<<20)
		if e != nil {
			return e
		}
		return encoder.Encode(b)
	case "prune":
		n, e := s.Prune(ctx, time.Now())
		if e != nil {
			return e
		}
		return encoder.Encode(map[string]int64{"expired_event_payloads": n})
	default:
		v, e := s.Status(ctx)
		if e != nil {
			return e
		}
		return encoder.Encode(v)
	}
}
