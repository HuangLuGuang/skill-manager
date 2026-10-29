package managedclient

import (
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

func (c *assetCollector) codeBuddyProjects(home string) []string {
	var projects []string
	seen := map[string]bool{}
	for _, app := range []string{"CodeBuddy CN", "CodeBuddy"} {
		root := filepath.Join(home, "Library/Application Support", app, "User/workspaceStorage")
		f, err := os.Open(root)
		if err != nil {
			continue
		}
		names, _ := f.Readdirnames(assetLimit + 1)
		f.Close()
		if len(names) > assetLimit {
			c.issue("limit_reached", root)
			names = names[:assetLimit]
		}
		for _, name := range names {
			data := c.read(filepath.Join(root, name, "workspace.json"))
			u, err := url.Parse(assetString(data["folder"]))
			if err != nil || u.Scheme != "file" || u.Host != "" || !filepath.IsAbs(u.Path) {
				continue
			}
			path := filepath.Clean(u.Path)
			if !seen[path] {
				seen[path] = true
				projects = append(projects, path)
			}
		}
	}
	return projects
}

func (c *assetCollector) codeBuddyPlugins(root string, config map[string]any, source, scope string) {
	markets := c.read(filepath.Join(root, "plugins/known_marketplaces.json"))
	catalogs := map[string]map[string]any{}
	for _, id := range assetKeys(assetObject(config["enabledPlugins"])) {
		name, market, ok := strings.Cut(id, "@")
		enabled := assetBool(assetObject(config["enabledPlugins"])[id])
		if !ok || name == "" || enabled == nil {
			c.issue("invalid_config", source)
			continue
		}
		location := assetString(assetObject(markets[market])["installLocation"])
		path := ""
		if filepath.IsAbs(location) {
			catalog, exists := catalogs[market]
			if !exists {
				catalog = c.read(filepath.Join(location, ".codebuddy-plugin/marketplace.json"))
				catalogs[market] = catalog
			}
			entries, _ := catalog["plugins"].([]any)
			for _, raw := range entries {
				entry := assetObject(raw)
				if entry["name"] != name {
					continue
				}
				relative := assetString(entry["source"])
				if relative != "" && !strings.Contains(relative, "://") {
					path = c.componentPath(location, relative)
				}
				break
			}
		}
		state := "installed"
		if path == "" {
			state = "configured"
			c.issue("plugin_missing", source)
		}
		c.addPlugin(path, id, state, scope, source, enabled)
	}
}
