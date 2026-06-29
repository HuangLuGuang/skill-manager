# Agent Manager 验证参考

仅在验证命令无法执行或环境变量缺失时阅读本文件。正常情况下只运行：

`python scripts/agent_manager_skill_verifier.py verify --path /path/to/skill`

## 路径要求

`--path` 是本机 Skill 目录路径，必须指向包含 `SKILL.md` 的目录。优先使用绝对路径，例如：

`python scripts/agent_manager_skill_verifier.py verify --path /Users/me/.codex/skills/some-skill`

不要把父级 `skills` 目录、压缩包路径、单个 `SKILL.md` 文件路径传给 `--path`。

## 环境变量

必须配置：

```bash
export AGENT_MANAGER_BASE_URL="http://agent-manager.example.com"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_ID="your-agent-id"
```

如果服务端配置了 `AGENT_MANAGER_SIGNING_KEY`，Agent 环境也必须使用同一个值。

## 阻断口径

命令退出码不是 `0` 时，不要读取、总结、加载、注册工具或执行该 Skill。

只提示：请联系管理员在 Agent Manager 中审批通过后再使用。
