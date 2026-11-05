package managedclient

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"time"
)

func (c *assetCollector) zcodeProjects(home string) []string {
	path := filepath.Join(home, ".zcode/cli/db/db.sqlite")
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return nil
	}
	if resolved != path {
		c.issue("read_failed", path)
		return nil
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		if info, e := os.Lstat(path + suffix); e == nil && !info.Mode().IsRegular() {
			c.issue("read_failed", path)
			return nil
		}
	}
	db, err := sql.Open("sqlite", sqliteURI(path, "mode=ro&_pragma=query_only(1)&_pragma=busy_timeout(100)"))
	if err != nil {
		return nil
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	rows, err := db.QueryContext(ctx, "SELECT DISTINCT directory FROM session WHERE time_deleted IS NULL ORDER BY directory LIMIT ?", assetLimit+1)
	if err != nil {
		c.issue("read_failed", path)
		return nil
	}
	defer rows.Close()
	var result []string
	for rows.Next() {
		var p string
		if rows.Scan(&p) != nil {
			break
		}
		if len(result) >= assetLimit {
			c.issue("limit_reached", path)
			break
		}
		if filepath.IsAbs(p) && len(p) <= 2048 {
			result = append(result, p)
		}
	}
	if rows.Err() != nil {
		c.issue("read_failed", path)
	}
	return result
}

func (c *assetCollector) zcodeConfig(path, scope string) {
	config := c.read(path)
	c.addMCP(map[string]any{"mcpServers": assetObject(config["mcp"])["servers"]}, path, scope)
	plugins := assetObject(config["plugins"])
	for _, dir := range assetPaths(plugins["dirs"]) {
		if !filepath.IsAbs(dir) {
			c.issue("invalid_config", path)
			continue
		}
		c.addPlugin(dir, filepath.Base(dir), "configured", scope, path, assetBool(plugins["enabled"]))
	}
}

func (c *assetCollector) discoverZcode(home string) {
	c.result.MCPSupported, c.result.PluginSupported = true, true
	path := filepath.Join(home, ".zcode/cli/config.json")
	c.zcodeConfig(path, "user")
	config := c.read(path)
	plugins := assetObject(config["plugins"])
	enabled := assetObject(plugins["enabledPlugins"])
	registry := filepath.Join(home, ".zcode/cli/plugins/installed_plugins.json")
	entries, _ := c.read(registry)["plugins"].([]any)
	for _, raw := range entries {
		item := assetObject(raw)
		id := assetString(item["id"])
		dir := assetString(item["installPath"])
		if id == "" || !filepath.IsAbs(dir) {
			c.issue("invalid_config", registry)
			continue
		}
		active := assetBool(enabled[id])
		if global := assetBool(plugins["enabled"]); global != nil && !*global {
			active = global
		}
		scope := assetString(item["scope"])
		c.addPlugin(dir, id, "installed", scope, registry, active)
	}
	for _, project := range c.zcodeProjects(home) {
		c.zcodeConfig(filepath.Join(project, "zcode.json"), project)
		c.zcodeConfig(filepath.Join(project, ".zcode/config.json"), project)
	}
}
