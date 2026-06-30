# Claude Code Agent Guard Hook

这个目录包含使用 agent-manager-skill-verifier 逻辑的 Claude Code Hook 实现。

## 功能特性

Agent Guard Hook (`agent_guard_hook.py`) 仅使用 verify 功能：

- **在 PreToolUse 事件触发** - 每次工具调用前验证 skills
- **验证所有发现的 skills** - 扫描 skill 目录并验证每个 skill
- **使用需要 token 的 API 端点** - `/api/v1/access/runtime/verify-skill-signature` 和 `/api/v1/access/runtime/can-load/{name}`
- **会话状态管理** - 跟踪已验证的 active skills

## 前置条件

1. **安装项目 SDK**
   ```bash
   cd /path/to/skill-manager
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

## 配置 Claude Code

在 `.claude/settings.json` 中配置：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 demo/claude-code-api-hook/agent_guard_hook.py"
          }
        ]
      }
    ],
    "ConfigChange": [
      {
        "matcher": "skills",
        "hooks": [
          {
            "type": "command",
            "command": "python3 demo/claude-code-api-hook/agent_guard_hook.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 demo/claude-code-api-hook/agent_guard_hook.py"
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

### 三个 Hook 事件

| 事件 | 触发时机 | 作用 |
|------|----------|------|
| `SessionStart` | 新会话开始时 | 扫描并验证所有 skills，初始化 active_skills |
| `ConfigChange` | 配置改变时 | 验证新加载的 skill，添加到 active_skills |
| `PreToolUse` | 每次工具调用前 | 验证 active_skills |

### PreToolUse 流程

```
Agent 调用工具
    ↓
PreToolUse 事件触发
    ↓
有 active_skills 吗？
    ├─ 否 → 扫描所有 skills，验证它们，更新 active_skills
    └─ 是 → 只验证 active_skills
              ↓
         skill 验证通过？
              ├─ 是 → 允许工具调用
              └─ 否 → 阻止工具调用
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
