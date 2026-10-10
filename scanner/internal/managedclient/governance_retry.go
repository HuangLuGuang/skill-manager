package managedclient

import "time"

func automaticFileActionDeferred(value SkillObservation, now time.Time) bool {
	if value.ActionStatus != "failed" {
		return false
	}
	next, err := time.Parse(time.RFC3339Nano, value.NextActionAt)
	return err == nil && now.Before(next)
}

func deferAutomaticFileAction(value *SkillObservation, now time.Time) {
	if value.Action != "quarantine" && value.Action != "uninstall" && value.Action != "restore_trusted" {
		return
	}
	// Persist backoff with the observation so restarts do not repeat a failing
	// copy immediately. New content/action/policy resets it in the patrol.
	if value.ActionFailures < 7 {
		value.ActionFailures++
	}
	delay := 30 * time.Second * time.Duration(1<<uint(value.ActionFailures-1))
	if delay > 30*time.Minute {
		delay = 30 * time.Minute
	}
	value.NextActionAt = now.Add(delay).UTC().Format(time.RFC3339Nano)
}
