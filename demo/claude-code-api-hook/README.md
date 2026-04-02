# Claude Code API Hook Demo

这个目录包含通过 HTTP API 调用 Skill Manager 后端的 Claude Code Hook 实现。

## 两种 Hook 方案对比

### 1. 本地 Hook (`demo/claude-code-hook`)
- 直接在本地运行，访问本地文件系统和 registry
- 无需启动后端服务
- 审计日志写入本地 `audit.jsonl`

### 2. API Hook (`demo/claude-code-api-hook`)
- 通过 HTTP API 调用 Skill Manager 后端服务
- 后端服务处理验证逻辑并写入审计日志
- 适合 Claude Code 与 Skill Manager 不在同一台机器上的场景

## 前置条件

1. 安装依赖：
   ```bash
   pip install httpx
   ```

2. 启动 Skill Manager 后端服务：
   ```bash
   uv run skill-manager-api --host 0.0.0.0 --port 8080
   ```

3. 日志文件
`SKILL_MANAGER_DATA_DIR/audit.jsonl`，通过 .env 配置 `SKILL_MANAGER_DATA_DIR`。
默认日志文件位置： ``Path.home() / ".skill-manager/audit.jsonl"`

4. 设置签名密钥

为了测试签名验证，先设置签名密钥：

```bash
# 在项目根目录的 .env 文件中添加
SKILL_MANAGER_SIGNING_KEY="your-secret-key-here-change-this-in-production"
```

### 配置 Claude Code

1. 复制配置文件示例：
   ```bash
   cp settings.json.example ~/.claude/settings.json
   ```

2. 根据你的环境修改 `~/.claude/settings.json` 中的路径

3. 启动 Claude Code，Hook 会自动生效

## 配置

### 环境变量

- 在 `.env` 中配置 `SKILL_MANAGER_BASE_URL`: Skill Manager 后端服务地址（默认：`http://127.0.0.1:8080`）


## 测试场景

### 测试步骤 1: SessionStart - code-review 未提交

1. 确保 code-review 未在 registry 中
2. 启动 Claude Code
3. 预期：会话正常启动，不会被阻止
4. 查看日志文件，可以看到 code-review 未注册的记录

### 测试步骤 2: SessionStart - code-review 已提交
让我们提交 code-review skill 到 registry：

```bash
cd skill-manager

# 提交 code-review skill
uv run skill-manager submit .claude/skills/code-review

# 批准 skill
uv run skill-manager approve code-review
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


### settings.json 配置

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 demo/claude-code-api-hook/claude_api_hook.py"
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
            "command": "python3 demo/claude-code-api-hook/claude_api_hook.py"
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
            "command": "python3 demo/claude-code-api-hook/claude_api_hook.py"
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
- 日志文件路径可以通过 `SKILL_MANAGER_DATA_DIR` 环境变量配置
- SessionStart 和 ConfigChange 事件不会阻止会话，所有信息都可以通过日志文件查看
- PreToolUse 事件会在权限检查失败时阻止工具调用


