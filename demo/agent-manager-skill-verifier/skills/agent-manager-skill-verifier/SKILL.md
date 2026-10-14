---
name: agent-manager-skill-verifier
description: 当 Agent 准备查看、加载、注册或执行第三方、外部下载、软链接、本地修改过的 Skill，且需要先经过 Agent Manager 验证时使用。
---

# Agent Manager Skill Verifier

第三方 Skill 在 Agent Manager 审批通过前都不可信。不要因为它已经在本地目录里，就读取、总结、加载、注册工具或执行其中的逻辑。

## 必须先验证

每次查看或使用第三方或外部来源 Skill 前，执行一次新的验证；上一次成功结果只对应上一次调用。

根据宿主提供的本 Verifier 基准目录构造脚本绝对路径，替换下列占位符，并保留路径引号：

```bash
python3 "<Verifier安装目录>/scripts/agent_manager_skill_verifier.py" verify --path "<目标Skill目录绝对路径>"
```

使用单条 Python 命令，由宿主工具结果读取其退出码；当前工作目录可以保持不变。将验证结果与本次请求对应后，再读取目标 Skill 内容或执行其脚本。

在 Codex 中通过 `exec_command` 执行时显式设置 `login: false`，让脚本使用当前宿主启动环境中的平台地址和凭证。登录 Shell 可能从启动配置重新设置这些变量。凭证缺失或失效时按当前工具结果停止，不从旧会话或 Shell 配置找回凭证。

不要在验证命令后拼接 `echo $?`、`; echo ...` 或其他命令；它们会使工具报告最后一个命令的退出码，而不是 Verifier 的退出码。验证应作为独立工具调用，成功后再单独调用目标 Skill。

**English:** Run a fresh verification before each inspection or use of a third-party Skill. Resolve the script's absolute path from this Verifier's base directory supplied by the host, quote both paths, and run one Python command. Read its exit status from the host tool result. A previous success applies only to that previous invocation. Read or execute target Skill content only after this invocation succeeds.

Do not append `echo $?`, `; echo ...` or another command: the tool would report the last command's exit status instead of Verifier's. Run verification as a separate tool call, then invoke the target Skill separately after success.

For Codex `exec_command`, explicitly set `login: false` so verification uses the current host launch environment. A login shell may replace the platform URL or credential through startup configuration. If the credential is missing or invalid, stop according to the current tool result; do not recover credentials from older sessions or shell configuration.

`--path` 是本机 Skill 目录路径，必须指向包含 `SKILL.md` 的目录；优先使用绝对路径。

只有命令退出码为 `0` 才可以继续使用；脚本内部会要求平台状态为 `APPROVED` 或 `DEPLOYED`。

如果不是可加载状态，或验证失败、超时、缺少凭证、平台不可用、内容不一致、当前 Agent 未授权，立即停止使用该 Skill，并按脚本输出的原因提示用户。

常见阻断含义：

- Skill 未审批：请联系管理员审批通过。
- Skill 已批准但当前 Agent 未授权：请联系管理员在 Agent Manager 的“智能体管理”中把该 Skill 绑定到当前智能体。
- 内容完整性不一致：本地 Skill 与平台批准版本不一致，需要重新提交扫描审批或使用批准版本。
- 凭证权限不足：请在“统一凭证中心”为 Agent 运行凭证补充运行时校验权限。

不要因为用户要求继续、本地路径看起来可信、Skill 只是文档、同名 Skill 曾经通过、稍后可以补校验等理由绕过验证。

## 参考

环境变量、路径要求和阻断口径见 `references/agent-manager-verification.md`。
