package managedclient

import (
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"slices"
)

func traeDataRoot(home, kind string) string {
	app := "Trae"
	if kind == "trae-cn" {
		app = "Trae CN"
	}
	switch runtime.GOOS {
	case "windows":
		return filepath.Join(home, "AppData/Roaming", app)
	case "linux":
		return filepath.Join(home, ".config", app)
	default:
		return filepath.Join(home, "Library/Application Support", app)
	}
}

func (c *assetCollector) traeProjects(home, kind string) []string {
	root := filepath.Join(traeDataRoot(home, kind), "User/workspaceStorage")
	f, err := os.Open(root)
	if err != nil {
		return nil
	}
	names, _ := f.Readdirnames(assetLimit + 1)
	f.Close()
	if len(names) > assetLimit {
		c.issue("limit_reached", root)
		names = names[:assetLimit]
	}
	slices.Sort(names)
	var result []string
	for _, name := range names {
		doc := c.read(filepath.Join(root, name, "workspace.json"))
		u, err := url.Parse(assetString(doc["folder"]))
		if err != nil || u.Scheme != "file" || u.Host != "" || !filepath.IsAbs(u.Path) {
			continue
		}
		project := filepath.Clean(u.Path)
		if !slices.Contains(result, project) {
			result = append(result, project)
		}
	}
	return result
}

func (c *assetCollector) discoverTrae(home, kind string, skillRoots []string) {
	c.result.MCPSupported, c.result.PluginSupported = true, true
	root := filepath.Join(home, "."+kind)
	mcp := filepath.Join(traeDataRoot(home, kind), "User/mcp.json")
	c.addMCP(c.read(mcp), mcp, "user")
	projects := c.traeProjects(home, kind)
	for _, skills := range skillRoots {
		if filepath.Base(filepath.Dir(skills)) == ".trae" && filepath.Dir(skills) != root {
			project := filepath.Dir(filepath.Dir(skills))
			if !slices.Contains(projects, project) {
				projects = append(projects, project)
			}
		}
	}
	for _, project := range projects {
		path := filepath.Join(project, ".trae/mcp.json")
		c.addMCP(c.read(path), path, project)
	}
	source := filepath.Join(root, "installed-plugins.json")
	doc := c.read(source)
	config := c.read(filepath.Join(root, "plugin-config.json"))
	markets, _ := assetObject(doc["data"])["marketplaces"].([]any)
	for _, market := range markets {
		plugins, _ := assetObject(market)["plugins"].([]any)
		for _, raw := range plugins {
			plugin := assetObject(raw)
			id := assetString(plugin["plugin_id"])
			path := assetString(assetObject(plugin["source"])["path"])
			if id == "" {
				c.issue("invalid_config", source)
				continue
			}
			if path != "" {
				path = c.componentPath(root, path)
			}
			state := assetObject(assetObject(config["plugins"])[id])
			enabled := assetBool(state["user_enabled"])
			if origin := assetBool(state["app_origin_enabled"]); origin != nil && !*origin {
				enabled = origin
			}
			status := "installed"
			if path == "" {
				status = "configured"
			}
			c.addPlugin(path, id, status, "user", source, enabled)
		}
	}
	// IDE extensions are separate from Agent plugins and do not carry an
	// inferred runtime enablement state merely because their directory exists.
	extensions := filepath.Join(root, "extensions")
	f, err := os.Open(extensions)
	if err != nil {
		return
	}
	names, _ := f.Readdirnames(assetLimit + 1)
	f.Close()
	slices.Sort(names)
	if len(names) > assetLimit {
		c.issue("limit_reached", extensions)
		names = names[:assetLimit]
	}
	for _, name := range names {
		path := c.componentPath(extensions, name)
		if path == "" {
			continue
		}
		info, err := os.Stat(path)
		if err != nil || !info.IsDir() {
			continue
		}
		manifest := filepath.Join(path, "package.json")
		doc := c.read(manifest)
		id := assetString(doc["publisher"]) + "." + assetString(doc["name"])
		if assetString(doc["name"]) == "" {
			continue
		}
		if len(c.result.Plugins) >= assetLimit {
			c.issue("limit_reached", extensions)
			break
		}
		c.result.Plugins = append(c.result.Plugins, PluginAsset{ID: assetID(path), Name: id, Version: assetString(doc["version"]), State: "installed", Scope: "user", SourcePath: manifest, Path: path, Format: "vscode_extension", Skills: []PluginSkillAsset{}, MCPServers: []MCPAsset{}})
	}
}
