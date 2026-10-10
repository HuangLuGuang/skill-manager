package hooks

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
)

//go:embed bundle.json
var bundledPlugins []byte

const BundledPluginVersion = "0.1.2"

// BundledSource uses the same declared resources as the desktop package. It
// also lets the existing background client install without a running window.
func BundledSource(root string) (string, error) {
	if !filepath.IsAbs(root) {
		return "", code("aidr_plugin_package_invalid")
	}
	realRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return "", code("aidr_plugin_package_invalid")
	}
	root = realRoot
	sum := sha256.Sum256(bundledPlugins)
	dir := filepath.Join(root, "bundled-"+hex.EncodeToString(sum[:16]))
	var files map[string]string
	if json.Unmarshal(bundledPlugins, &files) != nil {
		return "", code("aidr_plugin_package_invalid")
	}
	if _, err := os.Lstat(dir); os.IsNotExist(err) {
		stage, err := os.MkdirTemp(root, ".bundle-")
		if err != nil {
			return "", err
		}
		defer os.RemoveAll(stage)
		for name, body := range files {
			p := filepath.Join(stage, name)
			if err = os.MkdirAll(filepath.Dir(p), 0700); err != nil {
				return "", err
			}
			if err = os.WriteFile(p, []byte(body), 0600); err != nil {
				return "", err
			}
		}
		if err = os.Rename(stage, dir); err != nil {
			return "", err
		}
	} else if err != nil {
		return "", err
	}
	for name, body := range files {
		p := filepath.Join(dir, name)
		real, err := filepath.EvalSymlinks(p)
		if err != nil || real != p {
			return "", code("aidr_plugin_package_invalid")
		}
		f, err := os.Open(p)
		if err != nil {
			return "", code("aidr_plugin_package_invalid")
		}
		got, err := io.ReadAll(io.LimitReader(f, int64(len(body)+1)))
		f.Close()
		if err != nil || !bytes.Equal(got, []byte(body)) {
			return "", code("aidr_plugin_package_invalid")
		}
	}
	return dir, nil
}
