---
name: agent-manager-skill-guard
description: Use when an agent is asked to install, inspect, load, or execute a third-party skill, external skill, newly downloaded skill, locally modified skill, or any skill that should be checked against Agent Manager approval and signature state before use.
---

# Agent Manager Skill Guard

使用 Agent Manager 作为第三方 Skill 的审批和签名网关。不要因为某个第三方 Skill 已经存在于本地，就直接加载或执行它。

## 必须遵守

在使用任何第三方或外部来源 Skill 之前：

1. 如果该 Skill 还没有提交到 Agent Manager，先提交扫描。
2. 在加载或调用该 Skill 前，校验本地签名和加载状态。
3. 如果校验失败，阻断使用，并把原因告诉用户。

不需要 hook。这个 Skill 是平台无关的，依靠 Agent 在使用目标 Skill 前主动运行 guard 脚本。

## 配置

在 Agent Manager 管理台创建一个接入 Token：

`扫描器接入 -> 创建 Token`

Token 必须包含这些权限：

- `scanner:submit`
- `scanner:read-own-results`
- `runtime:verify-signature`
- `runtime:can-load`
- `runtime:check-tool`

通过环境变量配置运行环境：

```bash
export AGENT_MANAGER_BASE_URL="http://agent-manager.example.com"
export AGENT_MANAGER_TOKEN="smsc_live_xxx"
```

如果运行环境已经使用 `AGENT_MANAGER_API_TOKEN` 或 `AGENT_MANAGER_ACCESS_TOKEN`，guard 脚本也会识别它们。

不要把真实 Token 写进 Skill、仓库文件、Prompt 或示例输出。

如果服务端配置了 `AGENT_MANAGER_SIGNING_KEY`，执行验签的环境也必须使用相同的值，否则本地签名会和 Registry 中的签名不一致。

提交和验签时，guard 会忽略 `.git`、`.venv`、`node_modules`、`__pycache__`、`dist` 和 `build`。这些目录不属于受治理的 Skill 内容，不要把其中的代码当作 Skill 的一部分执行。

## 命令

提交本地 Skill 目录进行扫描：

```bash
python scripts/agent_manager_skill_guard.py submit --path /path/to/skill
```

提交时默认请求服务端启用 LLM 分析。只有在系统没有配置 LLM，且用户明确要求跳过时，才使用：

```bash
python scripts/agent_manager_skill_guard.py submit --path /path/to/skill --no-llm
```

查看已提交 Skill 的状态：

```bash
python scripts/agent_manager_skill_guard.py status --skill-id <skill-id>
```

使用前验签：

```bash
python scripts/agent_manager_skill_guard.py verify --name skill-name --path /path/to/skill
```

只有当 Skill 已批准或已部署，并且本地签名匹配时，guard 脚本才返回退出码 `0`。任何非 `0` 退出码都必须视为阻断。

## 阻断提示

向用户说明原因时，使用清晰的提示：

- 未提交：`该 Skill 尚未提交到 Agent Manager，请先上传扫描。`
- 扫描中：`该 Skill 正在扫描，当前不可调用。`
- 待审核：`该 Skill 等待人工审核，审批通过前不可调用。`
- 已拒绝：`该 Skill 已被拒绝，不可调用。`
- 未签名：`该 Skill 没有批准签名，请等待批准或重新提交。`
- 签名不匹配：`本地 Skill 内容与批准版本不一致，请重新提交扫描。`
- API 错误：`Agent Manager 校验失败，按安全策略阻断调用。`

不要提供绕过路径。如果用户坚持继续，说明该 guard 的默认策略是：必须等 Agent Manager 批准并验签通过后才能使用。
