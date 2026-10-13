package hooks

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// TeleAgent 2.7 desktop injects NewApi configuration at application startup.
// Its internal-debug.yaml llmBaseUrl override precedes that injection; ordinary
// TeleAgent.jsonc edits do not. Only this adapter owns that vendor configuration.
type teleAgentDesktopState struct {
	Address   string     `json:"address"`
	Secret    string     `json:"secret"`
	Upstream  string     `json:"upstream"`
	Previous  *yaml.Node `json:"previous,omitempty"`
	Installed bool       `json:"installed"`
}

func teleAgentStatePath(home string) string {
	return filepath.Join(home, ".agent-manager/aidr/teleagent-desktop.json")
}
func teleAgentConfigPath(home string) string {
	return filepath.Join(home, ".local/share/TeleAgent/internal-debug.yaml")
}
func (s teleAgentDesktopState) base() string {
	_, port, _ := net.SplitHostPort(s.Address)
	u, _ := url.Parse(s.Upstream)
	return "http://" + net.JoinHostPort(teleAgentLocalHost(s.Secret), port) + strings.TrimRight(u.EscapedPath(), "/")
}
func teleAgentDesktopAdapter() *desktopIntegration {
	return &desktopIntegration{Inspect: inspectTeleAgentDesktop, Configure: configureTeleAgentDesktop}
}

func TeleAgentProxyRequired(home string) bool {
	_, err := os.Stat(teleAgentStatePath(home))
	return !os.IsNotExist(err)
}

// RunTeleAgentProxy runs under the service manager, independently of the desktop
// and Hook receiver. The private host configuration remains stable across restarts.
func RunTeleAgentProxy(ctx context.Context, home string) error {
	if _, err := readTeleAgentState(home); err != nil {
		return code("aidr_teleagent_config_invalid")
	}
	runTeleAgentDesktop(ctx, home, filepath.Join(home, ".agent-manager/aidr/hook.sock"), filepath.Join(home, ".agent-manager/aidr/bridge.json"))
	return nil
}
func readTeleAgentState(home string) (teleAgentDesktopState, error) {
	var s teleAgentDesktopState
	b, e := os.ReadFile(teleAgentStatePath(home))
	if e != nil {
		return s, e
	}
	if json.Unmarshal(b, &s) != nil {
		return s, code("aidr_teleagent_config_invalid")
	}
	host, _, e := net.SplitHostPort(s.Address)
	key, ke := hex.DecodeString(s.Secret)
	u, ue := url.Parse(s.Upstream)
	if e != nil || host != "127.0.0.1" || ke != nil || len(key) != 32 || ue != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return s, code("aidr_teleagent_config_invalid")
	}
	return s, nil
}
func teleAgentAtomic(path string, b []byte) error {
	if e := os.MkdirAll(filepath.Dir(path), 0700); e != nil {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".teleagent-")
	if e != nil {
		return e
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, e = f.Write(b); e != nil {
		return e
	}
	if e = f.Sync(); e != nil {
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	return os.Rename(f.Name(), path)
}
func readTeleAgentYAML(home string) (*yaml.Node, error) {
	path := teleAgentConfigPath(home)
	st, e := os.Lstat(path)
	if os.IsNotExist(e) {
		return &yaml.Node{Kind: yaml.DocumentNode, Content: []*yaml.Node{{Kind: yaml.MappingNode, Tag: "!!map"}}}, nil
	}
	if e != nil {
		return nil, e
	}
	if !st.Mode().IsRegular() || st.Size() > 1<<20 {
		return nil, code("aidr_teleagent_config_invalid")
	}
	b, e := os.ReadFile(path)
	if e != nil {
		return nil, e
	}
	var doc yaml.Node
	if len(bytes.TrimSpace(b)) == 0 {
		doc = yaml.Node{Kind: yaml.DocumentNode, Content: []*yaml.Node{{Kind: yaml.MappingNode, Tag: "!!map"}}}
	} else if yaml.Unmarshal(b, &doc) != nil {
		return nil, code("aidr_teleagent_config_invalid")
	}
	if len(doc.Content) != 1 || doc.Content[0].Kind != yaml.MappingNode {
		return nil, code("aidr_teleagent_config_invalid")
	}
	// Decode once to reject duplicate keys that the vendor parser also rejects.
	var checked map[string]any
	if doc.Decode(&checked) != nil {
		return nil, code("aidr_teleagent_config_invalid")
	}
	return &doc, nil
}
func teleAgentURLNode(doc *yaml.Node) (int, *yaml.Node) {
	for i := 0; i < len(doc.Content[0].Content); i += 2 {
		if doc.Content[0].Content[i].Value == "llmBaseUrl" {
			return i, doc.Content[0].Content[i+1]
		}
	}
	return -1, nil
}
func inspectTeleAgentDesktop(home string) (PluginStatus, error) {
	status := pluginStatus("teleagent")
	installed := false
	status.Installed = &installed
	status.SourceKind = "settings"
	status.SourceCode = "aidr_plugin_not_installed"
	if runtime.GOOS != "darwin" {
		return status, nil
	}
	if _, e := os.Stat(filepath.Join(home, ".local/share/TeleAgent/runtimes/super-agent-code/bin/TeleAgent")); e != nil {
		status.SourceCode = "aidr_desktop_host_missing"
		return status, nil
	}
	status.VersionStatus = "adapter_available"
	s, e := readTeleAgentState(home)
	if os.IsNotExist(e) {
		return status, nil
	}
	if e != nil {
		return status, e
	}
	doc, e := readTeleAgentYAML(home)
	if e != nil {
		return status, e
	}
	_, n := teleAgentURLNode(doc)
	installed = s.Installed && n != nil && n.Value == s.base()
	if s.Installed && !installed {
		status.SourceCode = "aidr_teleagent_configuration_changed"
		return status, nil
	}
	if installed {
		status.PluginVersion = BundledPluginVersion
		status.SourceCode = "aidr_teleagent_restart_required"
		// Reachability only proves the bridge is listening, not event delivery.
		client := &http.Client{Timeout: 200 * time.Millisecond, Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
		r, e := client.Get(s.base() + "/_agent_manager/health")
		ready := false
		if e == nil {
			b, _ := io.ReadAll(io.LimitReader(r.Body, 64))
			r.Body.Close()
			ready = r.StatusCode == 200 && string(b) == "aidr_teleagent_bridge_ready"
		}
		if ready {
			status.ReceiverCode = "aidr_teleagent_bridge_ready"
		} else {
			status.ReceiverCode = "aidr_teleagent_bridge_unavailable"
		}
	}
	return status, nil
}
func configureTeleAgentDesktop(home string, remove bool) (PluginStatus, error) {
	status, e := inspectTeleAgentDesktop(home)
	if e != nil {
		return status, e
	}
	if !remove && status.VersionStatus != "adapter_available" {
		return status, code("aidr_desktop_host_missing")
	}
	doc, e := readTeleAgentYAML(home)
	if e != nil {
		return status, e
	}
	index, node := teleAgentURLNode(doc)
	s, e := readTeleAgentState(home)
	if e != nil && !os.IsNotExist(e) {
		return status, e
	}
	if remove {
		if os.IsNotExist(e) || !s.Installed {
			return status, nil
		}
		if node == nil || node.Value != s.base() {
			return status, code("aidr_teleagent_configuration_changed")
		}
		if s.Previous == nil {
			doc.Content[0].Content = append(doc.Content[0].Content[:index], doc.Content[0].Content[index+2:]...)
		} else {
			doc.Content[0].Content[index+1] = s.Previous
		}
	} else {
		if e == nil && s.Installed {
			if node == nil || node.Value != s.base() {
				return status, code("aidr_teleagent_configuration_changed")
			}
			return status, nil
		}
		if e != nil {
			l, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				return status, err
			}
			s.Address = l.Addr().String()
			l.Close()
			secret := make([]byte, 32)
			if _, err = rand.Read(secret); err != nil {
				return status, err
			}
			s.Secret = hex.EncodeToString(secret)
		}
		s.Upstream = "https://agent.teleai.com.cn/superCowork/sapi"
		s.Previous = node
		if node != nil && node.Value != "" {
			if node.Kind != yaml.ScalarNode || node.Tag != "!!str" {
				return status, code("aidr_teleagent_config_invalid")
			}
			s.Upstream = strings.TrimRight(node.Value, "/")
		}
		u, err := url.Parse(s.Upstream)
		if err != nil || u.Host == "" || (u.Scheme != "https" && u.Scheme != "http") || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Host == s.Address {
			return status, code("aidr_teleagent_config_invalid")
		}
		replacement := &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: s.base()}
		if index < 0 {
			doc.Content[0].Content = append(doc.Content[0].Content, &yaml.Node{Kind: yaml.ScalarNode, Tag: "!!str", Value: "llmBaseUrl"}, replacement)
		} else {
			doc.Content[0].Content[index+1] = replacement
		}
		// Save recovery information before touching the host configuration.
		s.Installed = true
		b, _ := json.Marshal(s)
		if e = teleAgentAtomic(teleAgentStatePath(home), b); e != nil {
			return status, e
		}
	}
	b, e := yaml.Marshal(doc)
	if e != nil {
		return status, e
	}
	if e = teleAgentAtomic(teleAgentConfigPath(home), b); e != nil {
		return status, e
	}
	if remove {
		// A running host still uses the old base URL until restart. Retain a proxy
		// record so disconnecting cannot strand its model requests.
		s.Installed = false
		b, _ = json.Marshal(s)
		if e = teleAgentAtomic(teleAgentStatePath(home), b); e != nil {
			return status, e
		}
	}
	return inspectTeleAgentDesktop(home)
}
func runTeleAgentDesktop(ctx context.Context, home, socket, connection string) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	var server *http.Server
	var address, upstream string
	defer func() {
		if server != nil {
			server.Close()
		}
	}()
	for {
		s, e := readTeleAgentState(home)
		if e == nil && server == nil {
			u, _ := url.Parse(s.Upstream)
			handler, err := NewTeleAgentHTTP(TeleAgentHTTP{Socket: socket, Secret: s.Secret, Upstream: u, PreservePath: true,
				Active: func() (bool, error) {
					current, err := readTeleAgentState(home)
					if err != nil {
						return false, err
					}
					if !current.Installed {
						return false, nil
					}
					var c struct {
						Active bool     `json:"active"`
						Agents []string `json:"agents"`
					}
					raw, err := os.ReadFile(connection)
					if err != nil {
						return false, err
					}
					if json.Unmarshal(raw, &c) != nil {
						return false, code("aidr_teleagent_config_invalid")
					}
					return c.Active && slices.Contains(c.Agents, "teleagent"), nil
				}})
			if err == nil {
				l, err := net.Listen("tcp", s.Address)
				if err == nil {
					server = &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 90 * time.Second}
					address, upstream = s.Address, s.Upstream
					go server.Serve(l)
				}
			}
		}
		// Upstream can change only while disconnected and subsequently re-enrolled.
		// Restart this product listener without affecting the shared receiver.
		if server != nil && (e != nil || s.Address != address || s.Upstream != upstream) {
			server.Close()
			server = nil
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
