# Claude Code Hook 集成演示

这个示例演示的是：

1. 如何在 Claude Code 中配置 Agent Manager hooks
2. SessionStart: 会话启动时扫描并验证所有可见 skill
3. ConfigChange: 加载 skill 时验证注册状态和签名
4. PreToolUse: 工具调用时强制执行 allowed_tools 权限控制

这个 demo 适合指导别人把 Claude Code 接入当前 Agent Manager 系统。

## Demo Scope

这个样例展示如何通过 Claude Code 的 hook 机制，把 Agent Manager 的安全控制无缝集成到 Claude Code 的整个生命周期中。

## Files

- [README.md](/Users/nancy_yu/riversecurity/agent-manager/demo/claude-code-hook/README.md)
  本文档
- [settings.json.example](/Users/nancy_yu/riversecurity/agent-manager/demo/claude-code-hook/settings.json.example)
  Claude Code 配置文件示例
- [skills/code-review/](/Users/nancy_yu/riversecurity/agent-manager/demo/claude-code-hook/skills/code-review/)
  示例 skill

## Hook 事件说明

Agent Manager hook 处理三个 Claude Code 事件：

| 事件 | 作用 | 是否会阻止 |
|------|------|-----------|
| `SessionStart` | 会话启动时扫描所有可见 skill，验证注册状态 | **不会阻止**，错误信息可通过日志文件查看 |
| `ConfigChange` | 加载 skill 时验证注册状态、签名和可加载性 | **不会阻止**，错误信息可通过日志文件查看 |
| `PreToolUse` | 每次工具调用前检查 allowed_tools 权限 | **会阻止**，错误信息会显示在 Claude Code 界面 |

> **注意**: 根据测试结果，虽然代码中 SessionStart 和 ConfigChange 事件有 `_block()` 调用，但实际 Claude Code 会话不会被阻止。所有事件的详细信息都可以通过日志文件查看。

## 快速开始

### 1. 准备工作

确保你已经在项目根目录下，并且 Agent Manager 已经安装：

```bash
cd agent-manager
uv sync
```

### 2. 日志文件
`AGENT_MANAGER_DATA_DIR/audit.jsonl`，通过 .env 配置。
默认日志文件位置： ``Path.home() / ".agent-manager/audit.jsonl"`

### 3 设置签名密钥

为了测试签名验证，先设置签名密钥：

```bash
# 在项目根目录的 .env 文件中添加
AGENT_MANAGER_SIGNING_KEY="your-secret-key-here-change-this-in-production"
```
### 4. 准备示例 skill

将 demo 目录下的 code-review skill 复制到 `.claude/skills/` 目录：

```bash
cd agent-manager

# 创建 .claude/skills 目录（如果不存在）
mkdir -p .claude/skills

# 复制示例 skill
cp -r demo/claude-code-hook/skills/code-review .claude/skills/
```

### 5. 配置 Claude Code

把示例配置复制到你的项目配置目录：

```bash
# 备份现有配置（如果有）
cp ~/.claude/settings.json ~/.claude/settings.json.backup 2>/dev/null || true

# 使用 demo 配置
cp demo/claude-code-hook/settings.json.example ~/.claude/settings.json
```

或者直接在项目根目录创建 `.claude/settings.json`（参考项目根目录已有的配置）。


## 测试场景

### 测试步骤 1: SessionStart - code-review 未提交

1. 确保 code-review 未在 registry 中
2. 启动 Claude Code
3. 预期：会话正常启动，不会被阻止
4. 查看日志文件，可以看到 code-review 未注册的记录

### 测试步骤 2: SessionStart - code-review 已提交
让我们提交 code-review skill 到 registry：

```bash
cd agent-manager

# 提交 code-review skill
uv run agent-manager submit .claude/skills/code-review

# 批准 skill
uv run agent-manager approve code-review
```

1. 确保提交并批准 code-review skill（带签名）
2. 再次启动 Claude Code
3. 预期：会话正常启动
4. 查看日志文件，可以看到 code-review 验证通过并加入 active 列表

### 测试步骤 3: ConfigChange - 验证签名失败

1. 启动 Claude Code
2. 修改 code-review skill 文件（篡改）
3. 查看日志文件，可以看到签名验证失败的记录

### 测试步骤 4: ConfigChange - 验证签名成功

1. 复原 code-review skill 文件
2. 查看日志文件，可以看到签名验证成功

### 测试步骤 5: PreToolUse - 使用不允许的工具（Block）

1. 在 Claude Code 中输入提示词 `执行 code-review skill 中的 check_style.py 对 sum(1, 2, 3) 进行审核。` 
2. 使用了不在 allowed-tools 中的工具（如 Bash）
3. 预期：工具调用被阻止，错误信息显示在 Claude Code 界面

### 测试步骤 6: PreToolUse - 使用允许的工具（通过）

1. 在 Claude Code 中输入提示词 `总结 code-review skill 的功能` 
2. 使用了在 allowed-tools 中的工具（如 Read）
3. 预期：工具调用成功

## 配置说明

### settings.json 结构

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m agent_manager.hooks.agent_hook",
            "timeout": 30
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
            "command": "python3 -m agent_manager.hooks.agent_hook",
            "timeout": 10
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
            "command": "python3 -m agent_manager.hooks.agent_hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### 关键点

1. **Python 路径**: 使用绝对路径确保 hook 能找到正确的 Python 解释器
2. **超时设置**:
   - SessionStart: 30秒（需要扫描所有 skill）
   - ConfigChange/PreToolUse: 10秒（快速校验）
3. **Matcher**:
   - SessionStart/PreToolUse: 空字符串匹配所有
   - ConfigChange: `"skills"` 只匹配 skill 相关配置变更

## 退出码约定

| 退出码 | 含义 |
|--------|------|
| 0 | 允许（或不适用） |
| 2 | 阻止，stderr 包含原因 |

### 退出码 2 的具体影响 
| Hook 事件 | 行为 |
|--------|------|
|PreToolUse	|阻止工具调用，向 Claude 显示 stderr|
|SessionStart	|不阻止执行，仅向用户显示 stderr|
|ConfigChange	|不阻止执行，仅向用户显示 stderr|

> **注意**: 只有 PreToolUse 事件会实际阻止操作，SessionStart 和 ConfigChange 事件虽然代码中有 `_block()` 调用，但根据测试结果，Claude Code 会话不会被阻止。

## 工作原理

### SessionStart 流程

```
Claude Code 启动
    ↓
SessionStart 事件触发
    ↓
扫描 .claude/skills/ 目录
    ↓
对每个 skill 检查 registry
    ↓
记录结果到日志文件
    ↓
会话继续（不会被阻止）
```

### ConfigChange 流程

```
用户加载 skill
    ↓
ConfigChange 事件触发
    ↓
验证 skill 在 registry 中
    ↓
验证 status 是 APPROVED/DEPLOYED
    ↓
验证签名（如果有）
    ↓
记录结果到日志文件
    ↓
skill 加载继续（不会被阻止）
```

### PreToolUse 流程

```
Agent 调用工具
    ↓
PreToolUse 事件触发
    ↓
有 active skill 吗？
    ├─ 否 → 允许所有工具
    └─ 是 → 计算所有 allowed_tools 的并集
              ↓
         工具在允许列表中？
              ├─ 是 → 允许调用
              └─ 否 → 阻止调用（显示错误信息）
```

## Notes

- 这是一个指导性 demo，展示如何配置 Claude Code hooks
- 日志文件路径可以通过 `AGENT_MANAGER_DATA_DIR` 环境变量配置
- SessionStart 和 ConfigChange 事件不会阻止会话，所有信息都可以通过日志文件查看
- PreToolUse 事件会在权限检查失败时阻止工具调用
