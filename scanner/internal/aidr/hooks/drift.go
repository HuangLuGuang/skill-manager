package hooks

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
)

// Only the three shipped product files are read, never user configuration or
// transcripts. Declared Codex source files are not proof of loaded cache bytes.
func pluginFilesDigest(agent, root string) (string, string) {
	files := []string{"." + agent + "-plugin/plugin.json", "hooks/hooks.json", "scripts/bridge.sh"}
	hashes := map[string]string{}
	for _, name := range files {
		path := filepath.Join(root, name)
		real, err := filepath.EvalSymlinks(path)
		if err != nil || real != filepath.Clean(path) {
			return "", "aidr_plugin_files_unreadable"
		}
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() {
			return "", "aidr_plugin_files_unreadable"
		}
		f, err := os.Open(path)
		if err != nil {
			return "", "aidr_plugin_files_unreadable"
		}
		data, err := io.ReadAll(io.LimitReader(f, 256*1024+1))
		f.Close()
		if err != nil || len(data) > 256*1024 {
			return "", "aidr_plugin_files_unreadable"
		}
		sum := sha256.Sum256(data)
		hashes[name] = hex.EncodeToString(sum[:])
	}
	raw, _ := json.Marshal(hashes)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), "aidr_plugin_files_observed"
}

type PluginDrift struct {
	Code            string   `json:"code"`
	Fields          []string `json:"fields"`
	FilesComparable bool     `json:"files_comparable"`
}

// ComparePluginStatus cannot turn a failed observation into a removal. Callers
// retain the last readable baseline independently from the latest health state.
func ComparePluginStatus(previous, current PluginStatus) PluginDrift {
	d := PluginDrift{Code: "aidr_plugin_drift_unknown", Fields: []string{}}
	if previous.Agent != current.Agent || previous.ScopeDigest != current.ScopeDigest || previous.ConfigurationDigest == "" || current.ConfigurationDigest == "" {
		return d
	}
	if previous.ConfigurationDigest != current.ConfigurationDigest {
		d.Fields = append(d.Fields, "native_configuration")
	}
	if previous.HostVersion != current.HostVersion {
		d.Fields = append(d.Fields, "host_version")
	}
	d.FilesComparable = previous.FilesDigest != "" && current.FilesDigest != "" && previous.SourceKind == current.SourceKind
	if d.FilesComparable && previous.FilesDigest != current.FilesDigest {
		d.Fields = append(d.Fields, "declared_files")
	}
	d.Code = "aidr_plugin_drift_unchanged"
	if len(d.Fields) > 0 {
		d.Code = "aidr_plugin_drift_changed"
	}
	if current.FilesCode == "aidr_plugin_files_unreadable" {
		d.Code = "aidr_plugin_drift_incomplete"
	}
	return d
}
