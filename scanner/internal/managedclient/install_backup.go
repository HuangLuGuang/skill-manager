package managedclient

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// Retain the exact pre-install content in the existing Agent backup layout.
// A failed copy or a concurrent edit prevents the caller from replacing it.
func retainInstallBackup(home, source, originalPath, agentType, skillName, policyVersion string) (string, error) {
	if !validInstallComponent(agentType) || !validInstallComponent(skillName) {
		return "", fmt.Errorf("invalid install identifier")
	}
	before, err := inspectInstallTarget(source)
	if err != nil {
		return "", err
	}
	resolved, err := filepath.EvalSymlinks(source)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(BackupsRoot(home), 0700); err != nil {
		return "", err
	}
	root, err := os.MkdirTemp(BackupsRoot(home), "install-"+time.Now().UTC().Format("20060102T150405Z")+"-")
	if err != nil {
		return "", err
	}
	retained := false
	defer func() {
		if !retained {
			_ = removeOwnedCopy(root)
		}
	}()
	copyPath := filepath.Join(root, agentType, skillName)
	if err := copyRecoveryTree(resolved, copyPath); err != nil {
		return "", err
	}
	if err := checkObservedContent(Skill{Path: copyPath, Signature: before.signature}); err != nil {
		return "", err
	}
	if err := checkInstallTarget(source, map[string]installTargetState{source: before}); err != nil {
		return "", err
	}
	metadata, err := json.Marshal(map[string]any{
		"source_path": resolved, "original_path": originalPath, "agent_type": agentType,
		"skill_name": skillName, "signature": before.signature, "policy_version": policyVersion,
		"reason": "before_install", "created_at": time.Now().UTC().Format(time.RFC3339Nano),
	})
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(root, "metadata.json"), metadata, 0600); err != nil {
		return "", err
	}
	retained = true
	return root, nil
}
