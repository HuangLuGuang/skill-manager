package hooks

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"skill-manager/scanner/internal/runtimeinfo"
)

type TeleAgentRuntimeStatus struct {
	Health        string            `json:"health"`
	Runtime       *runtimeinfo.Info `json:"runtime,omitempty"`
	DesiredSHA256 string            `json:"desired_sha256,omitempty"`
	Upgrade       string            `json:"upgrade"`
	Active        int64             `json:"active_requests"`
}
type proxyCandidate struct {
	Binary string `json:"binary"`
	SHA256 string `json:"sha256"`
}

func proxyRoot(home string) string { return filepath.Join(home, ".agent-manager/aidr/teleagent-proxy") }
func readProxyCandidate(home string) proxyCandidate {
	var c proxyCandidate
	raw, _ := os.ReadFile(filepath.Join(proxyRoot(home), "desired.json"))
	_ = json.Unmarshal(raw, &c)
	return c
}

type proxyRuntime struct {
	active  atomic.Int64
	mu      sync.Mutex
	upgrade string
	desired string
}

func (p *proxyRuntime) set(upgrade, desired string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.upgrade, p.desired = upgrade, desired
}
func (p *proxyRuntime) status() TeleAgentRuntimeStatus {
	p.mu.Lock()
	defer p.mu.Unlock()
	info := runtimeinfo.Current()
	return TeleAgentRuntimeStatus{Health: "healthy", Runtime: &info, DesiredSHA256: p.desired, Upgrade: p.upgrade, Active: p.active.Load()}
}
func (p *proxyRuntime) track(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/_agent_manager/status") && !strings.HasSuffix(r.URL.Path, "/_agent_manager/health") {
			p.active.Add(1)
			defer p.active.Add(-1)
		}
		h.ServeHTTP(w, r)
	})
}

// Draining closes keep-alive connections and stops accepts, while a duplicate
// holds the listening socket and its kernel backlog. On timeout the caller
// resumes accepting; Shutdown never force-closes the remaining active streams.
func drainProxy(server *http.Server, listener net.Listener) (net.Listener, bool, error) {
	file, err := listener.(*net.TCPListener).File()
	if err != nil {
		return nil, false, err
	}
	defer file.Close()
	next, err := net.FileListener(file)
	if err != nil {
		return nil, false, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	err = server.Shutdown(ctx)
	return next, err == nil, nil
}

// TeleAgentProxyStatus checks the authenticated local HTTP endpoint. A healthy
// proxy proves forwarding readiness, not the reachability of a vendor model.
func TeleAgentProxyStatus(ctx context.Context, home string) TeleAgentRuntimeStatus {
	result := TeleAgentRuntimeStatus{Health: "unavailable", Upgrade: "unknown"}
	if !TeleAgentProxyRequired(home) {
		result.Health = "not_configured"
		return result
	}
	s, err := readTeleAgentState(home)
	if err != nil {
		return result
	}
	u, _ := url.Parse(s.Upstream)
	req, _ := http.NewRequestWithContext(ctx, "GET", "http://"+s.Address+strings.TrimRight(u.Path, "/")+"/_agent_manager/status", nil)
	_, port, _ := net.SplitHostPort(s.Address)
	req.Host = teleAgentLocalHost(s.Secret) + ":" + port
	client := &http.Client{Timeout: time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	defer client.CloseIdleConnections()
	resp, err := client.Do(req)
	if err != nil {
		return result
	}
	defer resp.Body.Close()
	if resp.StatusCode == 200 {
		var status TeleAgentRuntimeStatus
		if json.NewDecoder(io.LimitReader(resp.Body, 8192)).Decode(&status) == nil && status.Runtime != nil && status.Runtime.PID > 0 {
			return status
		}
	}
	// Older proxies expose only readiness. Do not attribute the on-disk
	// candidate identity to that process, or mistake an upstream response for
	// proxy health.
	_ = resp.Body.Close()
	req.URL.Path = strings.TrimRight(u.Path, "/") + "/_agent_manager/health"
	legacy, err := client.Do(req)
	if err == nil {
		defer legacy.Body.Close()
		body, _ := io.ReadAll(io.LimitReader(legacy.Body, 64))
		if legacy.StatusCode == 200 && string(body) == "aidr_teleagent_bridge_ready" {
			result.Health = "healthy"
			result.Upgrade = "legacy"
		}
	}
	return result
}
