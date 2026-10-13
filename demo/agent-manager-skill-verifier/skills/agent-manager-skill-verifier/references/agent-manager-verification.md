# Agent Manager 验证参考

仅在验证命令无法执行或环境变量缺失时阅读本文件。正常情况下只运行：

`python3 "<Verifier安装目录>/scripts/agent_manager_skill_verifier.py" verify --path "<目标Skill目录绝对路径>"`

脚本路径从宿主提供的本 Verifier 基准目录解析，使用单条 Python 命令，并从宿主工具结果读取退出码。每次使用前重新执行，不能复用前一次成功结果。

不要拼接 `; echo ...` 等后续命令，以免覆盖 Verifier 退出码。校验与目标 Skill 执行使用独立工具调用。

**English:** Resolve the absolute script path from this Verifier's host-supplied base directory. Quote paths, run one Python command and read its exit status from the host tool result. Verify again before each use.

Do not append commands such as `; echo ...`, which replace the reported exit code. Use separate tool calls for verification and target Skill execution.

Codex 的 `exec_command` 显式设置 `login: false`，继承本次启动环境。登录 Shell 可能覆盖平台地址或凭证，造成连接到其他地址，或在凭证移除后重新注入旧值。遇到缺少凭证时停止，不从旧配置自动补回。

**English:** Set `login: false` explicitly in Codex `exec_command` to inherit the current launch environment. Login-shell startup configuration may replace the URL or reintroduce an old credential after removal. Stop on missing credentials instead of restoring them from old configuration.

## 路径要求

`--path` 是本机 Skill 目录路径，必须指向包含 `SKILL.md` 的目录。优先使用绝对路径，例如：

`python3 "<Verifier安装目录>/scripts/agent_manager_skill_verifier.py" verify --path "/Users/me/.codex/skills/some-skill"`

不要把父级 `skills` 目录、压缩包路径、单个 `SKILL.md` 文件路径传给 `--path`。

## 环境变量

必须配置：

```bash
export AGENT_MANAGER_VERIFIER_BASE_URL="http://agent-manager.example.com"
export AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"
export AGENT_ID="your-agent-id"
export AGENT_MANAGER_VERIFIER_LANG="zh-CN"
```

不要复用 `SKILL_SCANNER_TOKEN`；Verifier 需要 Agent 运行凭证。

变量必须由实际 Agent 进程继承。终端 export 不会自动影响已启动的桌面应用；按宿主支持的方式配置启动环境并重启。跨机器使用运行端可达的平台地址。AGENT_ID 必须与凭证绑定身份一致；verify 最少需要 runtime:verify-signature 和 runtime:can-load。

**English:** Configure these variables in the actual Agent launch environment and restart as needed. Terminal exports do not affect already running desktop apps. Use an endpoint reachable from the runtime and an AGENT_ID matching the credential binding. verify requires runtime:verify-signature and runtime:can-load; set AGENT_MANAGER_VERIFIER_LANG=en-US for English output.

只有执行 `submit` 或 `status` 子命令时才使用独立的 Scanner 接入凭证，可通过 `AGENT_MANAGER_SCANNER_TOKEN` 或该子命令的 `--token` 传入。

Agent 环境只计算无密钥内容摘要，不得复制或配置 Agent Manager 的签名私钥。

## 阻断口径

命令退出码不是 `0` 时，不要读取、总结、加载、注册工具或执行该 Skill。

优先按脚本输出提示用户，不要把所有阻断都说成“未审批”：

- Skill 未审批：请联系管理员审批通过。
- Skill 已批准但当前 Agent 未授权：请联系管理员在 Agent Manager 的“智能体管理”中把该 Skill 绑定到当前智能体。
- 内容完整性不一致：本地 Skill 与平台批准版本不一致，需要重新提交扫描审批或使用批准版本。
- 凭证权限不足：请在“统一凭证中心”为 Agent 运行凭证补充运行时校验权限。
