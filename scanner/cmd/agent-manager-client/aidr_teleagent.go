package main

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"skill-manager/scanner/internal/aidr/hooks"
)

func aidrTeleAgentService(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-teleagent-service", flag.ContinueOnError)
	home := fs.String("home", userHome(), "client home directory")
	action := fs.String("action", "run", "run or ensure the independent TeleAgent proxy")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 0 || !filepath.IsAbs(*home) {
		return errors.New("aidr_teleagent_config_invalid")
	}
	switch *action {
	case "ensure":
		if !hooks.TeleAgentProxyRequired(*home) {
			return errors.New("aidr_teleagent_config_invalid")
		}
		binary, err := os.Executable()
		if err != nil {
			return err
		}
		if err = hooks.EnsureTeleAgentProxyService(*home, binary); err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]string{"code": "aidr_teleagent_service_registered"})
	case "run":
		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer cancel()
		return hooks.RunTeleAgentProxy(ctx, *home)
	default:
		return errors.New("aidr_desktop_action_invalid")
	}
}

func aidrTeleAgentServe(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("aidr-teleagent-serve", flag.ContinueOnError)
	socket := fs.String("socket", "", "absolute path to the existing Hook receiver socket")
	listen := fs.String("listen", "127.0.0.1:0", "loopback HTTP listen address")
	secretFile := fs.String("secret-file", "", "private file containing a 32-byte hex URL access secret")
	upstreamText := fs.String("upstream", "", "original NewApi base URL for non-review requests")
	if err := fs.Parse(args); err != nil {
		return err
	}
	host, _, err := net.SplitHostPort(*listen)
	ip := net.ParseIP(host)
	if err != nil || ip == nil || !ip.IsLoopback() || fs.NArg() != 0 || !filepath.IsAbs(*socket) || !filepath.IsAbs(*secretFile) {
		return errors.New("aidr_hook_config_invalid")
	}
	if err := hooks.ValidateBridgePrivateFile(*secretFile); err != nil {
		return err
	}
	f, err := os.Open(*secretFile)
	if err != nil {
		return errors.New("aidr_hook_config_invalid")
	}
	raw, err := io.ReadAll(io.LimitReader(f, 129))
	f.Close()
	if err != nil {
		return errors.New("aidr_hook_config_invalid")
	}
	secret := strings.TrimSpace(string(raw))
	decoded, err := hex.DecodeString(secret)
	if err != nil || len(decoded) != 32 {
		return errors.New("aidr_hook_config_invalid")
	}
	var upstream *url.URL
	if *upstreamText != "" {
		upstream, err = url.Parse(*upstreamText)
		if err != nil {
			return errors.New("aidr_hook_config_invalid")
		}
	}
	handler, err := hooks.NewTeleAgentHTTP(hooks.TeleAgentHTTP{Socket: *socket, Secret: secret, Upstream: upstream})
	if err != nil {
		return err
	}
	l, err := net.Listen("tcp", *listen)
	if err != nil {
		return errors.New("aidr_hook_listener_failed")
	}
	defer l.Close()
	server := http.Server{Handler: handler, ReadHeaderTimeout: 3 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 << 10}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			server.Close()
		case <-done:
		}
	}()
	defer close(done)
	// Never print the secret URL; the operator supplies the private prefix in
	// TeleAgent's NewApi baseURL. No existing host configuration is overwritten.
	if err = json.NewEncoder(out).Encode(map[string]string{"code": "aidr_hook_healthy", "listen": l.Addr().String()}); err != nil {
		return err
	}
	err = server.Serve(l)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}
