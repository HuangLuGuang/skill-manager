package managedclient

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/BurntSushi/toml"
)

const assetLimit = 128
const assetFileLimit = 2 << 20

// Asset discovery reads configuration and metadata only. Credentials and command
// arguments are deliberately absent from this wire contract.
type AssetInventory struct {
	Version         int           `json:"version"`
	ObservedAt      string        `json:"observed_at"`
	MCPSupported    bool          `json:"mcp_supported"`
	PluginSupported bool          `json:"plugin_supported"`
	MCPServers      []MCPAsset    `json:"mcp_servers"`
	Plugins         []PluginAsset `json:"plugins"`
	Issues          []AssetIssue  `json:"issues"`
}
type AssetIssue struct {
	Code string `json:"code"`
	Path string `json:"path"`
}
type MCPAsset struct {
	ID              string   `json:"id"`
	Name            string   `json:"name"`
	Transport       string   `json:"transport"`
	EndpointOrigin  string   `json:"endpoint_origin,omitempty"`
	ServerReference string   `json:"server_reference,omitempty"`
	Executable      string   `json:"executable,omitempty"`
	ArgumentCount   int      `json:"argument_count"`
	CredentialKeys  []string `json:"credential_keys"`
	Enabled         *bool    `json:"enabled"`
	Scope           string   `json:"scope"`
	SourcePath      string   `json:"source_path"`
}
type PluginSkillAsset struct {
	Name string `json:"name"`
	Path string `json:"path"`
}
type PluginAsset struct {
	ID         string             `json:"id"`
	Name       string             `json:"name"`
	Version    string             `json:"version,omitempty"`
	Format     string             `json:"format"`
	Path       string             `json:"path,omitempty"`
	SourcePath string             `json:"source_path"`
	Scope      string             `json:"scope"`
	State      string             `json:"state"`
	Enabled    *bool              `json:"enabled"`
	Skills     []PluginSkillAsset `json:"skills"`
	MCPServers []MCPAsset         `json:"mcp_servers"`
}

type assetCollector struct {
	result     *AssetInventory
	seenMCP    map[string]bool
	seenPlugin map[string]int
	reads      int
	readBytes  int
}

func assetID(parts ...string) string {
	sum := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return hex.EncodeToString(sum[:16])
}
func assetString(value any) string         { text, _ := value.(string); return text }
func assetObject(value any) map[string]any { object, _ := value.(map[string]any); return object }
func assetBool(value any) *bool {
	if v, ok := value.(bool); ok {
		return &v
	}
	return nil
}
func assetKeys(value map[string]any) []string {
	keys := make([]string, 0, len(value))
	for key := range value {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
func (c *assetCollector) issue(code, path string) {
	if utf8.RuneCountInString(path) > 2048 {
		path = string([]rune(path)[:2048])
	}
	for _, item := range c.result.Issues {
		if item.Code == code && item.Path == path {
			return
		}
	}
	if len(c.result.Issues) < assetLimit {
		c.result.Issues = append(c.result.Issues, AssetIssue{code, path})
	}
}
func (c *assetCollector) read(path string) map[string]any {
	if c.reads >= 1024 || c.readBytes >= 16<<20 {
		c.issue("limit_reached", path)
		return nil
	}
	c.reads++
	info, err := os.Stat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil || !info.Mode().IsRegular() {
		c.issue("read_failed", path)
		return nil
	}
	if info.Size() > assetFileLimit {
		c.issue("limit_reached", path)
		return nil
	}
	f, err := os.Open(path)
	if err != nil {
		c.issue("read_failed", path)
		return nil
	}
	defer f.Close()
	body, err := io.ReadAll(io.LimitReader(f, assetFileLimit+1))
	if err != nil {
		c.issue("read_failed", path)
		return nil
	}
	if len(body) > assetFileLimit {
		c.issue("limit_reached", path)
		return nil
	}
	c.readBytes += len(body)
	if c.readBytes > 16<<20 {
		c.issue("limit_reached", path)
		return nil
	}
	var data map[string]any
	if strings.HasSuffix(path, ".toml") {
		_, err = toml.Decode(string(body), &data)
	} else {
		err = decodeModelJSON(body, &data)
	}
	if err != nil || data == nil {
		c.issue("invalid_config", path)
		return nil
	}
	return data
}

func assetOrigin(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http" && u.Scheme != "ws" && u.Scheme != "wss") || u.Hostname() == "" {
		return ""
	}
	return u.Scheme + "://" + u.Host
}

func (c *assetCollector) bounded(value string, limit int, source string) string {
	if utf8.RuneCountInString(value) <= limit {
		return value
	}
	c.issue("limit_reached", source)
	return string([]rune(value)[:limit])
}

func (c *assetCollector) boundMCP(item *MCPAsset) {
	item.Name = c.bounded(item.Name, 512, item.SourcePath)
	item.EndpointOrigin = c.bounded(item.EndpointOrigin, 2048, item.SourcePath)
	item.ServerReference = c.bounded(item.ServerReference, 512, item.SourcePath)
	item.Executable = c.bounded(item.Executable, 512, item.SourcePath)
	item.Scope = c.bounded(item.Scope, 2048, item.SourcePath)
	for i := range item.CredentialKeys {
		item.CredentialKeys[i] = c.bounded(item.CredentialKeys[i], 512, item.SourcePath)
	}
	if item.ArgumentCount > 100000 {
		c.issue("limit_reached", item.SourcePath)
		item.ArgumentCount = 100000
	}
	item.SourcePath = c.bounded(item.SourcePath, 2048, item.SourcePath)
}

func (c *assetCollector) boundWireValues() {
	for i := range c.result.MCPServers {
		c.boundMCP(&c.result.MCPServers[i])
	}
	for i := range c.result.Plugins {
		plugin := &c.result.Plugins[i]
		plugin.Name = c.bounded(plugin.Name, 512, plugin.SourcePath)
		plugin.Version = c.bounded(plugin.Version, 512, plugin.SourcePath)
		plugin.Path = c.bounded(plugin.Path, 2048, plugin.SourcePath)
		plugin.Scope = c.bounded(plugin.Scope, 2048, plugin.SourcePath)
		for j := range plugin.Skills {
			plugin.Skills[j].Name = c.bounded(plugin.Skills[j].Name, 512, plugin.SourcePath)
			plugin.Skills[j].Path = c.bounded(plugin.Skills[j].Path, 2048, plugin.SourcePath)
		}
		for j := range plugin.MCPServers {
			c.boundMCP(&plugin.MCPServers[j])
		}
		plugin.SourcePath = c.bounded(plugin.SourcePath, 2048, plugin.SourcePath)
	}
}

func (c *assetCollector) mcps(data map[string]any, source, scope string) []MCPAsset {
	result := []MCPAsset{}
	servers := assetObject(data["mcpServers"])
	if servers == nil {
		servers = assetObject(data["mcp_servers"])
	}
	if servers == nil {
		servers = assetObject(data["mcp"])
	}
	for _, name := range assetKeys(servers) {
		if len(result) >= assetLimit {
			c.issue("limit_reached", source)
			break
		}
		entry := assetObject(servers[name])
		if entry == nil {
			c.issue("invalid_config", source)
			continue
		}
		item := MCPAsset{ID: assetID(source, scope, name), Name: name, Scope: scope, SourcePath: source, Transport: "unknown", Enabled: assetBool(entry["enabled"]), CredentialKeys: []string{}}
		if disabled := assetBool(entry["disabled"]); disabled != nil {
			enabled := !*disabled
			item.Enabled = &enabled
		}
		command := assetString(entry["command"])
		args, _ := entry["args"].([]any)
		item.ArgumentCount = len(args)
		if commands, ok := entry["command"].([]any); ok && len(commands) > 0 {
			command = assetString(commands[0])
			item.ArgumentCount = len(commands) - 1
		}
		if command != "" {
			item.Transport = "stdio"
			// Shell snippets can contain inline secrets. Show only a simple executable name.
			if !strings.ContainsAny(command, " \t\r\n;|&=\"'`") {
				item.Executable = filepath.Base(command)
			}
		}
		rawURL := assetString(entry["url"])
		if rawURL == "" {
			rawURL = assetString(entry["httpUrl"])
		}
		if rawURL != "" {
			item.EndpointOrigin = assetOrigin(rawURL)
			item.Transport = "streamable_http"
		}
		if assetString(entry["type"]) == "sse" || assetString(entry["transport"]) == "sse" {
			item.Transport = "sse"
		}
		for _, key := range []string{"env", "environment", "headers", "http_headers"} {
			for _, field := range assetKeys(assetObject(entry[key])) {
				if len(item.CredentialKeys) < assetLimit {
					item.CredentialKeys = append(item.CredentialKeys, key+"."+field)
				} else {
					c.issue("limit_reached", source)
				}
			}
		}
		result = append(result, item)
	}
	return result
}
func (c *assetCollector) addMCP(data map[string]any, source, scope string) {
	for _, item := range c.mcps(data, source, scope) {
		if c.seenMCP[item.ID] {
			continue
		}
		if len(c.result.MCPServers) >= assetLimit {
			c.issue("limit_reached", source)
			return
		}
		c.seenMCP[item.ID] = true
		c.result.MCPServers = append(c.result.MCPServers, item)
	}
}

func discoverAssets(home, kind string, skillRoots []string) *AssetInventory {
	result := &AssetInventory{Version: 1, ObservedAt: time.Now().UTC().Format(time.RFC3339), MCPServers: []MCPAsset{}, Plugins: []PluginAsset{}, Issues: []AssetIssue{}}
	c := &assetCollector{result: result, seenMCP: map[string]bool{}, seenPlugin: map[string]int{}}
	defer c.boundWireValues()
	if kind == "trae" || kind == "trae-cn" {
		c.discoverTrae(home, kind, skillRoots)
		return result
	}
	rootName := map[string]string{"claude-code": ".claude", "codex": ".codex", "cursor": ".cursor", "gemini": ".gemini", "qoder": ".qoder", "qoder-cn": ".qoder-cn", "codebuddy": ".codebuddy", "workbuddy": ".workbuddy", "openclaw": ".openclaw", "opencode": ".config/opencode"}[kind]
	if kind == "claude-desktop" {
		result.MCPSupported = true
		relative := "Library/Application Support/Claude/claude_desktop_config.json"
		if runtime.GOOS == "windows" {
			relative = "AppData/Roaming/Claude/claude_desktop_config.json"
		}
		if runtime.GOOS == "linux" {
			relative = ".config/Claude/claude_desktop_config.json"
		}
		path := filepath.Join(home, filepath.FromSlash(relative))
		c.addMCP(c.read(path), path, "user")
		return result
	}
	if rootName == "" {
		return result
	}
	result.MCPSupported, result.PluginSupported = kind != "openclaw", true
	root := filepath.Dir(resolvedModelPath(home, kind, rootName+"/settings.json"))
	if kind == "codex" {
		root = filepath.Dir(resolvedModelPath(home, kind, rootName+"/config.toml"))
	}
	projects := map[string]bool{}
	for _, path := range skillRoots {
		parent := filepath.Dir(path)
		if filepath.Base(parent) == filepath.Base(rootName) && filepath.Clean(parent) != filepath.Clean(root) {
			projects[filepath.Dir(parent)] = true
		}
	}
	settingsPath := filepath.Join(root, "settings.json")
	settings := c.read(settingsPath)
	config := settings
	if kind == "codex" {
		settingsPath = filepath.Join(root, "config.toml")
		config = c.read(settingsPath)
	}
	if kind == "opencode" {
		settingsPath = modelJSONPath(kind, filepath.Join(root, "opencode.json"))
		config = c.read(settingsPath)
	}
	if kind == "openclaw" {
		settingsPath = filepath.Join(root, "openclaw.json")
		config = c.read(settingsPath)
	}
	if result.MCPSupported {
		c.addMCP(config, settingsPath, "user")
	}
	if result.MCPSupported {
		for _, name := range []string{"mcp.json", ".mcp.json"} {
			path := filepath.Join(root, name)
			c.addMCP(c.read(path), path, "user")
		}
	}
	if kind == "claude-code" {
		path := filepath.Join(home, ".claude.json")
		data := c.read(path)
		c.addMCP(data, path, "user")
		for _, project := range assetKeys(assetObject(data["projects"])) {
			if len(projects) >= assetLimit {
				c.issue("limit_reached", path)
				break
			}
			if filepath.IsAbs(project) {
				projects[project] = true
				c.addMCP(assetObject(assetObject(data["projects"])[project]), path, project)
			}
		}
	}
	for _, project := range assetKeys(assetObject(config["projects"])) {
		if filepath.IsAbs(project) && len(projects) < assetLimit {
			projects[project] = true
		}
	}
	c.discoverPlugins(root, kind, config, settingsPath, projects)
	projectPaths := []string{}
	for project := range projects {
		projectPaths = append(projectPaths, project)
	}
	sort.Strings(projectPaths)
	for _, project := range projectPaths {
		if _, err := os.Stat(project); err != nil {
			continue
		}
		projectRoot := filepath.Join(project, filepath.Base(rootName))
		paths := []string{}
		switch kind {
		case "claude-code", "qoder", "qoder-cn", "codebuddy", "workbuddy":
			paths = []string{filepath.Join(project, ".mcp.json"), filepath.Join(projectRoot, "mcp.json"), filepath.Join(projectRoot, "settings.json"), filepath.Join(projectRoot, "settings.local.json")}
		case "cursor":
			paths = []string{filepath.Join(projectRoot, "mcp.json")}
		case "gemini":
			paths = []string{filepath.Join(projectRoot, "settings.json")}
		case "codex":
			paths = []string{filepath.Join(projectRoot, "config.toml")}
		case "opencode":
			paths = []string{modelJSONPath(kind, filepath.Join(project, "opencode.json"))}
		}
		for _, path := range paths {
			// A known project can be the user's home. Its product directory
			// then points at the user configuration already collected above.
			if canonicalSkillRoot(filepath.Dir(path)) == canonicalSkillRoot(root) {
				continue
			}
			c.addMCP(c.read(path), path, project)
		}
	}
	return result
}
