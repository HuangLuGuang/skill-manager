package hooks

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// BuildMarketplace exports only the product's declared plugin files. The result
// contains no user settings, credentials, model configuration or host trust.
func BuildMarketplace(source, destination string) (map[string]string, error) {
	return BuildConnectedMarketplace(source, destination, "", "")
}

// Connected packages contain stable paths, never device credentials.
func BuildConnectedMarketplace(source, destination, binary, connection string) (map[string]string, error) {
	if (binary != "" || connection != "") && (!filepath.IsAbs(binary) || !filepath.IsAbs(connection)) {
		return nil, code("aidr_plugin_package_invalid")
	}
	if !filepath.IsAbs(source) || !filepath.IsAbs(destination) {
		return nil, code("aidr_plugin_package_invalid")
	}
	files := map[string][]byte{}
	hashes := map[string]string{}
	for _, host := range []string{"codex", "claude"} {
		name := "aidr-" + host
		manifest := "." + host + "-plugin/plugin.json"
		for _, relative := range []string{manifest, "hooks/hooks.json", "scripts/bridge.sh"} {
			path := filepath.Join(source, name, relative)
			real, err := filepath.EvalSymlinks(path)
			if err != nil || real != path {
				return nil, code("aidr_plugin_package_unreadable")
			}
			f, err := os.Open(path)
			if err != nil {
				return nil, code("aidr_plugin_package_unreadable")
			}
			info, err := f.Stat()
			if err != nil || !info.Mode().IsRegular() {
				f.Close()
				return nil, code("aidr_plugin_package_invalid")
			}
			data, err := io.ReadAll(io.LimitReader(f, 256*1024+1))
			f.Close()
			if err != nil || len(data) > 256*1024 {
				return nil, code("aidr_plugin_package_invalid")
			}
			if relative == manifest {
				var m struct {
					Name    string `json:"name"`
					Version string `json:"version"`
				}
				if json.Unmarshal(data, &m) != nil || m.Name != name || m.Version != BundledPluginVersion {
					return nil, code("aidr_plugin_package_invalid")
				}
			}
			key := filepath.ToSlash(filepath.Join("plugins", name, relative))
			if relative == "scripts/bridge.sh" && connection != "" {
				data = []byte("#!/bin/sh\nset -eu\nif [ ! -x " + shellQuote(binary) + " ]; then\n  if [ \"${1:-}\" = PreToolUse ]; then\n    printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"aidr_hook_binary_unavailable\"}}'\n    exit 0\n  fi\n  printf '%s\\n' aidr_hook_binary_unavailable >&2\n  exit 1\nfi\nexec " + shellQuote(binary) + " aidr-hook --connection-file " + shellQuote(connection) + " --agent " + host + " --event \"$1\"\n")
			}
			files[key] = data
		}
	}
	files[".agents/plugins/marketplace.json"] = []byte(`{"name":"aidr-local","interface":{"displayName":"Agent Manager AIDR"},"plugins":[{"name":"aidr-codex","source":{"source":"local","path":"./plugins/aidr-codex"},"policy":{"installation":"AVAILABLE","authentication":"ON_INSTALL"},"category":"Developer Tools"}]}`)
	files[".claude-plugin/marketplace.json"] = []byte(`{"name":"aidr-local","owner":{"name":"Agent Manager"},"plugins":[{"name":"aidr-claude","source":"./plugins/aidr-claude"}]}`)
	for name, data := range files {
		sum := sha256.Sum256(data)
		hashes[name] = hex.EncodeToString(sum[:])
	}
	metadata, _ := json.Marshal(struct {
		Schema int               `json:"schema"`
		Files  map[string]string `json:"files"`
	}{1, hashes})
	files["aidr-package.json"] = metadata
	// Build into a new sibling and rename only after every file is complete.
	parent := filepath.Dir(destination)
	real, err := filepath.EvalSymlinks(parent)
	if err != nil || parent != real {
		return nil, code("aidr_plugin_package_invalid")
	}
	if _, err = os.Lstat(destination); !os.IsNotExist(err) {
		return nil, code("aidr_plugin_package_exists")
	}
	stage, err := os.MkdirTemp(parent, ".aidr-package-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(stage)
	for name, data := range files {
		path := filepath.Join(stage, name)
		if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return nil, err
		}
		if err = os.WriteFile(path, data, 0600); err != nil {
			return nil, err
		}
	}
	if err = os.Rename(stage, destination); err != nil {
		return nil, err
	}
	return hashes, nil
}

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

// Verify the immutable package before reusing its native marketplace path.
func VerifyMarketplace(directory string) error {
	f, err := os.Open(filepath.Join(directory, "aidr-package.json"))
	if err != nil {
		return code("aidr_plugin_package_unreadable")
	}
	body, err := io.ReadAll(io.LimitReader(f, 65537))
	f.Close()
	var metadata struct {
		Schema int               `json:"schema"`
		Files  map[string]string `json:"files"`
	}
	if err != nil || len(body) > 65536 || json.Unmarshal(body, &metadata) != nil || metadata.Schema != 1 || len(metadata.Files) != 8 {
		return code("aidr_plugin_package_invalid")
	}
	for name, digest := range metadata.Files {
		allowed := name == ".agents/plugins/marketplace.json" || name == ".claude-plugin/marketplace.json"
		for _, host := range []string{"claude", "codex"} {
			for _, rel := range []string{"." + host + "-plugin/plugin.json", "hooks/hooks.json", "scripts/bridge.sh"} {
				allowed = allowed || name == "plugins/aidr-"+host+"/"+rel
			}
		}
		path := filepath.Join(directory, filepath.FromSlash(name))
		real, e := filepath.EvalSymlinks(path)
		if !allowed || e != nil || real != path {
			return code("aidr_plugin_package_invalid")
		}
		f, e := os.Open(path)
		if e != nil {
			return code("aidr_plugin_package_unreadable")
		}
		data, e := io.ReadAll(io.LimitReader(f, 256*1024+1))
		f.Close()
		sum := sha256.Sum256(data)
		if e != nil || len(data) > 256*1024 || hex.EncodeToString(sum[:]) != digest {
			return code("aidr_plugin_package_invalid")
		}
	}
	return nil
}
