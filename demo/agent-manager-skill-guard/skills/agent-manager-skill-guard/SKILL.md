---
name: agent-manager-skill-guard
description: Use when an agent is asked to install, inspect, load, or execute a third-party skill, external skill, newly downloaded skill, locally modified skill, or any skill that should be checked against Agent Manager approval and signature state before use.
---

# Agent Manager Skill Guard

使用 Agent Manager 作为第三方 Skill 的准入、审批和运行时校验网关。不要因为某个第三方 Skill 已经存在于本地，就直接加载或执行它。

## 必须遵守

在使用任何第三方或外部来源 Skill 之前：

1. 如果该 Skill 还没有提交到 Agent Manager，先提交扫描。
2. 在加载或调用该 Skill 前，校验内容完整性、加载状态和当前 Agent 的授权范围。
3. 如果校验失败，阻断使用，并把原因告诉用户。

不需要 hook。这个 Skill 是平台无关的，依靠 Agent 在使用目标 Skill 前主动运行 guard 脚本。

## 配置

在 Agent Manager 管理台创建一个接入凭证：

`智能体管理 -> 凭证管理`

凭证需要绑定当前 Agent，并包含这些权限：

- `scanner:submit`
- `scanner:read-own-results`
- `scanner:read-own-sessions`
- `runtime:verify-signature`
- `runtime:can-load`
- `runtime:check-tool`

通过环境变量配置运行环境：

```bash
export AGENT_MANAGER_BASE_URL="http://agent-manager.example.com"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_ID="your-agent-id"
```

如果运行环境已经使用 `SKILL_MANAGER_SERVER`、`SKILL_MANAGER_TOKEN`、`AGENT_MANAGER_TOKEN` 或 `AGENT_MANAGER_ACCESS_TOKEN`，guard 脚本也会识别它们。

不要把真实凭证写进 Skill、仓库文件、Prompt 或示例输出。

如果服务端配置了 `AGENT_MANAGER_SIGNING_KEY`，执行完整性校验的 Agent 环境也必须使用相同的值，否则本地内容指纹会和平台中批准版本的指纹不一致。

提交和完整性校验时，guard 会忽略 `.git`、`.venv`、`node_modules`、`__pycache__`、`dist` 和 `build`。这些目录不属于受治理的 Skill 内容，不要把其中的代码当作 Skill 的一部分执行。

## 命令

提交本地 Skill 目录进行扫描：

```bash
python scripts/agent_manager_skill_guard.py submit --path /path/to/skill --behavioral
```

按需启用更完整的分析能力：

```bash
python scripts/agent_manager_skill_guard.py submit --path /path/to/skill \
  --behavioral \
  --deep-scan \
  --sandbox \
  --llm \
  --no-cache
```

查看已提交 Skill 的状态：

```bash
python scripts/agent_manager_skill_guard.py status --skill-id <skill-id>
```

使用前做内容完整性和加载授权校验：

```bash
python scripts/agent_manager_skill_guard.py verify --name skill-name --path /path/to/skill
```

只有当 Skill 已批准或已部署、本地内容与批准版本一致，并且当前 Agent 被授权使用该 Skill 时，guard 脚本才返回退出码 `0`。任何非 `0` 退出码都必须视为阻断。

## 阻断提示

向用户说明原因时，使用清晰的提示：

- 未提交：`该 Skill 尚未提交到 Agent Manager，请先上传扫描。`
- 扫描中：`该 Skill 正在扫描，当前不可调用。`
- 待审核：`该 Skill 等待人工审核，审批通过前不可调用。`
- 已拒绝：`该 Skill 已被拒绝，不可调用。`
- 未形成可信版本：`该 Skill 没有内容指纹，请等待批准或重新提交。`
- 内容不匹配：`本地 Skill 内容与批准版本不一致，请重新提交扫描。`
- API 错误：`Agent Manager 校验失败，按安全策略阻断调用。`

不要提供绕过路径。如果用户坚持继续，说明该 guard 的默认策略是：必须等 Agent Manager 批准，并且内容完整性与授权校验通过后才能使用。
