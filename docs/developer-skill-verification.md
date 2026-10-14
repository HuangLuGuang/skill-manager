# 开发者：加载前验签

本指南面向能够修改 Skill Loader 或适配宿主事件的开发者。加载前计算实际 Skill 内容摘要，通过 Agent 运行凭证调用验签和加载许可接口，再决定是否读取、加载或执行目标内容。下文保留手工 Hook 脚本、凭证和配置示例，按各示例的实际覆盖范围验收。

日常宿主事件采集与工具策略接入请先使用[客户端 AIDR 插件 Hook](hook-integration.md)。它通过设备认证管理插件、接收器和上报。这里的开发者脚本使用独立的 Agent 运行凭证，同步核对 Skill 内容与加载授权；AIDR 工具规则或异步 Skill 使用审计不能替代该加载边界。

**English:** This developer guide covers synchronous Skill verification in a real Loader or a supported host event. Compute the actual content digest, verify it with an Agent-bound runtime credential, check load authorization, then enforce the result before loading. For routine host audit and tool policies, start with [Client AIDR plugin Hooks](hook-integration.md). AIDR device authentication, tool decisions and asynchronous usage audit have separate purposes. The bilingual in-app guide is available at `/docs/developer-skill-verification`.

## 自研 Loader 的检查顺序

1. 复用或登记平台 Agent，绑定允许使用的 Skill，签发 `runtime:verify-signature` 与 `runtime:can-load` 运行凭证。
2. 在真实加载路径读取实际目录，按平台兼容的 manifest 和忽略规则计算无密钥摘要。
3. 调用 `POST /api/v1/access/runtime/verify-skill-signature`，通过后调用 `GET /api/v1/access/runtime/can-load/{skill_name}`；两项均允许后才继续加载，并保证执行内容与被核对内容一致。
4. 在 Tool Dispatcher 执行前按需接入 `check-tool`，并增加 `runtime:check-tool` 权限。
5. 演练内容篡改、未授权、撤销、凭证失效和平台不可达，核对实际加载结果及平台审计。

接口字段与摘要算法见[内容签名验证](agent-signature-verification.md)，自研框架示例见[外部 Agent 接入](external-agent-integration.md)。下列手工脚本只覆盖其明确识别且宿主实际触发的事件。

## 1. 当前实现与边界

| Agent | 示例 | 事件与检查 | 当前边界 |
|---|---|---|---|
| Claude Code | `demo/claude-code-api-hook/` | `PreToolUse` 识别到 Skill 调用后执行内容签名和加载许可检查 | 无法解析的输入和非 Skill 调用放行，必须用真实事件验证 Skill 提取 |
| TraeCode / TRAE CN | 官方 Hook 协议已支持，可以 `demo/claude-code-api-hook/` 作为适配起点 | 官方提供 `PreToolUse`，输入包含 `tool_name` 和 `tool_input` | Agent Manager 尚未在真实 TraeCode 中完成端到端验证，不应宣称已可用 |
| Codex | `demo/codex-agent-manager-hook/` | `PreToolUse` 在受支持的 Tool 前校验发现到的全部受治理 Skill | 当前覆盖 Bash、`apply_patch`、MCP 等受支持路径，不代表所有 Tool |
| OpenClaw | `demo/openclaw-agent-manager-hook/` | `agent:bootstrap` 做加载校验，`before_tool_call` 计划做 Tool 检查 | 当前是骨架，需要根据目标 OpenClaw 版本的真实 payload 和插件工程适配 |

## 2. 平台侧准备

1. 在“智能体管理 -> 智能体列表”复用已有身份，或创建并启用 Agent，记录稳定的 Agent ID。
2. 将允许使用的 `APPROVED` 或 `DEPLOYED` Skill 绑定给该 Agent。
3. 在“智能体管理 -> 统一凭证中心”创建绑定该 Agent 的运行凭证。
4. Claude Code 示例以及待验证的 TraeCode 适配至少需要：
   - `runtime:verify-signature`
   - `runtime:can-load`
5. 需要执行 Tool 权限检查时再增加 `runtime:check-tool`。当前 Codex 示例至少需要 `runtime:verify-signature`。

运行时的 `AGENT_ID`、运行凭证绑定对象和平台 Agent 必须一致。不要使用管理员登录 Token、客户端接入凭证或 Scanner 凭证代替 Agent 运行凭证。

凭证明文只展示一次。应通过环境变量或仓库外、仅当前用户可读的环境文件注入，不要写进 Hook JSON、截图或代码仓库。

## 3. Claude Code 接入

推荐使用 API 型示例：

```text
demo/claude-code-api-hook/agent_guard_hook.py
```

脚本只计算无密钥内容摘要并调用 Agent Manager API，不需要也不允许持有服务端签名私钥。

### 3.1 安装依赖

在 `skill-manager` 源码目录执行：

```bash
uv sync --extra dev
```

Hook 配置中的 Python 使用该环境的 `.venv/bin/python` 绝对路径，确保能够导入 `httpx` 和 `dotenv`。

### 3.2 注入运行环境

```bash
export AGENT_MANAGER_BASE_URL="https://agent-manager.example.com"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_ID="your-agent-id"
```

可选环境变量：

- `AGENT_MANAGER_SKILLS_DIR`：追加优先扫描的 Skill 根目录。
- `AGENT_MANAGER_MANAGED_SKILLS_DIR`：受管 Skill 根目录，默认 `~/.agent-manager/skills`。
- `AGENT_MANAGER_HOOK_LOG_FILE`：自定义诊断日志路径。

### 3.3 配置 `PreToolUse`

Claude Code 配置位置：

- 项目级：`.claude/settings.json`
- 用户级：`~/.claude/settings.json`

先在项目级配置中验证，再决定是否推广到用户级。命令必须使用脚本绝对路径：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/skill-manager/.venv/bin/python /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py"
          }
        ]
      }
    ]
  }
}
```

修改配置后重新启动 Agent 或新建会话。

### 3.4 验证

1. 调用一个已批准、已绑定且内容一致的 Skill，预期退出码为 `0`，Tool 继续执行。
2. 修改该 Skill 的一个受签名文件，再次调用，预期退出码为 `2` 并阻断。
3. 恢复文件后撤销 Agent 的 Skill 绑定，再次调用，预期阻断。
4. 检查 Agent 界面原因、本地日志和平台运行审计：

```bash
tail -f ~/.agent-manager/logs/agent_guard_hook.log
```

该示例只对能够识别出的 Skill 调用执行 fail-closed 校验。无法解析的事件和非 Skill 调用直接放行，因此“配置文件存在”不等于覆盖已经生效。

Claude Code 官方参考：

- [Claude Code：Hook 快速指南](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code：Hook 完整参考](https://code.claude.com/docs/en/hooks)
- [Claude Code：权限与 `PreToolUse` Hook](https://code.claude.com/docs/en/permissions)

## 4. TraeCode / TRAE CN 接入状态

TraeCode 官方已提供 Hook 能力，支持 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop` 和 `Notification` 等事件。官方也说明可导入 Claude Code Hooks，但同名事件的输入输出可能不同，仍需适配。

官方配置位置为：

- 项目级：`$PROJECT_FOLDER/.trae/hooks.json`
- macOS / Linux 用户级：`~/.trae-cn/hooks.json`

TraeCode 原生配置需要 `version: 1`。下面只是 Agent Manager 的待验证适配示例，不是已通过实机验收的配置：

```json
{
  "version": 1,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Skill",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/skill-manager/.venv/bin/python /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

协议层面的兼容点已确认：TraeCode `PreToolUse` 会通过 stdin 传入 JSON，其中包含 `hook_event_name`、`tool_name` 和 `tool_input`；命令退出码 `2` 表示拒绝，stderr 作为拒绝原因。这些与现有脚本的基本输入和阻断方式一致。

仍未验证的关键点包括：

1. TraeCode 真实 `Skill` Tool 的 `tool_input` 字段形状是否能被当前脚本提取。
2. TraeCode 本地执行与沙箱执行模式下，Python 路径、环境变量和本地 Skill 目录是否可见。
3. 允许、内容篡改、取消授权、平台不可达四类场景是否在 TraeCode 界面和 Agent Manager 审计中形成完整证据链。

所以当前结论是“TraeCode 官方支持 Hook，Agent Manager 具备协议适配基础”，而不是“Agent Manager 已完成 TraeCode Hook 实际验证”。

官方来源：

- [TRAE：通过 Hook 实现自动化](https://docs.trae.cn/ide_automate-actions-with-hooks)
- [TRAE：Hook 配置参考](https://docs.trae.cn/ide_hook-configuration-reference)
- [TRAE CN 更新日志](https://docs.trae.cn/ide_changelog)

## 5. Codex 接入

### 5.1 准备环境文件

```bash
mkdir -p ~/.agent-manager
cp demo/codex-agent-manager-hook/codex-agent-manager-hook.env.example \
  ~/.agent-manager/codex-agent-manager-hook.env
chmod 600 ~/.agent-manager/codex-agent-manager-hook.env
```

编辑环境文件：

```dotenv
AGENT_MANAGER_VERIFIER_BASE_URL=https://agent-manager.example.com
AGENT_MANAGER_VERIFIER_TOKEN=amat_xxx
AGENT_ID=your-agent-id
```

Hook 默认检查当前项目和父级仓库中的 `.agents/skills`、用户级 `~/.agents/skills`、兼容目录 `~/.codex/skills` 以及 `/etc/codex/skills`。需要追加插件或自定义目录时设置：

```dotenv
AGENT_MANAGER_CODEX_SKILLS_DIRS=/path/to/plugin/skills:/path/to/custom/skills
```

追加目录不会关闭默认目录检查。

### 5.2 安装 Hook 配置

项目级：

```bash
mkdir -p .codex
cp demo/codex-agent-manager-hook/hooks.json.example .codex/hooks.json
```

也可以合并到用户级 `~/.codex/hooks.json`。把示例命令中的 Python 脚本和环境文件改为绝对路径：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/skill-manager/.venv/bin/python /absolute/path/skill-manager/demo/codex-agent-manager-hook/codex_agent_guard_hook.py --env-file /absolute/path/.agent-manager/codex-agent-manager-hook.env",
            "timeout": 30,
            "statusMessage": "正在通过 Agent Manager 校验 Codex Skills"
          }
        ]
      }
    ]
  }
}
```

重新启动 Codex 或创建新任务，在 Codex CLI 中运行 `/hooks`，审核并信任该 Hook。项目级 Hook 只有在项目被信任后才会加载。

### 5.3 验证

1. 在受治理目录放入一个未批准、未绑定或内容不一致的 Skill。
2. 触发 Bash、`apply_patch` 或 MCP 等当前支持的 Tool。
3. 预期 Hook 返回 `permissionDecision=deny`，Agent 显示“Agent Manager 强制校验阻断”。
4. 批准并绑定 Skill、恢复一致内容后再次执行，预期放行。

当前 Codex Hook 对能够拦截的调用采用 fail-closed，但尚未覆盖所有 Shell、WebSearch 和其他 Tool 路径。它不能替代操作系统 Sandbox、插件信任策略或受控 Skill 部署目录。

Codex 官方参考：

- [OpenAI Docs：Codex Hooks](https://learn.chatgpt.com/docs/hooks)
- [OpenAI Docs：Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

## 6. OpenClaw 接入

OpenClaw 示例当前是实现骨架，不是即装即用成品：

```text
demo/openclaw-agent-manager-hook/
```

推荐顺序：

1. 先安装 `payload-recorder`，触发一次 `agent:bootstrap`。
2. 查看 `~/.openclaw/logs/hook-payloads.jsonl` 中的真实 payload。
3. 根据真实结构收紧 `discoverVisibleSkills()` 和 `resolveSkillNameFromContext()`。
4. 将 internal Hook 安装为 managed hook，完成 `agent:bootstrap` 加载校验。
5. 把 `plugin-hooks.ts` 接入真实 OpenClaw 插件工程，在 `before_tool_call` 调用 `check-tool`。
6. 将事件中的会话身份稳定映射到平台 Agent ID，不能直接把任意 session key 当作 Agent ID。

未使用目标版本真实事件和插件 API 完成适配前，不应宣称已经强制覆盖 Skill 加载与 Tool 调用。

## 7. 上线验收与排查

| 场景 | 预期 | 优先检查 |
|---|---|---|
| 已批准、已绑定、内容一致 | Hook 放行 | Agent ID、凭证绑定、Skill 路径和本地摘要 |
| Skill 内容被修改 | 阻断 | 签名忽略集是否一致；macOS 上确认 `.DS_Store` 未参与摘要 |
| Agent 未绑定 Skill 或凭证错误 | 阻断 | Agent 绑定、凭证类型、状态和权限范围 |
| 平台不可达或凭证过期 | 声明为 fail-closed 的路径应阻断 | 地址、代理、证书、超时和 Hook stderr |
| 没有任何 Hook 日志 | 不能证明已接入 | 当前会话 cwd、项目/用户配置作用域、事件名称和目标 Tool |

上线前至少演练：允许、内容篡改、未授权、平台不可达、事件未命中。每次同时核对 Agent 界面结果、本地 Hook 日志和平台“接入与运行”审计，不能只看其中一个。

## 8. 相关文档

- [外部 Agent 接入](external-agent-integration.md)
- [客户端 AIDR 插件 Hook 接入](hook-integration.md)
- [Agent 内容签名验证](agent-signature-verification.md)
- [Agent Manager Client](agent-manager-client.md)
- [OpenClaw Hook 设计](openclaw-agent-manager-hooks.md)
