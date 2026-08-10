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
export AGENT_MANAGER_VERIFIER_BASE_URL="http://agent-manager.example.com"
export AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"
export AGENT_ID="your-agent-id"
```

不要复用 `SKILL_SCANNER_TOKEN`；Verifier 需要 Agent 运行凭证。

只有执行 `submit` 或 `status` 子命令时才使用独立的 Scanner 接入凭证，可通过 `AGENT_MANAGER_SCANNER_TOKEN` 或该子命令的 `--token` 传入。

Agent 环境只计算无密钥内容摘要，不得复制或配置 Agent Manager 的签名私钥。

## 阻断口径

命令退出码不是 `0` 时，不要读取、总结、加载、注册工具或执行该 Skill。

优先按脚本输出提示用户，不要把所有阻断都说成“未审批”：

- Skill 未审批：请联系管理员审批通过。
- Skill 已批准但当前 Agent 未授权：请联系管理员在 Agent Manager 的“智能体管理”中把该 Skill 绑定到当前智能体。
- 内容完整性不一致：本地 Skill 与平台批准版本不一致，需要重新提交扫描审批或使用批准版本。
- 凭证权限不足：请在“统一凭证中心”为 Agent 运行凭证补充运行时校验权限。
