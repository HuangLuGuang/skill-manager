package managedclient

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

func notificationForEvent(eventType, agentType, skillName string, details map[string]any) (LocalNotification, bool) {
	agent := agentDisplayName(agentType)
	target := fmt.Sprintf("%s 的 Skill %s", agent, skillName)
	result := LocalNotification{Severity: "warning", EventType: eventType, AgentType: agentType, SkillName: skillName}
	switch eventType {
	case "skill_repaired":
		result.Severity = "info"
		result.Title = "Skill 已自动恢复"
		result.Message = target + "发生内容变化，已恢复为平台批准版本。"
	case "skill_quarantined":
		result.Severity = "critical"
		result.Title = "Skill 已隔离"
		result.Message = target + "未通过完整性或准入校验，已移出 Agent 目录。"
	case "skill_modified":
		mode := stringDetail(details, "mode")
		offline, _ := details["offline"].(bool)
		if mode != "audit" && !offline {
			return LocalNotification{}, false
		}
		result.Title = "发现 Skill 内容变化"
		if offline {
			result.Message = target + "与平台批准版本不一致；平台暂不可达，未执行自动恢复。"
		} else {
			result.Message = target + "与平台批准版本不一致；当前为只审计策略，未自动处置。"
		}
	case "unmanaged_skill_found":
		if stringDetail(details, "mode") == "block" {
			return LocalNotification{}, false
		}
		result.Title = "发现未受管 Skill"
		result.Message = target + "尚未纳入平台治理，当前策略未自动隔离。"
	default:
		return LocalNotification{}, false
	}
	return result, true
}

func DeliverPendingNotifications(store *Store) {
	items, err := store.PendingNotifications(20)
	if err != nil {
		return
	}
	for _, item := range items {
		if err := sendSystemNotification(item.Title, item.Message); err != nil {
			return
		}
		_ = store.MarkNotificationDelivered(item.ID)
	}
}

func sendSystemNotification(title, message string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	var command *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		return fmt.Errorf("macOS notifications are delivered by the desktop app")
	case "linux":
		command = exec.CommandContext(ctx, "notify-send", title, message)
	case "windows":
		script := `$title=[Security.SecurityElement]::Escape($env:AM_NOTIFICATION_TITLE); $message=[Security.SecurityElement]::Escape($env:AM_NOTIFICATION_MESSAGE); $xml=New-Object Windows.Data.Xml.Dom.XmlDocument; $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$message</text></binding></visual></toast>"); [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('River Security').Show([Windows.UI.Notifications.ToastNotification]::new($xml))`
		command = exec.CommandContext(ctx, "powershell", "-NoProfile", "-NonInteractive", "-Command", script)
		command.Env = append(os.Environ(), "AM_NOTIFICATION_TITLE="+title, "AM_NOTIFICATION_MESSAGE="+message)
	default:
		return fmt.Errorf("system notifications are not supported on %s", runtime.GOOS)
	}
	return command.Run()
}

func stringDetail(details map[string]any, key string) string {
	if value, ok := details[key].(string); ok {
		return value
	}
	return ""
}

func agentDisplayName(agentType string) string {
	labels := map[string]string{
		"claude-code": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI",
		"opencode": "OpenCode", "openclaw": "OpenClaw", "hermes": "Hermes",
	}
	if label := labels[agentType]; label != "" {
		return label
	}
	if strings.TrimSpace(agentType) == "" {
		return "当前 Agent"
	}
	return agentType
}
