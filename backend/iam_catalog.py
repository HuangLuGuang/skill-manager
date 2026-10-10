"""Stable permission codes and supported management pages."""

MODULE_ACTIONS = {
    "dashboard": "view",
    "users": "view create update assign_role set_status reset_password delete",
    "groups": "view create update",
    "roles": "view create update grant delete",
    "menus": "view create update sort set_status delete",
    "audit": "login operation security verify",
    "skills": "view create update delete scan approve reject deploy sign",
    "policy": "view update",
    "scans": "view create update execute cancel stop approve raw",
    "schedules": "view create update delete execute",
    "targets": "view create update sync",
    "providers": "view create update delete test",
    "models": "view create update delete",
    "credentials": "view create update delete",
    "privacy": "view create update delete test",
    "privacy_audit": "view raw",
    "mcp": "view create update delete execute approve reject",
    "agents": "view create update delete",
    "clients": "view create update execute read-audit-content",
    "external_gateways": "view create update delete test reveal",
    "runtime": "view create update delete execute",
    "traces": "view raw delete",
    "settings": "view update",
    "tasks": "view create update execute",
    "docs": "view update",
}
PERMISSIONS = {f"{module}:{action}" for module, actions in MODULE_ACTIONS.items() for action in actions.split()}
SENSITIVE_PERMISSIONS = {"privacy_audit:raw", "traces:raw", "scans:raw", "external_gateways:reveal", "clients:read-audit-content"}

# name, parent, Chinese title, English title, path, permission, icon, feature
PAGES = [
    ("dashboard", None, "平台总览", "Overview", "/dashboard", "dashboard:view", "dashboard", None),
    ("capabilities", None, "能力治理", "Capability Governance", None, None, "fileSearch", None),
    ("skill-governance", "capabilities", "Skill 治理", "Skill Governance", None, None, "fileSearch", None),
    ("submit", "skill-governance", "提交 Skill", "Submit Skill", "/submit", "skills:create", "upload", None),
    ("review", "skill-governance", "Skill 审核", "Skill Review", "/review", "skills:view", "checkSquare", None),
    ("skills", "skill-governance", "Skill 列表", "Skills", "/skills", "skills:view", "fileSearch", None),
    ("policy", "skill-governance", "策略配置", "Policy", "/policy", "policy:view", "setting", None),
    ("mcp-governance", "capabilities", "MCP 治理", "MCP Governance", None, None, "api", None),
    ("mcp-servers", "mcp-governance", "MCP 服务", "MCP Servers", "/mcp-governance/servers", "mcp:view", "api", None),
    ("mcp-gateways", "mcp-governance", "MCP 网关", "MCP Gateways", "/mcp-governance/gateways", "mcp:view", "deployment", None),
    ("mcp-approvals", "mcp-governance", "MCP 审批", "MCP Approvals", "/mcp-governance/approvals", "mcp:view", "checkSquare", None),
    ("mcp-debug", "mcp-governance", "MCP 调试", "MCP Debug", "/mcp-governance/debug", "mcp:execute", "safety", None),
    ("mcp-audit", "mcp-governance", "调用审计", "Call Audit", "/mcp-governance/audit", "mcp:view", "audit", None),
    ("agent-management", None, "智能体管理", "Agent Management", None, None, "agent", None),
    ("agents", "agent-management", "智能体列表", "Agents", "/agents", "agents:view", "agent", None),
    ("clients", "agent-management", "客户端管理", "Clients", "/clients", "clients:view", "desktop", None),
    ("external-ai-gateways", "agent-management", "外部 AI 网关", "External AI Gateways", "/external-ai-gateways", "external_gateways:view", "api", None),
    ("credentials", "agent-management", "统一凭证中心", "Credentials", "/credentials", "credentials:view", "key", None),
    ("runtime", "agent-management", "接入与运行", "Integration & Runtime", "/runtime", "runtime:view", "safety", None),
    ("skill-audit", "agent-management", "审计追踪", "Skill Audit", "/audit", "skills:view", "audit", None),
    ("model-gateway", None, "模型网关", "Model Gateway", None, None, "api", None),
    ("providers", "model-gateway", "供应商与模型", "Providers & Models", "/model-gateway/providers", "providers:view", "api", None),
    ("bindings", "model-gateway", "组策略绑定", "Group Policy Bindings", "/model-gateway/policy-bindings", "groups:view", "team", None),
    ("privacy", "model-gateway", "隐私策略", "Privacy Policies", "/model-gateway/policies", "privacy:view", "setting", None),
    ("prompt-guard", "model-gateway", "Prompt 防护测试", "Prompt Guard Test", "/model-gateway/prompt-guard", "privacy:test", "safety", None),
    ("skill-alerts", "model-gateway", "Skill 风险告警", "Skill Risk Alerts", "/model-gateway/skill-alerts", "privacy:view", "safety", None),
    ("privacy-audit", "model-gateway", "隐私审计", "Privacy Audit", "/model-gateway/audit", "privacy_audit:view", "audit", None),
    ("stats", "model-gateway", "Token 压缩统计", "Token Compression", "/model-gateway/stats", "privacy_audit:view", "barChart", None),
    ("user-stats", "model-gateway", "用户 Token 分析", "User Token Analytics", "/model-gateway/user-stats", "privacy_audit:view", "team", None),
    ("pipeline-trace", "model-gateway", "隐私链路追踪", "Pipeline Trace", "/pipeline-trace", "privacy_audit:raw", "audit", None),
    ("scans", None, "安全扫描", "Security Scans", "/agent-security/scans", "scans:view", "fileSearch", "agent_security_scanning"),
    ("traces", None, "调用轨迹", "Runtime Traces", "/runtime-traces", "traces:view", "audit", "runtime_trace"),
    ("system-admin", None, "系统管理", "System Management", None, None, "setting", None),
    ("users", "system-admin", "账号管理", "Accounts", "/users", "users:view", "team", None),
    ("groups", "system-admin", "用户组", "User Groups", "/users-groups", "groups:view", "team", None),
    ("roles", "system-admin", "角色管理", "Roles", "/roles", "roles:view", "key", None),
    ("menus", "system-admin", "菜单管理", "Menus", "/menus", "menus:view", "setting", None),
    ("system-audit", "system-admin", "系统审计", "System Audit", "/system-audit", "audit:operation", "audit", None),
    ("settings", "system-admin", "系统总览", "System Overview", "/settings", "settings:view", "setting", None),
    ("docs-settings", "system-admin", "文档设置", "Documentation Settings", "/docs-settings", "docs:update", "fileText", None),
]
PAGE_PERMISSIONS = {row[4]: row[5] for row in PAGES if row[4]}
PAGE_PERMISSIONS.update({"/scanner-access": "credentials:view", "/model-gateway/keys": "credentials:view"})
PAGE_FEATURES = {row[4]: row[7] for row in PAGES if row[7]}
ICONS = {row[6] for row in PAGES}

SYSTEM_ROLES = {
    "super_admin": ("超级管理员", "/dashboard", PERMISSIONS),
    "admin": ("管理员", "/dashboard", PERMISSIONS),
    "privacy_auditor": ("隐私审计员", "/pipeline-trace", {"privacy_audit:view", "privacy_audit:raw", "traces:view", "traces:raw"}),
    "security_auditor": ("安全审计员", "/agent-security/scans", {"scans:view", "scans:raw", "targets:view", "schedules:view", "traces:view", "audit:security", "audit:verify"}),
    "auditor": ("系统审计员", "/system-audit", {"audit:login", "audit:operation", "audit:security", "audit:verify"}),
    "user": ("普通用户", "/dashboard", {"dashboard:view", "skills:view"}),
}
