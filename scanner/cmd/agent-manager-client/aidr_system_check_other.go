//go:build !darwin

package main

import (
	"context"
	"time"
)

func systemPreflight(context.Context) systemPrerequisites {
	return systemPrerequisites{Version: 1, Code: "aidr_system_platform_unsupported", CheckedAt: time.Now().UTC().Format(time.RFC3339Nano), Components: []systemComponentCheck{}, ESAuthorization: "unknown", ESSubscription: "unknown"}
}
