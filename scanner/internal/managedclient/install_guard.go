package managedclient

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"skill-manager/scanner/internal/manifest"
)

// Package identifiers become directory names on every supported client OS.
func validInstallComponent(value string) bool {
	return value != "" && value != "." && value != ".." &&
		!strings.ContainsAny(value, "/\\:\x00") && !filepath.IsAbs(value)
}

type installTargetState struct {
	failed    bool
	signature string
	link      string
	mode      os.FileMode
}

func captureInstallTargets(root string) (map[string]installTargetState, error) {
	entries, err := os.ReadDir(root)
	if os.IsNotExist(err) {
		return map[string]installTargetState{}, nil
	}
	if err != nil {
		return nil, err
	}
	result := make(map[string]installTargetState, len(entries))
	for _, entry := range entries {
		path := filepath.Join(root, entry.Name())
		state, err := inspectInstallTarget(path)
		if err != nil {
			state.failed = true
		}
		result[path] = state
	}
	return result, nil
}

func inspectInstallTarget(path string) (installTargetState, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return installTargetState{}, err
	}
	state := installTargetState{mode: info.Mode().Type()}
	if info.Mode()&os.ModeSymlink != 0 {
		state.link, err = os.Readlink(path)
		if err != nil {
			return state, err
		}
		if _, err := os.Stat(path); os.IsNotExist(err) {
			return state, nil
		}
	}
	if info.IsDir() || state.link != "" {
		resolved, err := filepath.EvalSymlinks(path)
		if err != nil {
			return state, err
		}
		value, err := manifest.Build(resolved, DefaultManifestOptions())
		if err != nil {
			return state, err
		}
		state.signature = manifest.ContentSignature(value.Files)
	}
	return state, nil
}

func checkInstallTarget(path string, targets map[string]installTargetState) error {
	before, existed := targets[path]
	after, err := inspectInstallTarget(path)
	if !existed && os.IsNotExist(err) {
		return nil
	}
	if err != nil || !existed || before.failed || before != after {
		return fmt.Errorf("skill_content_changed")
	}
	return nil
}

func removeInstallAlias(path string, before map[string]installTargetState) error {
	expected, exists := before[path]
	if exists && expected.link != "" {
		// The installed release may have changed; the alias itself must still match.
		link, err := os.Readlink(path)
		if err != nil || link != expected.link {
			return fmt.Errorf("skill_content_changed")
		}
		return os.Remove(path)
	}
	if err := checkInstallTarget(path, before); err != nil {
		return err
	}
	return os.RemoveAll(path)
}

func checkQueuedInstallTarget(path, root string, payload map[string]any) error {
	if expected := stringValue(payload, "expected_path"); expected != "" && expected != path {
		return fmt.Errorf("skill_target_unavailable")
	}
	value, bound := payload["expected_targets"]
	if !bound {
		return nil // Tasks issued before content binding retain their original contract.
	}
	targets, ok := value.(map[string]any)
	if !ok || stringValue(payload, "expected_root") != root {
		return fmt.Errorf("skill_target_unavailable")
	}
	current, err := inspectInstallTarget(path)
	expected, existed := targets[path]
	if !existed && os.IsNotExist(err) {
		return nil
	}
	signature, valid := expected.(string)
	if err != nil || !existed || !valid || signature == "" || current.signature != signature {
		return fmt.Errorf("skill_content_changed")
	}
	return nil
}
