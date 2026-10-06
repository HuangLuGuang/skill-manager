package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"skill-manager/scanner/internal/aidr/localstore"
	"skill-manager/scanner/internal/aidr/upload"
)

func aidrSync(args []string, out io.Writer) (resultErr error) {
	fs := flag.NewFlagSet("aidr-sync", flag.ContinueOnError)
	state := fs.String("state-dir", "", "absolute private AIDR state directory")
	server := fs.String("server", "", "platform base URL; HTTPS required except loopback")
	device := fs.String("client-id", "", "enrolled managed client ID")
	tokenEnv := fs.String("token-env", "AGENT_MANAGER_AIDR_TOKEN", "environment variable containing a device-bound credential")
	claude := fs.String("claude-root", "", "Claude JSONL root; defaults to current user's projects")
	codex := fs.String("codex-root", "", "Codex JSONL root; defaults to current user's sessions")
	claudeFile := fs.String("claude-file", "", "optional single Claude JSONL within its root")
	codexFile := fs.String("codex-file", "", "optional single Codex JSONL within its root")
	sinceText := fs.String("since", "", "initial lookback RFC3339; durable cursors keep their original scope")
	duration := fs.Duration("duration", 0, "optional bounded run duration; zero runs until interrupted")
	interval := fs.Duration("interval", 2*time.Second, "bounded intake/upload cycle interval")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 || *state == "" || *duration < 0 {
		return errors.New("aidr_upload_config_invalid")
	}
	since := time.Now().Add(-24 * time.Hour)
	if *sinceText != "" {
		var err error
		since, err = time.Parse(time.RFC3339, *sinceText)
		if err != nil {
			return errors.New("aidr_log_since_invalid")
		}
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	if *claude == "" {
		base := os.Getenv("CLAUDE_CONFIG_DIR")
		if base == "" {
			base = filepath.Join(home, ".claude")
		}
		*claude = filepath.Join(base, "projects")
	}
	if *codex == "" {
		base := os.Getenv("CODEX_HOME")
		if base == "" {
			base = filepath.Join(home, ".codex")
		}
		*codex = filepath.Join(base, "sessions")
	}
	c, err := upload.New(upload.Options{Server: *server, ClientID: *device, Token: os.Getenv(*tokenEnv)})
	if err != nil {
		return err
	}
	defer c.Close()
	s, err := localstore.Open(*state, localstore.DefaultLimits())
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, s.Close()) }()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if *duration > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, *duration)
		defer cancel()
	}
	// Emit only final health. Live collection never waits on a UI or stdout
	// consumer; state can be inspected once this explicitly launched run ends.
	err = upload.Run(ctx, s, c, upload.WorkerOptions{Roots: []upload.Root{{Agent: "claude", Path: *claude, File: *claudeFile}, {Agent: "codex", Path: *codex, File: *codexFile}}, Since: since, Interval: *interval, HeartbeatInterval: 30 * time.Second, DiscoveryInterval: 30 * time.Second})
	if err != nil && ctx.Err() == nil && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	status, err := s.Status(context.Background())
	if err != nil {
		return err
	}
	if err = s.Close(); err != nil {
		return err
	}
	stop()
	return json.NewEncoder(out).Encode(status)
}
