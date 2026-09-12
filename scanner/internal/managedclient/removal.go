package managedclient

import (
	"context"
	"fmt"
)

func executeRemovalTask(ctx context.Context, home string, policy Policy, api API, store *Store, task Task) error {
	if _, exists, err := store.State(fmt.Sprintf("skill-action-receipt:%d", task.ID)); err != nil || exists {
		return err
	}
	agentType := stringValue(task.Payload, "agent_type")
	skillID := stringValue(task.Payload, "skill_id")
	path := stringValue(task.Payload, "path")
	signature := stringValue(task.Payload, "expected_signature")
	if agentType == "" || skillID == "" {
		return fmt.Errorf("skill_target_unavailable")
	}
	if path == "" && signature == "" {
		installs, err := store.Installations()
		if err != nil {
			return err
		}
		for _, install := range installs {
			if install.AgentType == agentType && install.SkillID == skillID {
				path = install.TargetPath
				signature = install.Manifest.ContentSignature
				break
			}
		}
	}
	if path == "" || signature == "" {
		return fmt.Errorf("skill_content_changed")
	}
	payload := make(map[string]any, len(task.Payload)+3)
	for key, value := range task.Payload {
		payload[key] = value
	}
	payload["action"] = "uninstall"
	payload["path"] = path
	payload["expected_signature"] = signature
	task.Payload = payload
	return executeObservedTask(ctx, home, policy, api, store, task)
}
