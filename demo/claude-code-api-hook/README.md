# Claude Code Agent and Trae IDE Guard Hook

这个目录包含使用 agent-manager-skill-verifier 逻辑的 Claude Code Hook 和 Trae IDE Hook 实现。

## 功能特性

Agent Guard Hook (`agent_guard_hook.py`) 仅使用 verify 功能，逻辑与 `agent_manager_skill_verifier.py` 完全一致：

- **仅在 PreToolUse 事件触发** - 每次调用 Skill 工具前验证该 skill
- **验证被调用的 skill** - 从事件中提取 skill 名称，找到对应目录并验证
- **使用需要 token 的 API 端点** - `/api/v1/access/runtime/verify-skill-signature` 和 `/api/v1/access/runtime/can-load/{name}`
- **阻断消息格式与 verifier 完全一致** - 使用中文，包含详细原因和后续提示
- **会话状态管理** - 跟踪已验证的 skills（用于日志，不跳过验证）

## 前置条件

1. **安装项目 SDK**
   ```bash
   cd skill-manager
   python -m pip install -e ".[dev]"
   ```

2. **配置环境变量** - 在项目根目录的 `.env` 文件中设置：
   ```bash
   # Agent Manager 服务地址（必需）
   AGENT_MANAGER_BASE_URL=http://your-agent-manager-server:port

   # API Token（必需）
   AGENT_MANAGER_API_TOKEN=your-token-here

   # Agent ID（可选）
   AGENT_ID=your-agent-id

   # 签名密钥（必需，必须与服务端一致！）
   AGENT_MANAGER_SIGNING_KEY=your-signing-key-here
   ```

   注意：`AGENT_MANAGER_SIGNING_KEY` 必须与服务端配置的完全一致！

## 配置 Claude Code or Trae IDE Hook

在 `.claude/settings.json` 中配置（仅需 PreToolUse）：使用 `agent_guard_hook.py` 脚本的绝对路径。
在 `.trae-cn/hooks.json` 中配置（仅需 PreToolUse）：使用 `agent_guard_hook.py` 脚本的绝对路径。
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 skill-manager/demo/claude-code-api-hook/agent_guard_hook.py"
          }
        ]
      }
    ]
  }
}
```

## 环境变量

| 环境变量 | 必需 | 说明 |
|----------|------|------|
| `AGENT_MANAGER_BASE_URL` | ✅ | Agent Manager 服务地址 |
| `AGENT_MANAGER_API_TOKEN` | ✅ | API 访问 Token |
| `AGENT_MANAGER_SIGNING_KEY` | ✅ | 签名密钥（必须与服务端一致，服务端没有可不填）|
| `AGENT_ID` | ✅ | Agent ID |
| `AGENT_MANAGER_DATA_DIR` | ❌ | 数据目录 |

## 工作原理

### 单个 Hook 事件

| 事件 | 触发时机 | 作用 |
|------|----------|------|
| `PreToolUse` | 每次工具调用前 | 如果是 Skill 工具调用，验证该 skill |

### PreToolUse 流程

```
Agent 调用工具
    ↓
PreToolUse 事件触发
    ↓
是 Skill 工具调用吗？
    ├─ 否 → 允许工具调用
    └─ 是 → 提取 skill 名称
              ↓
         找到 skill 目录
              ↓
         调用 verify-skill-signature API
              ↓
         验证通过且状态是 APPROVED？
              ├─ 否 → 阻断并显示原因
              └─ 是 → 调用 can-load API
                        ↓
                   验证通过且状态是 APPROVED？
                        ├─ 否 → 阻断并显示原因
                        └─ 是 → 允许工具调用
```

### 验证步骤（与 agent_manager_skill_verifier.py 完全一致）

1. **Verify Skill Signature**
   - 调用 `/api/v1/access/runtime/verify-skill-signature`
   - 检查 `allowed` 字段为 True
   - 检查 `status` 为 `APPROVED`

2. **Verify Can Load**
   - 调用 `/api/v1/access/runtime/can-load/{skill_name}`
   - 检查 `allowed` 字段为 True
   - 检查 `status` 为 `APPROVED`

### 阻断消息格式

```
阻断: {reason} status={status}
不要调用该 Skill。请联系管理员在 Agent Manager 中审批通过后再使用。
```

## 日志文件

Hook 日志位于：
```
~/.agent-manager/logs/agent_guard_hook.log
```

查看实时日志：
```bash
tail -f ~/.agent-manager/logs/agent_guard_hook.log
```

## 退出码约定

| 退出码 | 含义 |
|--------|------|
| 0 | 允许 |
| 2 | 阻止，stderr 包含原因 |

## Skill 目录扫描顺序

按以下优先级顺序扫描 skill 目录：

1. `AGENT_MANAGER_SKILLS_DIR` 环境变量指定的目录（最高优先级）
2. 项目 `.claude/skills/` 目录
3. 全局 `~/.claude/skills/` 目录
