package hooks

import (
	"context"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

// TeleAgentHTTP accepts the host's native protocol and submits it to the same
// authenticated local receiver used by command Hooks. The private endpoint uses
// a hostname or URL prefix because the host offers no custom auth header.
type TeleAgentHTTP struct {
	Socket   string
	Secret   string
	Upstream *url.URL
	Exchange func(context.Context, string, IPCRequest) (IPCResponse, error)
	Active   func() (bool, error)
	// Desktop uses a private localhost hostname so the vendor's signed request
	// path survives forwarding unchanged. Command integrations retain URL prefixes.
	Status       func() TeleAgentRuntimeStatus
	PreservePath bool
}

func teleAgentLocalHost(secret string) string { return secret[:32] + "." + secret[32:] + ".localhost" }

func NewTeleAgentHTTP(options TeleAgentHTTP) (http.Handler, error) {
	secret, err := hex.DecodeString(options.Secret)
	if err != nil || len(secret) != 32 || options.Socket == "" {
		return nil, code("aidr_hook_config_invalid")
	}
	if options.Exchange == nil {
		options.Exchange = Exchange
	}
	var proxy *httputil.ReverseProxy
	if options.Upstream != nil {
		u := *options.Upstream
		if (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
			return nil, code("aidr_hook_config_invalid")
		}
		proxy = httputil.NewSingleHostReverseProxy(&u)
		proxy.ErrorLog = log.New(io.Discard, "", 0)
		proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, e error) {
			http.Error(w, "aidr_hook_upstream_unavailable", http.StatusBadGateway)
		}
		// Caller identity is local. Never forward injected proxy identity headers.
		base := proxy.Director
		proxy.Director = func(r *http.Request) {
			path, rawPath := r.URL.Path, r.URL.RawPath
			base(r)
			if options.PreservePath {
				r.URL.Path, r.URL.RawPath = path, rawPath
			}
			r.Host = u.Host
			r.Header.Del("Forwarded")
			r.Header["X-Forwarded-For"] = nil
			r.Header.Del("X-Forwarded-Host")
			r.Header.Del("X-Forwarded-Proto")
		}
	}
	slots := make(chan struct{}, 16)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		ip := net.ParseIP(host)
		path := strings.SplitN(strings.TrimPrefix(r.URL.Path, "/"), "/", 2)
		authenticated := len(path) == 2 && subtle.ConstantTimeCompare([]byte(path[0]), []byte(options.Secret)) == 1
		if options.PreservePath {
			name, _, hostErr := net.SplitHostPort(r.Host)
			authenticated = hostErr == nil && subtle.ConstantTimeCompare([]byte(name), []byte(teleAgentLocalHost(options.Secret))) == 1
		}
		if err != nil || ip == nil || !ip.IsLoopback() || r.Header.Get("Origin") != "" || !authenticated {
			http.Error(w, "aidr_hook_peer_rejected", http.StatusForbidden)
			return
		}
		if !options.PreservePath {
			r.URL.Path = "/" + path[1]
			r.URL.RawPath = ""
		}
		route := r.URL.Path
		if options.PreservePath && options.Upstream != nil {
			route = strings.TrimPrefix(route, strings.TrimRight(options.Upstream.Path, "/"))
		}
		if r.Method == http.MethodGet && route == "/_agent_manager/health" {
			w.Header().Set("Cache-Control", "no-store")
			_, _ = io.WriteString(w, "aidr_teleagent_bridge_ready")
			return
		}
		if r.Method == http.MethodGet && route == "/_agent_manager/status" && options.Status != nil {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Cache-Control", "no-store")
			_ = json.NewEncoder(w).Encode(options.Status())
			return
		}
		active := true
		if (route == "/security/instruction/review" || route == "/api/v1/security/instruction/review") && options.Active != nil {
			var err error
			active, err = options.Active()
			if err != nil {
				w.Header().Set("Content-Type", "application/json")
				w.Header().Set("Cache-Control", "no-store")
				_ = WriteHostDecision(w, "teleagent", "", "deny", "aidr_teleagent_config_invalid")
				return
			}
		}
		if (route != "/security/instruction/review" && route != "/api/v1/security/instruction/review") || !active {
			if proxy != nil {
				proxy.ServeHTTP(w, r)
			} else {
				http.NotFound(w, r)
			}
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		reply := func(decision, reason string) { _ = WriteHostDecision(w, "teleagent", "", decision, reason) }
		if r.Method != http.MethodPost {
			reply("deny", "aidr_hook_method_unsupported")
			return
		}
		select {
		case slots <- struct{}{}:
			defer func() { <-slots }()
		default:
			reply("deny", "aidr_hook_receiver_busy")
			return
		}
		_ = http.NewResponseController(w).SetReadDeadline(time.Now().Add(time.Second))
		raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, MaxRecordBytes))
		if err != nil {
			reply("deny", "aidr_hook_record_invalid")
			return
		}
		hook, err := TeleAgentEvent(raw)
		if err != nil {
			reply("deny", "aidr_hook_event_unsupported")
			return
		}
		id, err := NewEventID()
		if err != nil {
			reply("deny", "aidr_hook_receiver_unavailable")
			return
		}
		// Match command Hooks: do not abandon a connected review before the
		// receiver's two-second processing deadline. Upgrade dial waits remain
		// separately bounded and never replay an ambiguous submitted event.
		reviewContext := r.Context()
		if hook == "BeforeMCPExecute" || hook == "AfterMCPExecute" {
			// Preserve the existing MCP adapter budget, including during an
			// upgrade: its native review contract is shorter than tool review.
			var cancel context.CancelFunc
			reviewContext, cancel = context.WithTimeout(reviewContext, time.Second)
			defer cancel()
		}
		response, err := exchangeForHost(reviewContext, options.Socket, IPCRequest{Version: 1, Method: "SubmitEvent", EventID: id, Agent: "teleagent", Hook: hook, Raw: raw}, 4*time.Second, options.Exchange)
		if err != nil {
			reason := "aidr_hook_receiver_unavailable"
			switch err.Error() {
			case "aidr_hook_peer_rejected", "aidr_hook_transport_failed", "aidr_hook_protocol_invalid", "aidr_hook_response_timeout", "aidr_hook_record_oversized":
				reason = err.Error()
			}
			reply("deny", reason)
			return
		}
		if response.Decision != nil {
			reply(response.Decision.Decision, response.Decision.Code)
			return
		}
		if (response.Code == "aidr_hook_recorded" || response.Code == "aidr_hook_audit_paused") && response.State != nil && (response.State.ControlMode == "audit" || !IsPreTool("teleagent", hook)) {
			reply("allow", response.Code)
			return
		}
		reply("deny", "aidr_hook_decision_unavailable")
	}), nil
}
