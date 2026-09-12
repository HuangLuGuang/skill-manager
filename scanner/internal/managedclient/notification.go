package managedclient

import (
	"fmt"
	"strings"

	"skill-manager/scanner/internal/localize"
)

func notificationForEvent(eventType, agentType, skillName string, details map[string]any) (LocalNotification, bool) {
	agent := agentDisplayName(agentType)
	target := fmt.Sprintf("%s 的 Skill %s", agent, skillName)
	if agents := stringSliceDetail(details, "affected_agents"); len(agents) > 1 {
		labels := make([]string, 0, len(agents))
		for _, value := range agents {
			labels = append(labels, agentDisplayName(value))
		}
		target = fmt.Sprintf("Skill %s（影响 %s）", skillName, strings.Join(labels, "、"))
	}
	result := LocalNotification{Severity: "warning", EventType: eventType, AgentType: agentType, SkillName: skillName}
	switch eventType {
	case "skill_governance_detected", "skill_governance_action":
		if stringDetail(details, "action") == "record_only" {
			return LocalNotification{}, false
		}
		result.Details = map[string]string{}
		for _, key := range []string{"path", "signature", "trigger", "action", "status", "error_code", "policy_version"} {
			result.Details[key] = stringDetail(details, key)
		}
		result.Title = localize.Text("Skill 分类告警", "Skill Classification Alert")
		if eventType == "skill_governance_action" {
			result.Title = localize.Text("Skill 处置结果", "Skill Remediation Result")
			if stringDetail(details, "status") == "completed" {
				result.Severity = "info"
			}
		}
		if stringDetail(details, "trigger") == "malicious" || stringDetail(details, "status") == "failed" {
			result.Severity = "critical"
		}
		result.Message = fmt.Sprintf(localize.Text("%s：请在 Agent 管理中查看原因和处置状态。", "%s: Review the reason and remediation status in Agent Management."), skillName)
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
		if mode != "audit" && (!offline || mode == "block") {
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

func stringSliceDetail(details map[string]any, key string) []string {
	switch values := details[key].(type) {
	case []string:
		return values
	case []any:
		result := make([]string, 0, len(values))
		for _, value := range values {
			if text, ok := value.(string); ok {
				result = append(result, text)
			}
		}
		return result
	default:
		return nil
	}
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
		"trae-cn": "TRAE CN", "trae": "TRAE", "cursor": "Cursor",
		"global-skills": "共用 Skills", "codebuddy": "CodeBuddy",
	}
	if label := labels[agentType]; label != "" {
		return label
	}
	if strings.TrimSpace(agentType) == "" {
		return "当前 Agent"
	}
	return agentType
}
