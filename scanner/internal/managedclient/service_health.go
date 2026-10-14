package managedclient

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/runtimeinfo"
	"strings"
	"time"
)

type daemonHealth struct {
	Runtime   runtimeinfo.Info `json:"runtime"`
	PID       int              `json:"pid"`
	UpdatedAt time.Time        `json:"updated_at"`
}

func writeDaemonHealth(home string) error {
	body, err := json.Marshal(daemonHealth{Runtime: runtimeinfo.Current(), PID: os.Getpid(), UpdatedAt: time.Now().UTC()})
	if err != nil {
		return err
	}
	return atomicWriteFile(filepath.Join(RuntimeRoot(home), "daemon-health.json"), body, 0600)
}

func daemonIsReady(home string) bool {
	body, err := os.ReadFile(filepath.Join(RuntimeRoot(home), "daemon-health.json"))
	var health daemonHealth
	if err != nil || json.Unmarshal(body, &health) != nil || health.PID <= 0 {
		return false
	}
	age := time.Since(health.UpdatedAt)
	if age < 0 || age > 5*time.Second || !clientProcessAlive(health.PID) {
		return false
	}
	lock, err := os.ReadFile(filepath.Join(RuntimeRoot(home), "client.lock"))
	if err != nil || strings.TrimSpace(string(lock)) != fmt.Sprintf("v2 %d", health.PID) {
		return false
	}
	file, err := os.OpenFile(filepath.Join(RuntimeRoot(home), "client.lock"), os.O_RDWR, 0)
	if err != nil {
		return false
	}
	defer file.Close()
	err = lockClientFile(file)
	if err == nil {
		_ = unlockClientFile(file)
		return false
	}
	return errors.Is(err, ErrAlreadyRunning)
}

// ServiceRuntimeStatus is for diagnostics; lifecycle decisions still use the
// OS registration plus the independently checked readiness marker.
func ServiceRuntimeStatus(home string) map[string]any {
	state := ServiceStatus(home)
	health := "unavailable"
	var h daemonHealth
	raw, _ := os.ReadFile(filepath.Join(RuntimeRoot(home), "daemon-health.json"))
	_ = json.Unmarshal(raw, &h)
	var running *runtimeinfo.Info
	if daemonIsReady(home) {
		health = "healthy"
		if h.Runtime.PID == h.PID {
			running = &h.Runtime
		}
	}
	return map[string]any{"installed": state.Installed, "running": state.Running, "detail": state.Detail, "health": health, "runtime": running}
}
