package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/catalog"
)

// This read-only command emits proposed cursors; it does not update the daemon,
// save a checkpoint, upload records, or mutate the source Agent's configuration.
func readAgentLog(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("agent-log-read", flag.ContinueOnError)
	agent := fs.String("agent", "", "product log adapter ID")
	root := fs.String("root", "", "explicit allowed log directory (default: current user's Agent log root)")
	file := fs.String("file", "", "one JSONL file under the allowed root")
	cursorPath := fs.String("cursor", "", "previous cursor JSON for --file; read-only, never overwritten")
	sinceText := fs.String("since", "", "earliest event RFC3339 timestamp (default: 24 hours ago)")
	maxFiles := fs.Int("max-files", 64, "maximum files discovered")
	maxBytes := fs.Int64("max-bytes", 4<<20, "maximum bytes read per invocation")
	maxEvents := fs.Int("max-events", 500, "maximum events per invocation")
	maxLine := fs.Int("max-line-bytes", 2<<20, "maximum JSONL record size")
	duration := fs.Duration("timeout", 5*time.Second, "total read/discovery time budget")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 || !catalog.Log(*agent) {
		return errors.New("aidr_log_agent_required")
	}
	if *duration <= 0 || *duration > time.Minute || *maxBytes <= 0 || *maxBytes > 64<<20 || *maxEvents <= 0 || *maxEvents > 4096 || *maxLine <= 0 || *maxLine > 4<<20 || *maxFiles < 1 || *maxFiles > 4096 {
		return errors.New("aidr_log_budget_invalid")
	}
	if *root == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return errors.New("aidr_log_home_unavailable")
		}
		roots := agentlog.DefaultRoots(*agent, home)
		if len(roots) == 0 {
			return errors.New("aidr_log_platform_unverified")
		}
		*root = roots[0]

	}
	since := time.Now().Add(-24 * time.Hour)
	if *sinceText != "" {
		var err error
		since, err = time.Parse(time.RFC3339, *sinceText)
		if err != nil {
			return errors.New("aidr_log_since_invalid")
		}
	}
	// Keep default process signal handling: a CLI blocked on its output pipe
	// must still terminate on SIGINT/SIGTERM. Library readers accept a context.
	ctx, deadlineCancel := context.WithTimeout(context.Background(), *duration)
	defer deadlineCancel()
	encoder := json.NewEncoder(out)
	var sources []agentlog.Source
	var cursor agentlog.Cursor
	if *file != "" {
		s, err := agentlog.NewSource(*agent, *root, *file)
		if err != nil {
			return err
		}
		sources = []agentlog.Source{s}
		if *cursorPath != "" {
			f, err := os.Open(*cursorPath)
			if err != nil {
				return errors.New("aidr_log_cursor_unreadable")
			}
			defer f.Close()
			data, err := io.ReadAll(io.LimitReader(f, 16385))
			if err != nil || len(data) > 16384 {
				return errors.New("aidr_log_cursor_invalid")
			}
			if json.Unmarshal(data, &cursor) != nil {
				return errors.New("aidr_log_cursor_invalid")
			}
			if err := agentlog.ValidateCursor(cursor, s); err != nil {
				return err
			}
		}
	} else {
		if *cursorPath != "" {
			return errors.New("aidr_log_cursor_requires_file")
		}
		discovery := agentlog.Discover(ctx, *agent, *root, *maxFiles, 10000, *duration)
		if err := encoder.Encode(struct {
			SchemaVersion int    `json:"schema_version"`
			Type          string `json:"type"`
			agentlog.Discovery
		}{agentlog.SchemaVersion, "discovery", discovery}); err != nil {
			return err
		}
		sources = discovery.Sources
	}
	leftBytes, leftEvents := *maxBytes, *maxEvents
	for _, s := range sources {
		if leftBytes <= 0 || leftEvents <= 0 || ctx.Err() != nil {
			return encoder.Encode(map[string]any{"schema_version": 1, "type": "scan_coverage", "status": "partial", "reason_codes": []string{"aidr_log_read_budget"}})
		}
		batch, err := agentlog.ReadIncremental(ctx, s, cursor, agentlog.Budget{Bytes: leftBytes, Events: leftEvents, LineBytes: *maxLine, Duration: *duration}, since)
		if err != nil {
			return err
		}
		if err := encoder.Encode(batch); err != nil {
			return err
		}
		leftBytes -= batch.Coverage.Bytes
		leftEvents -= len(batch.Events)
	}
	return nil
}
