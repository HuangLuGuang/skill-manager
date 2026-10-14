package managedclient

import (
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

var pluginManifests = []struct{ path, format string }{
	{"plugin.json", "agent_plugins"}, {".codex-plugin/plugin.json", "codex"},
	{".claude-plugin/plugin.json", "claude"}, {".cursor-plugin/plugin.json", "cursor"},
	{".qoder-plugin/plugin.json", "qoder"}, {".codebuddy-plugin/plugin.json", "codebuddy"},
	{".workbuddy-plugin/plugin.json", "workbuddy"}, {"gemini-extension.json", "gemini"},
	{"openclaw.plugin.json", "openclaw"},
}

func assetPaths(value any) []string {
	if text := assetString(value); text != "" {
		return []string{text}
	}
	paths := []string{}
	if values, ok := value.([]any); ok {
		for _, item := range values {
			if text := assetString(item); text != "" {
				paths = append(paths, text)
			}
		}
	}
	return paths
}

// Component declarations belong to a plugin package. Do not follow references
// outside that package or turn discovery into execution of product commands.
func (c *assetCollector) componentPath(root, relative string) string {
	path := filepath.Join(root, relative)
	if filepath.IsAbs(relative) {
		path = relative
	}
	resolvedRoot, rootErr := filepath.EvalSymlinks(root)
	resolved, err := filepath.EvalSymlinks(path)
	if os.IsNotExist(err) {
		return ""
	}
	if err != nil || rootErr != nil {
		c.issue("read_failed", path)
		return ""
	}
	rel, err := filepath.Rel(resolvedRoot, resolved)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		c.issue("outside_package", path)
		return ""
	}
	return resolved
}

func (c *assetCollector) pluginSkills(root string, manifest map[string]any) []PluginSkillAsset {
	result := []PluginSkillAsset{}
	seen := map[string]bool{}
	roots := assetPaths(manifest["skills"])
	if len(roots) == 0 {
		roots = []string{"skills"}
	}
	if _, err := os.Stat(filepath.Join(root, "SKILL.md")); err == nil {
		roots = append(roots, "SKILL.md")
	}
	visited := 0
	for _, relative := range roots {
		start := c.componentPath(root, relative)
		if start == "" {
			continue
		}
		_ = filepath.WalkDir(start, func(path string, entry fs.DirEntry, err error) error {
			if err != nil {
				c.issue("read_failed", path)
				return nil
			}
			visited++
			if visited > 2048 || len(result) >= assetLimit {
				c.issue("limit_reached", start)
				return fs.SkipAll
			}
			if entry.IsDir() {
				if entry.Name() == ".git" || entry.Name() == "node_modules" || entry.Name() == ".venv" || entry.Name() == "__pycache__" {
					return fs.SkipDir
				}
				skillPath := filepath.Join(path, "SKILL.md")
				if info, statErr := os.Lstat(skillPath); statErr == nil && info.Mode().IsRegular() {
					if !seen[skillPath] {
						seen[skillPath] = true
						result = append(result, PluginSkillAsset{Name: filepath.Base(path), Path: skillPath})
					}
					return fs.SkipDir
				}
				rel, _ := filepath.Rel(start, path)
				if strings.Count(rel, string(filepath.Separator)) > 4 {
					c.issue("limit_reached", path)
					return fs.SkipDir
				}
				return nil
			}
			if entry.Type()&os.ModeSymlink != 0 {
				if c.componentPath(root, path) != "" {
					c.issue("symlink_skipped", path)
				}
				return nil
			}
			if entry.Name() == "SKILL.md" && !seen[path] {
				seen[path] = true
				result = append(result, PluginSkillAsset{Name: filepath.Base(filepath.Dir(path)), Path: path})
			}
			return nil
		})
	}
	return result
}

func (c *assetCollector) addPlugin(root, name, state, scope, source string, enabled *bool) {
	if len(c.result.Plugins) >= assetLimit {
		c.issue("limit_reached", source)
		return
	}
	if root != "" {
		root = filepath.Clean(root)
		if actual, err := filepath.EvalSymlinks(root); err == nil {
			root = actual
		}
	}
	key := root + "\x00" + scope
	if root == "" {
		key = name + "\x00" + source + "\x00" + scope
	}
	if _, exists := c.seenPlugin[key]; exists {
		return
	}
	item := PluginAsset{ID: assetID(key), Name: name, State: state, Scope: scope, SourcePath: source, Path: root, Enabled: enabled, Format: "unknown", Skills: []PluginSkillAsset{}, MCPServers: []MCPAsset{}}
	var manifest map[string]any
	if root != "" {
		for _, candidate := range pluginManifests {
			path := c.componentPath(root, candidate.path)
			if path == "" {
				continue
			}
			if data := c.read(path); data != nil {
				manifest, item.Format = data, candidate.format
				if value := assetString(data["name"]); value != "" {
					item.Name = value
				} else if value := assetString(data["id"]); value != "" {
					item.Name = value
				}
				item.Version = assetString(data["version"])
				break
			}
		}
		if info, err := os.Stat(root); err != nil || !info.IsDir() {
			c.issue("plugin_missing", root)
		} else {
			item.Skills = c.pluginSkills(root, manifest)
			mcpFiles := []string{".mcp.json", "mcp.json"}
			mcpFiles = append(mcpFiles, assetPaths(manifest["mcpServers"])...)
			seen := map[string]bool{}
			for _, relative := range mcpFiles {
				path := c.componentPath(root, relative)
				if path == "" || seen[path] {
					continue
				}
				seen[path] = true
				item.MCPServers = append(item.MCPServers, c.mcps(c.read(path), path, scope)...)
			}
			if servers := assetObject(manifest["mcpServers"]); servers != nil {
				item.MCPServers = append(item.MCPServers, c.mcps(map[string]any{"mcpServers": servers}, source, scope)...)
			}
			if item.Format == "codex" || item.Format == "agent_plugins" {
				openai := assetObject(assetObject(manifest["extensions"])["com.openai"])
				appFiles := append([]string{".app.json"}, assetPaths(manifest["apps"])...)
				appFiles = append(appFiles, assetPaths(openai["apps"])...)
				for _, relative := range appFiles {
					path := c.componentPath(root, relative)
					if path == "" || seen[path] {
						continue
					}
					seen[path] = true
					apps := assetObject(c.read(path)["apps"])
					for _, name := range assetKeys(apps) {
						if len(item.MCPServers) >= assetLimit {
							c.issue("limit_reached", path)
							break
						}
						id := assetString(assetObject(apps[name])["id"])
						if id != "" {
							item.MCPServers = append(item.MCPServers, MCPAsset{ID: assetID(path, scope, name), Name: name, ServerReference: id, Transport: "registered", Scope: scope, SourcePath: path, CredentialKeys: []string{}})
						}
					}
				}
			}
			if len(item.MCPServers) > assetLimit {
				item.MCPServers = item.MCPServers[:assetLimit]
				c.issue("limit_reached", root)
			}
		}
	}
	if item.Name == "" {
		item.Name = filepath.Base(root)
	}
	c.seenPlugin[key] = len(c.result.Plugins)
	c.result.Plugins = append(c.result.Plugins, item)
}

func (c *assetCollector) discoverPlugins(root, kind string, config map[string]any, configPath string, projects map[string]bool) {
	enabledPlugins := assetObject(config["enabledPlugins"])
	registryPath := filepath.Join(root, "plugins", "installed_plugins.json")
	registry := c.read(registryPath)
	for _, id := range assetKeys(assetObject(registry["plugins"])) {
		value := assetObject(registry["plugins"])[id]
		entries, ok := value.([]any)
		if !ok {
			entries = []any{value}
		}
		for _, raw := range entries {
			entry := assetObject(raw)
			path := assetString(entry["installPath"])
			if path == "" || !filepath.IsAbs(path) {
				c.issue("invalid_config", registryPath)
				continue
			}
			scope := assetString(entry["scope"])
			if scope == "" {
				scope = "user"
			}
			project := assetString(entry["projectPath"])
			if (scope == "project" || scope == "local") && filepath.IsAbs(project) {
				scope = project
				if len(projects) < assetLimit {
					projects[project] = true
				} else {
					c.issue("limit_reached", registryPath)
				}
			}
			enabled := assetBool(enabledPlugins[id])
			if scope != "user" && scope != "managed" {
				enabled = nil
			}
			if filepath.IsAbs(scope) {
				settings := c.read(filepath.Join(scope, filepath.Base(root), "settings.json"))
				local := c.read(filepath.Join(scope, filepath.Base(root), "settings.local.json"))
				if value := assetBool(assetObject(settings["enabledPlugins"])[id]); value != nil {
					enabled = value
				}
				if value := assetBool(assetObject(local["enabledPlugins"])[id]); value != nil {
					enabled = value
				}
			}
			c.addPlugin(path, id, "installed", scope, registryPath, enabled)
		}
	}
	if kind == "codex" {
		c.codexPlugins(root, config, configPath)
	}
	if kind == "opencode" {
		for _, reference := range assetPaths(config["plugin"]) {
			path := ""
			if strings.HasPrefix(reference, "file://") {
				path = strings.TrimPrefix(reference, "file://")
			} else if filepath.IsAbs(reference) {
				path = reference
			}
			if path != "" {
				c.addCodePlugin(path, configPath)
			} else {
				c.addPlugin("", safePackageReference(reference), "configured", "user", configPath, nil)
			}
		}
		entries, err := os.ReadDir(filepath.Join(root, "plugins"))
		if err != nil && !os.IsNotExist(err) {
			c.issue("read_failed", filepath.Join(root, "plugins"))
		}
		for _, entry := range entries {
			if !entry.IsDir() && (strings.HasSuffix(entry.Name(), ".js") || strings.HasSuffix(entry.Name(), ".ts")) {
				c.addCodePlugin(filepath.Join(root, "plugins", entry.Name()), configPath)
			}
		}
	}
	if kind == "openclaw" {
		plugins := assetObject(config["plugins"])
		for _, name := range assetKeys(assetObject(plugins["installs"])) {
			entry := assetObject(assetObject(plugins["installs"])[name])
			path := assetString(entry["installPath"])
			if filepath.IsAbs(path) {
				c.addPlugin(path, name, "installed", "user", configPath, assetBool(assetObject(assetObject(plugins["entries"])[name])["enabled"]))
			}
		}
		for _, path := range assetPaths(assetObject(plugins["load"])["paths"]) {
			if filepath.IsAbs(path) {
				c.addPlugin(path, filepath.Base(path), "configured", "user", configPath, nil)
			}
		}
	}
	// Cache directories can outlive installation. Their state remains cached.
	c.walkPluginRoots(filepath.Join(root, "plugins", "cache"), 4, "cached")
	if kind == "gemini" || kind == "openclaw" {
		c.walkPluginRoots(filepath.Join(root, "extensions"), 1, "local")
	}
	// Local plugin directories are also used by manually unpacked bundles.
	c.walkPluginRoots(filepath.Join(root, "plugins"), 1, "local")
}

func safePackageReference(value string) string {
	if strings.Contains(value, "://") {
		return assetOrigin(value)
	}
	if len(value) > 512 {
		return ""
	}
	return value
}
func (c *assetCollector) addCodePlugin(path, source string) {
	if len(c.result.Plugins) >= assetLimit {
		c.issue("limit_reached", source)
		return
	}
	key := path + "\x00user"
	if _, exists := c.seenPlugin[key]; exists {
		return
	}
	if info, err := os.Stat(path); err != nil || !info.Mode().IsRegular() {
		c.issue("plugin_missing", path)
		return
	}
	c.seenPlugin[key] = len(c.result.Plugins)
	c.result.Plugins = append(c.result.Plugins, PluginAsset{ID: assetID(key), Name: filepath.Base(path), Format: "opencode", Path: path, SourcePath: source, Scope: "user", State: "local", Skills: []PluginSkillAsset{}, MCPServers: []MCPAsset{}})
}

func (c *assetCollector) walkPluginRoots(start string, maxDepth int, state string) {
	if _, err := os.Stat(start); os.IsNotExist(err) {
		return
	}
	visited := 0
	_ = filepath.WalkDir(start, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			c.issue("read_failed", path)
			return nil
		}
		visited++
		if visited > 2048 || len(c.result.Plugins) >= assetLimit {
			c.issue("limit_reached", start)
			return fs.SkipAll
		}
		if !entry.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(start, path)
		if rel != "." && strings.Count(rel, string(filepath.Separator)) >= maxDepth {
			return fs.SkipDir
		}
		for _, manifest := range pluginManifests {
			if info, err := os.Stat(filepath.Join(path, manifest.path)); err == nil && info.Mode().IsRegular() {
				c.addPlugin(path, entry.Name(), state, "user", filepath.Join(path, manifest.path), nil)
				return fs.SkipDir
			}
		}
		return nil
	})
}

func (c *assetCollector) codexPlugins(root string, config map[string]any, configPath string) {
	for _, id := range assetKeys(assetObject(config["plugins"])) {
		entry := assetObject(assetObject(config["plugins"])[id])
		enabled := assetBool(entry["enabled"])
		name, marketplace, _ := strings.Cut(id, "@")
		source := assetObject(assetObject(config["marketplaces"])[marketplace])
		directory := assetString(source["source"])
		found := false
		if source["source_type"] == "local" && filepath.IsAbs(directory) {
			catalog := c.read(filepath.Join(directory, ".agents/plugins/marketplace.json"))
			entries, _ := catalog["plugins"].([]any)
			for _, value := range entries {
				plugin := assetObject(value)
				if plugin["name"] != name {
					continue
				}
				location := assetObject(plugin["source"])
				relative := assetString(location["path"])
				if location["source"] == "local" && relative != "" {
					path := filepath.Join(directory, relative)
					if filepath.IsAbs(relative) {
						path = relative
					}
					c.addPlugin(path, name, "configured", "user", configPath, enabled)
					found = true
					break
				}
			}
		}
		if !found {
			// Codex cache is marketplace / plugin / version. Keep each cached
			// version as evidence; configuration alone cannot select the active one.
			matches, _ := filepath.Glob(filepath.Join(root, "plugins/cache", filepath.Base(marketplace), filepath.Base(name), "*"))
			sort.Strings(matches)
			for _, path := range matches {
				if info, err := os.Stat(path); err == nil && info.IsDir() {
					c.addPlugin(path, name, "cached", "user", configPath, enabled)
					found = true
				}
			}
		}
		if !found {
			c.addPlugin("", name, "configured", "user", configPath, enabled)
		}
	}
}
