package managedclient

import (
	"os"
	"path/filepath"
	"strings"
)

// Installed packages do not establish runtime enablement; connector settings are encrypted.
func (c *assetCollector) discoverQwenWork(home string) {
	c.result.PluginSupported = true
	for _, folder := range []string{"plugins", "plugins-custom"} {
		root := filepath.Join(home, ".qwenworkcn", folder)
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
			if strings.HasPrefix(name, ".") || name == "cache" || name == "marketplaces" {
				continue
			}
			path := filepath.Join(root, name)
			for _, manifest := range []string{".qoder-plugin/plugin.json", ".claude-plugin/plugin.json"} {
				if info, err := os.Lstat(filepath.Join(path, manifest)); err == nil && info.Mode().IsRegular() {
					c.addPlugin(path, name, "installed", "user", filepath.Join(path, manifest), nil)
					break
				}
			}
		}
	}
}
