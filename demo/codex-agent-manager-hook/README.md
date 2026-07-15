# Codex Agent Manager Hook

这是 Codex 专用的强制 Skill 校验 Hook，不修改或复用 Claude Code Hook。

Codex 每次执行受支持的 `PreToolUse` 时，Hook 会校验受治理目录中的全部 Skill。任一 Skill 未注册、未批准、未绑定当前 Agent、签名不一致，或者 Agent Manager 不可达，当前工具调用都会被拒绝。

## 1. 配置环境文件

复制示例到仓库外，避免提交真实凭证：

```bash
mkdir -p ~/.agent-manager
cp demo/codex-agent-manager-hook/codex-agent-manager-hook.env.example ~/.agent-manager/codex-agent-manager-hook.env
```

编辑该文件，至少设置：

```dotenv
AGENT_MANAGER_VERIFIER_BASE_URL=http://127.0.0.1:8001
AGENT_MANAGER_VERIFIER_TOKEN=凭证管理中创建的Agent运行凭证
AGENT_ID=该凭证绑定的智能体ID
```

运行凭证需要 `runtime:verify-signature` 权限，智能体需要绑定允许使用的 Skill。

默认扫描当前仓库的 `.agents/skills`、`~/.agents/skills`、`/etc/codex/skills`，并兼容旧目录 `~/.codex/skills`。`AGENT_MANAGER_CODEX_SKILLS_DIRS` 用于追加其他受治理目录，不会关闭对 Codex 默认目录的检查。

强约束环境中，应只在上述受治理目录安装业务 Skill。如果启用了自带 Skill 的 Codex 插件，还需将对应插件的 `skills` 目录加入 `AGENT_MANAGER_CODEX_SKILLS_DIRS`，否则这些 Skill 不在本 Hook 的目录检查范围内。

## 2. 配置 Codex Hook

将 `hooks.json.example` 复制为项目 `.codex/hooks.json` 或合并到 `~/.codex/hooks.json`，并把命令里的两个路径替换成绝对路径。

```bash
mkdir -p .codex
cp demo/codex-agent-manager-hook/hooks.json.example .codex/hooks.json
```

重新启动 Codex 或新建任务，然后在 Codex CLI 中运行 `/hooks`，审核并信任该 Hook。项目级 Hook 只有在项目被信任后才会加载。

## 3. 验证阻断

先把一个未在 Agent Manager 审批或未绑定当前智能体的 Skill 放进受治理目录，再让 Codex 执行任意 Bash、文件修改或 MCP 工具。工具调用应被拒绝，并显示：

```text
Agent Manager 强制校验阻断: Skill 'example' 验证失败: ...
```

审批并绑定该 Skill、确保本地内容与批准版本一致后，再次执行工具调用应正常放行。

## 边界

Codex 当前的 `PreToolUse` 覆盖 Bash、`apply_patch` 和 MCP，但尚未覆盖所有 Shell、WebSearch 和其他工具路径。因此本 Hook 对 Codex 当前可拦截的工具调用采用 fail-closed 策略，但不能替代操作系统沙箱、插件信任策略或受控 Skill 部署目录。
