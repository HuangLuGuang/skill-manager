package hooks

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type PluginStatus struct {
	Agent               string       `json:"agent"`
	HostVersion         string       `json:"host_version"`
	VersionStatus       string       `json:"version_status"`
	Installed           *bool        `json:"installed"`
	Enabled             *bool        `json:"enabled"`
	PluginVersion       string       `json:"plugin_version"`
	PluginID            string       `json:"plugin_id"`
	SourceCode          string       `json:"source_code"`
	HookTrust           string       `json:"hook_trust"`
	ReportedAt          string       `json:"reported_at"`
	ReceiverCode        string       `json:"receiver_code"`
	ConfigurationDigest string       `json:"configuration_digest,omitempty"`
	SourceKind          string       `json:"source_kind"`
	FilesCode           string       `json:"files_code"`
	FilesDigest         string       `json:"files_digest,omitempty"`
	ScopeDigest         string       `json:"scope_digest,omitempty"`
	Drift               *PluginDrift `json:"drift,omitempty"`
	sourcePath          string
}

type boundedOutput struct{ bytes.Buffer }

func (b *boundedOutput) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 256<<10 {
		return 0, io.ErrShortWrite
	}
	return b.Buffer.Write(p)
}

// Native output is parsed but never returned as a diagnostic: it can contain
// unrelated plugin configuration. ConfigHome is an explicit child environment,
// not a modification of the current user's configuration.
func hostCommand(ctx context.Context, binary, agent, configHome string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, args...)
	cmd.WaitDelay = time.Second
	cmd.Env = os.Environ()
	if len(args) == 1 && args[0] == "--version" || len(args) == 3 && args[0] == "plugin" && args[1] == "list" && args[2] == "--json" {
		cmd.Env = append(cmd.Env, "AGENT_MANAGER_ACTIVITY=client_probe")
	}
	if configHome != "" {
		key := "CODEX_HOME"
		if agent == "claude" {
			key = "CLAUDE_CONFIG_DIR"
		}
		env := cmd.Env[:0]
		for _, v := range cmd.Env {
			if !strings.HasPrefix(v, key+"=") {
				env = append(env, v)
			}
		}
		cmd.Env = append(env, key+"="+configHome)
	}
	var out boundedOutput
	cmd.Stdout = &out
	cmd.Stderr = io.Discard
	stop, err := startNativeProcess(cmd)
	if err != nil {
		return nil, code("aidr_plugin_source_unreadable")
	}
	defer stop()
	if err := cmd.Wait(); err != nil {
		return nil, code("aidr_plugin_source_unreadable")
	}
	return out.Bytes(), nil
}

func ParsePluginStatus(agent string, raw []byte) (PluginStatus, error) {
	s := PluginStatus{Agent: agent, HookTrust: "unknown", VersionStatus: "unverified", SourceCode: "aidr_plugin_source_unreadable", SourceKind: "unknown", FilesCode: "aidr_plugin_files_unknown"}
	if len(raw) > 256<<10 {
		return s, code("aidr_plugin_source_unreadable")
	}
	var rows []struct {
		ID          string `json:"id"`
		PluginID    string `json:"pluginId"`
		Enabled     *bool  `json:"enabled"`
		Installed   *bool  `json:"installed"`
		Version     string `json:"version"`
		InstallPath string `json:"installPath"`
		Source      struct {
			Kind string `json:"source"`
			Path string `json:"path"`
		} `json:"source"`
	}
	if agent == "codex" {
		var root struct {
			Installed json.RawMessage `json:"installed"`
		}
		if json.Unmarshal(raw, &root) != nil || len(root.Installed) == 0 || string(root.Installed) == "null" || json.Unmarshal(root.Installed, &rows) != nil {
			return s, code("aidr_plugin_source_unreadable")
		}
	} else if agent == "claude" {
		if string(bytes.TrimSpace(raw)) == "null" || json.Unmarshal(raw, &rows) != nil {
			return s, code("aidr_plugin_source_unreadable")
		}
	} else {
		return s, code("aidr_plugin_host_unsupported")
	}
	found := 0
	for _, row := range rows {
		id := row.ID
		if agent == "codex" {
			id = row.PluginID
		}
		if id == "" || len(id) > 256 || strings.ContainsAny(id, "\n\r\t") {
			return s, code("aidr_plugin_source_unreadable")
		}
		if !strings.HasPrefix(id, "aidr-"+agent+"@") {
			continue
		}
		found++
		s.PluginID = id
		yes := true
		s.Installed = &yes
		s.Enabled = row.Enabled
		s.PluginVersion = row.Version
		if agent == "claude" && filepath.IsAbs(row.InstallPath) {
			s.sourcePath = row.InstallPath
			s.SourceKind = "native_install_path"
		} else if agent == "codex" && row.Source.Kind == "local" && filepath.IsAbs(row.Source.Path) {
			s.sourcePath = row.Source.Path
			s.SourceKind = "declared_local_source"
		}
		if agent == "codex" {
			s.Installed = row.Installed
		}
		if row.Enabled == nil || s.Installed == nil || len(row.Version) > 80 {
			return PluginStatus{Agent: agent, HookTrust: "unknown", SourceCode: "aidr_plugin_source_unreadable", SourceKind: "unknown", FilesCode: "aidr_plugin_files_unknown"}, code("aidr_plugin_source_unreadable")
		}
	}
	if found > 1 {
		s.Installed = nil
		s.Enabled = nil
		s.SourceCode = "aidr_plugin_multiple_sources"
		s.sourcePath = ""
		s.SourceKind = "unknown"
		return s, nil
	}
	if found == 0 {
		no := false
		s.Installed = &no
		s.Enabled = &no
		s.SourceCode = "aidr_plugin_not_installed"
	} else if !*s.Installed {
		s.SourceCode = "aidr_plugin_not_installed"
	} else if !*s.Enabled {
		s.SourceCode = "aidr_plugin_disabled"
	} else {
		s.SourceCode = "aidr_plugin_enabled_trust_unknown"
	}
	// This digest describes plugin metadata, never an effective permission
	// or hook trust decision. Paths are hashed locally rather than uploaded.
	metadata, _ := json.Marshal([]any{s.Agent, s.PluginID, s.PluginVersion, s.Installed, s.Enabled, s.SourceKind, s.sourcePath})
	sum := sha256.Sum256(metadata)
	s.ConfigurationDigest = hex.EncodeToString(sum[:])
	return s, nil
}

func inspectNativePlugin(ctx context.Context, agent, binary, configHome, socket string) (PluginStatus, error) {
	status := pluginStatus(agent)
	if (agent != "codex" && agent != "claude") || !filepath.IsAbs(binary) || (configHome != "" && !filepath.IsAbs(configHome)) {
		return status, code("aidr_plugin_config_invalid")
	}
	effectiveHome := configHome
	if effectiveHome == "" {
		key := "CODEX_HOME"
		if agent == "claude" {
			key = "CLAUDE_CONFIG_DIR"
		}
		effectiveHome = os.Getenv(key)
		if effectiveHome == "" {
			home, e := os.UserHomeDir()
			if e != nil {
				return status, code("aidr_plugin_config_invalid")
			}
			effectiveHome = filepath.Join(home, "."+agent)
		}
	}
	if !filepath.IsAbs(effectiveHome) {
		return status, code("aidr_plugin_config_invalid")
	}
	scope, _ := json.Marshal([]any{agent, os.Geteuid(), filepath.Clean(effectiveHome)})
	scopeSum := sha256.Sum256(scope)
	status.ScopeDigest = hex.EncodeToString(scopeSum[:])
	version, err := hostCommand(ctx, binary, agent, configHome, "--version")
	if err == nil {
		status.HostVersion = strings.TrimSpace(string(version))
	}
	if len(status.HostVersion) > 100 || strings.ContainsAny(status.HostVersion, "\n\r") {
		status.HostVersion = ""
	}
	var data []byte
	if agent == "codex" {
		// Query the native local inventory on demand. Starting the host can still
		// refresh configured marketplaces; background checks use local files.
		data, err = nativeCodexLocalPlugins(ctx, binary, effectiveHome)
		if err == errNativeMethodUnsupported {
			data, err = hostCommand(ctx, binary, agent, configHome, "plugin", "list", "--json")
		}
	} else {
		data, err = hostCommand(ctx, binary, agent, configHome, "plugin", "list", "--json")
	}
	if err != nil {
		return status, nil
	}
	parsed, err := ParsePluginStatus(agent, data)
	if err == nil {
		parsed.HostVersion = status.HostVersion
		if parsed.Installed != nil && parsed.Enabled != nil {
			parsed.VersionStatus = "interface_compatible"
		}
		parsed.ReportedAt = status.ReportedAt
		parsed.ReceiverCode = status.ReceiverCode
		parsed.ScopeDigest = status.ScopeDigest
		status = parsed
		if status.Installed != nil && *status.Installed && status.sourcePath != "" {
			status.FilesDigest, status.FilesCode = pluginFilesDigest(agent, status.sourcePath)
		}
	}
	if socket != "" {
		reply, e := Exchange(ctx, socket, IPCRequest{Version: 1, Method: "GetHealth"})
		if e != nil {
			status.ReceiverCode = "aidr_hook_receiver_unavailable"
		} else {
			status.ReceiverCode = reply.Code
		}
	}
	return status, nil
}

// Check the native reported source, rather than assuming installation used the
// desktop's current marketplace. Unknown/ambiguous sources cannot be migrated.
func PluginBridgeMatches(status PluginStatus, connection string) bool {
	if status.sourcePath == "" {
		return false
	}
	p := filepath.Join(status.sourcePath, "scripts", "bridge.sh")
	f, e := os.Open(p)
	if e != nil {
		return false
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, 65537))
	return e == nil && len(b) <= 65536 && strings.Contains(string(b), "--connection-file "+shellQuote(connection)+" --agent ")
}

// InstallPlugin delegates installation to the native host. A local marketplace
// must contain the expected package and keep its source within that directory.
// Native hook trust is deliberately not changed by this command.
func installNativePlugin(ctx context.Context, agent, binary, configHome, marketplace string) (PluginStatus, error) {
	status, err := InspectPlugin(ctx, agent, binary, configHome, "")
	if err != nil {
		return status, err
	}
	if status.VersionStatus != "interface_compatible" {
		return status, code("aidr_plugin_interface_unavailable")
	}
	if !filepath.IsAbs(marketplace) {
		return status, code("aidr_plugin_marketplace_invalid")
	}
	real, err := filepath.EvalSymlinks(marketplace)
	if err != nil || real != filepath.Clean(marketplace) {
		return status, code("aidr_plugin_marketplace_invalid")
	}
	manifest := filepath.Join(real, ".agents", "plugins", "marketplace.json")
	if agent == "claude" {
		manifest = filepath.Join(real, ".claude-plugin", "marketplace.json")
	}
	f, err := os.Open(manifest)
	if err != nil {
		return status, code("aidr_plugin_marketplace_unreadable")
	}
	raw, err := io.ReadAll(io.LimitReader(f, 65537))
	f.Close()
	if err != nil || len(raw) > 65536 {
		return status, code("aidr_plugin_marketplace_invalid")
	}
	var market struct {
		Name    string `json:"name"`
		Plugins []struct {
			Name   string          `json:"name"`
			Source json.RawMessage `json:"source"`
		} `json:"plugins"`
	}
	if json.Unmarshal(raw, &market) != nil || !regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`).MatchString(market.Name) {
		return status, code("aidr_plugin_marketplace_invalid")
	}
	count := 0
	for _, entry := range market.Plugins {
		if entry.Name != "aidr-"+agent {
			continue
		}
		count++
		var path string
		if agent == "claude" {
			if json.Unmarshal(entry.Source, &path) != nil {
				return status, code("aidr_plugin_marketplace_invalid")
			}
		} else {
			var source struct {
				Source string `json:"source"`
				Path   string `json:"path"`
			}
			if json.Unmarshal(entry.Source, &source) != nil || source.Source != "local" {
				return status, code("aidr_plugin_marketplace_invalid")
			}
			path = source.Path
		}
		if !strings.HasPrefix(path, "./") {
			return status, code("aidr_plugin_marketplace_invalid")
		}
		resolved, e := filepath.EvalSymlinks(filepath.Join(real, path))
		if e != nil || !strings.HasPrefix(resolved, real+string(os.PathSeparator)) {
			return status, code("aidr_plugin_marketplace_invalid")
		}
	}
	if count != 1 {
		return status, code("aidr_plugin_marketplace_invalid")
	}
	if status.Installed == nil {
		return status, code("aidr_plugin_source_unreadable")
	}
	if *status.Installed {
		if status.PluginID != "aidr-"+agent+"@"+market.Name {
			return status, code("aidr_plugin_multiple_sources")
		}
		return status, nil
	}
	if _, err = hostCommand(ctx, binary, agent, configHome, "plugin", "marketplace", "add", real); err != nil {
		return status, code("aidr_plugin_install_failed")
	}
	args := []string{"plugin", "add", "aidr-" + agent + "@" + market.Name, "--json"}
	if agent == "claude" {
		args = []string{"plugin", "install", "aidr-claude@" + market.Name, "--scope", "user"}
	}
	if _, err = hostCommand(ctx, binary, agent, configHome, args...); err != nil {
		return status, code("aidr_plugin_install_failed")
	}
	return InspectPlugin(ctx, agent, binary, configHome, "")
}
