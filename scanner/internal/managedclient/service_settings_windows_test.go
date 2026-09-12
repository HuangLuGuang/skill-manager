package managedclient

import (
	"encoding/xml"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func TestWindowsScheduledTaskSettings(t *testing.T) {
	if os.Getenv("AGENT_MANAGER_TEST_SCHEDULER") != "1" {
		t.Skip("set AGENT_MANAGER_TEST_SCHEDULER=1 to verify real Windows Task Scheduler settings")
	}
	name := fmt.Sprintf("AgentManagerClientTest-%d-%d", os.Getpid(), time.Now().UnixNano())
	if output, err := exec.Command("schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", name, "/TR", "cmd.exe /c exit 0").CombinedOutput(); err != nil {
		t.Fatalf("create isolated task: %v %s", err, output)
	}
	defer func() {
		if output, err := exec.Command("schtasks", "/Delete", "/F", "/TN", name).CombinedOutput(); err != nil {
			t.Errorf("remove isolated task: %v %s", err, output)
		}
	}()
	script := strings.ReplaceAll(windowsServiceSettingsScript, "'AgentManagerClient'", "'"+name+"'")
	if output, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", script).CombinedOutput(); err != nil {
		t.Fatalf("configure task: %v %s", err, output)
	}
	output, err := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Export-ScheduledTask -TaskName '"+name+"'").Output()
	if err != nil {
		t.Fatal(err)
	}
	var task struct {
		Settings struct {
			ExecutionTimeLimit         string
			DisallowStartIfOnBatteries bool
			StopIfGoingOnBatteries     bool
			StartWhenAvailable         bool
			MultipleInstancesPolicy    string
			RestartOnFailure           struct {
				Interval string
				Count    int
			}
		}
	}
	// PowerShell emits UTF-8 bytes but Export-ScheduledTask's declaration uses UTF-16.
	text := strings.TrimPrefix(strings.TrimSpace(string(output)), "\ufeff")
	text = strings.Replace(text, `encoding="UTF-16"`, `encoding="UTF-8"`, 1)
	if err := xml.Unmarshal([]byte(text), &task); err != nil {
		t.Fatal(err)
	}
	settings := task.Settings
	if settings.ExecutionTimeLimit != "PT0S" || settings.DisallowStartIfOnBatteries || settings.StopIfGoingOnBatteries || !settings.StartWhenAvailable || settings.MultipleInstancesPolicy != "IgnoreNew" || settings.RestartOnFailure.Interval != "PT1M" || settings.RestartOnFailure.Count != 999 {
		t.Fatalf("scheduler did not retain continuous background settings: %+v", settings)
	}
}
