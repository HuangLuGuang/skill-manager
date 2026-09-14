package managedclient

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// An explicit alternate home is an isolation boundary. Environment overrides
// are interpreted only for the current OS user, never for a staged/test home.
func resolvedModelPath(home, kind, relative string) string {
	spec := modelAdapters[kind]
	current, _ := os.UserHomeDir()
	if filepath.Clean(home) != filepath.Clean(current) {
		root := home
		if actual, err := filepath.EvalSymlinks(home); err == nil {
			root = actual
		}
		return modelJSONPath(kind, filepath.Join(root, relative))
	}
	expand := func(value string) string {
		if strings.HasPrefix(value, "~/") {
			value = filepath.Join(home, value[2:])
		}
		if actual, err := filepath.EvalSymlinks(value); err == nil {
			return actual
		}
		return filepath.Clean(value)
	}
	if kind == "claude-desktop" && runtime.GOOS == "windows" {
		root := os.Getenv("LOCALAPPDATA")
		if root == "" {
			root = filepath.Join(home, "AppData", "Local")
		}
		path, err := desktopWindowsPath(expand(root), strings.TrimPrefix(relative, "AppData/Local/"))
		if err != nil {
			return ""
		}
		return path
	}
	if spec.ConfigFileEnv != "" && relative == spec.Files[0] {
		if value := os.Getenv(spec.ConfigFileEnv); value != "" {
			return expand(value)
		}
	}
	if spec.ConfigRootEnv != "" {
		if root := os.Getenv(spec.ConfigRootEnv); root != "" {
			suffix := strings.TrimPrefix(strings.TrimPrefix(relative, spec.ConfigRootPrefix), "/")
			return modelJSONPath(kind, filepath.Join(expand(root), filepath.FromSlash(suffix)))
		}
	}
	root := home
	if actual, err := filepath.EvalSymlinks(home); err == nil {
		root = actual
	}
	return modelJSONPath(kind, filepath.Join(root, relative))
}

func desktopWindowsPath(localData, relative string) (string, error) {
	parts := strings.SplitN(filepath.ToSlash(relative), "/", 2)
	if len(parts) != 2 || (parts[0] != "Claude" && parts[0] != "Claude-3p") {
		return "", errors.New("model_config.invalid_path")
	}
	directory := filepath.Join(localData, parts[0])
	if info, err := os.Stat(directory); err == nil && info.IsDir() {
		return filepath.Join(directory, filepath.FromSlash(parts[1])), nil
	}
	entries, err := os.ReadDir(localData)
	if err != nil && !os.IsNotExist(err) {
		return "", err
	}
	selected := ""
	for _, entry := range entries {
		if !entry.IsDir() || !strings.HasPrefix(entry.Name(), "Claude") || strings.Contains(entry.Name(), "-3p") != (parts[0] == "Claude-3p") {
			continue
		}
		if selected != "" {
			return "", errors.New("model_config.ambiguous_paths")
		}
		selected = entry.Name()
	}
	if selected != "" {
		directory = filepath.Join(localData, selected)
	}
	return filepath.Join(directory, filepath.FromSlash(parts[1])), nil
}

func modelJSONPath(kind, path string) string {
	if kind == "opencode" && strings.HasSuffix(path, "opencode.json") {
		if _, err := os.Stat(path); os.IsNotExist(err) {
			if _, err := os.Stat(path + "c"); err == nil {
				return path + "c"
			}
		}
	}
	return path
}
