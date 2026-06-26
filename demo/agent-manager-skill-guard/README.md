# Agent Manager Skill Verifier

这是一个通用 Agent skill 示例，核心目标是在 Codex、Claude Code 等平台安装、加载或调用第三方 skill 前，先强制完成 Agent Manager 验证。

它依赖 Agent 遵循 `SKILL.md` 指令和脚本退出码，适合做跨平台的通用接入样例。对于 Hermes 等运行时，要真正强制生效，还应把同样的校验调用集成到 Skill loader 或 tool runtime。

## 目录

```text
skills/agent-manager-skill-guard/
├── SKILL.md
├── references/
│   └── agent-manager-verification.md
└── scripts/
    └── agent_manager_skill_guard.py
```

## 下载

管理台进入：

- `智能体管理`
- `接入与运行`
- `下载 Skill Guard`

后端接口：

```http
GET /api/v1/scanner/skill-guard/download
```

下载得到：

```text
agent-manager-skill-guard.zip
```

## Token 权限

在管理台 `智能体管理 -> 凭证管理` 创建 Agent 运行凭证，绑定目标 Agent。至少需要：

- `scanner:submit`
- `scanner:read-own-results`
- `scanner:read-own-sessions`
- `runtime:verify-signature`
- `runtime:can-load`
- `runtime:check-tool`

配置环境变量：

```bash
export AGENT_MANAGER_BASE_URL="http://localhost:8001"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_ID="<agent-id>"
export AGENT_MANAGER_SIGNING_KEY="和服务器 .env 中保持一致"
```

脚本也兼容读取 `SKILL_MANAGER_SERVER`、`SKILL_MANAGER_TOKEN`、`AGENT_MANAGER_TOKEN` 和 `AGENT_MANAGER_ACCESS_TOKEN`。

## 安装到 Codex

```bash
mkdir -p ~/.codex/skills
unzip agent-manager-skill-guard.zip -d ~/.codex/skills/
```

安装后重启 Codex，或刷新 Codex 的 skill 列表。

## 安装到 Claude Code

```bash
mkdir -p ~/.claude/skills
unzip agent-manager-skill-guard.zip -d ~/.claude/skills/
```

安装后重启 Claude Code，或刷新 Claude Code 的 skill 列表。

## 使用

提交第三方 skill：

```bash
python <skills-dir>/agent-manager-skill-guard/scripts/agent_manager_skill_guard.py submit \
  --path /path/to/third-party-skill \
  --behavioral \
  --deep-scan
```

查看状态：

```bash
python <skills-dir>/agent-manager-skill-guard/scripts/agent_manager_skill_guard.py status \
  --skill-id <skill-id>
```

使用前做内容完整性和加载授权校验：

```bash
python <skills-dir>/agent-manager-skill-guard/scripts/agent_manager_skill_guard.py verify \
  --path /path/to/third-party-skill
```

`submit` 不再默认启用 LLM。需要更完整分析时显式增加 `--sandbox`、`--llm` 或 `--no-cache`。

## 阻断策略

下面情况都应阻断使用第三方 skill：

- 未提交到 Agent Manager
- 仍在扫描中
- 待人工审核
- 已拒绝
- 未形成可信版本
- 本地内容和批准版本不一致
- `can-load` 返回不可加载
- 网络或 API 错误导致无法完成校验

默认不提供“用户确认后继续”的绕过路径。需要强制拦截时，应在具体平台上再实现 hook 或 runtime adapter。
