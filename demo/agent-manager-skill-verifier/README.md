# Agent Manager Skill Verifier

这是一个通用 Agent skill 示例，用于指导支持本地 Skill 指令和脚本执行的 Agent 在使用第三方 Skill 前完成 Agent Manager 验证。

它依赖 Agent 遵循 `SKILL.md` 指令和脚本退出码，适合做跨平台的通用接入样例。对于 Hermes 等运行时，要真正强制生效，还应把同样的校验调用集成到 Skill loader 或 tool runtime。

## 目录

```text
skills/agent-manager-skill-verifier/
├── SKILL.md
├── references/
│   └── agent-manager-verification.md
└── scripts/
    └── agent_manager_skill_verifier.py
```

## 下载

管理台进入：

- `智能体管理`
- `接入与运行`
- `Agent Skill Verifier 接入`
- `下载 Skill Verifier`

后端接口：

```http
GET /api/v1/scanner/skill-verifier/download
```

下载得到：

```text
agent-manager-skill-verifier.zip
```

## 凭证权限

管理台指引顺序为：选择已有身份或登记身份 → 创建运行凭证 → 在运行端安装 → 配置环境 → 首次验证与运行审计。客户端已发现的 Agent 复用其现有身份。启用身份、授权已批准的 Skill，并准备同一批准版本的本地文件；仅使用 Verifier 无需绑定模型或 MCP。

执行 `verify` 时，在管理台 `智能体管理 -> 凭证管理` 创建 Agent 运行凭证并绑定目标 Agent。至少需要：

- `runtime:verify-signature`
- `runtime:can-load`

执行 `submit` 或 `status` 时使用独立的 Scanner 接入凭证，按需授予：

- `scanner:submit`
- `scanner:read-own-results`
- `scanner:read-own-sessions`

配置环境变量：

```bash
export AGENT_MANAGER_VERIFIER_BASE_URL="http://localhost:8001"
export AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"
export AGENT_MANAGER_SCANNER_TOKEN="amat_xxx"
export AGENT_ID="<agent-id>"
```

只执行 `verify` 时不需要设置 `AGENT_MANAGER_SCANNER_TOKEN`。Verifier 仅计算无密钥内容摘要，不持有 Agent Manager 的 Ed25519 私钥。

准备 Python 3 与 unzip。本文安装及 `export` 命令适用于 macOS / Linux 的 Bash / zsh；Windows 可手动解压，并在宿主启动环境配置同名变量。平台 URL 必须从运行端可达，跨机器时替换 `localhost`。终端 `export` 仅影响该终端及其子进程，已启动的桌面应用需配置宿主支持的启动环境并重启。使用 `AGENT_MANAGER_VERIFIER_LANG=zh-CN` 或 `en-US` 选择脚本及 API 错误语言。

不要复用 `SKILL_SCANNER_TOKEN`；Verifier 需要 Agent 运行凭证。

## 安装到 Codex

```bash
mkdir -p ~/.codex/skills
unzip agent-manager-skill-verifier.zip -d ~/.codex/skills/
```

安装后重启 Codex，或刷新 Codex 的 skill 列表。

当前 Codex 也支持项目级 `.agents/skills/`；本文的真实 Codex 验收使用该目录安装下载包，并通过宿主实际读取其中的 `SKILL.md` 确认发现成功。目录范围参考 [OpenAI 官方 Skill 文档](https://learn.chatgpt.com/docs/build-skills)。

**English:** Current Codex also supports project-local `.agents/skills/`. The real Codex acceptance below installs the downloaded package there and confirms discovery through the host's actual `SKILL.md` read. See the [official Skill documentation](https://learn.chatgpt.com/docs/build-skills) for discovery scopes.

## 安装到 Claude Code

```bash
mkdir -p ~/.claude/skills
unzip agent-manager-skill-verifier.zip -d ~/.claude/skills/
```

安装后重启 Claude Code，或刷新 Claude Code 的 skill 列表。

宿主执行 Verifier 时，使用它提供的 Skill 基准目录构造脚本绝对路径，并给路径加引号。验证命令应独立执行，从宿主工具结果读取 Python 的退出码，再决定是否读取或执行目标 Skill。不要拼接 `; echo ...`，以免用后续命令的退出码覆盖校验结果。每次使用都重新校验。

**English:** Resolve the Verifier script's absolute path from the Skill base directory provided by the host and quote paths. Execute verification as a separate tool call and use Python's exit status to decide whether to read or execute the target Skill. Do not append `; echo ...`, which replaces the reported exit status. Verify afresh before each use.

## 使用

提交第三方 skill：

```bash
python3 <skills-dir>/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py submit \
  --path /path/to/third-party-skill \
  --behavioral \
  --deep-scan
```

查看状态：

```bash
python3 <skills-dir>/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py status \
  --skill-id <skill-id>
```

使用前做内容完整性和加载授权校验：

```bash
python3 <skills-dir>/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \
  --path /path/to/third-party-skill
```

`submit` 从 `SKILL.md` 读取名称并连同文件指纹上传，服务端重新核对文件内容。缺少名称时在本地报错。默认不启用 LLM；按需显式增加 `--sandbox` 或 `--llm`。`--no-cache` 通过服务端 `force_rescan` 请求重新检测当前凭证有权访问的同内容版本，不会因为重新检测而创建新内容版本。

## 阻断策略

首次验证时，`--path` 指向包含 `SKILL.md` 的单个 Skill 绝对路径。确认退出码为 0，再到平台运行审计按 Agent ID、时间与 Skill 核对验签和加载许可记录。随后在真实 Agent 会话中确认每次使用前确实执行脚本；下载成功或一次终端验证成功均不证明后续调用已被强制拦截。

下面情况都应阻断使用第三方 skill：

- 未提交到 Agent Manager
- 仍在扫描中
- 待人工审核
- 已拒绝
- 未形成可信版本
- 本地内容和批准版本不一致
- `can-load` 返回不可加载
- 网络或 API 错误导致无法完成校验

默认不提供“用户确认后继续”的绕过路径。需要强制拦截时，应在具体平台上再实现 hook 或 runtime adapter。

## English onboarding

1. Open **Integration & Runtime → Agent Skill Verifier**. Reuse a Client-discovered identity or register a platform identity, enable it, authorize an approved Skill, and prepare the same files locally. Model and MCP bindings are optional separate integrations.
2. Create a credential bound to that Agent with only `runtime:verify-signature` and `runtime:can-load`. Save the one-time secret and return to the guide. `AGENT_ID` must match its binding.
3. Prepare Python 3 and unzip. Install the downloaded ZIP into the host's actual Skill directory, then refresh Skills or restart. The commands above use Bash / zsh on macOS / Linux; on Windows, extract manually and set the same variables in the host launch environment.
4. Set `AGENT_MANAGER_VERIFIER_BASE_URL`, `AGENT_MANAGER_AGENT_RUNTIME_TOKEN`, `AGENT_ID` and `AGENT_MANAGER_VERIFIER_LANG=en-US`. Use a service address reachable from the Agent machine. Terminal exports do not reach an already running desktop app; configure its launch environment and restart.
5. Run `python3 <skills-dir>/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify --path /absolute/path/to/skill`. Use one Skill containing `SKILL.md`, not its parent or a ZIP. Proceed only on exit code 0 and match signature/load decisions in runtime audit. Confirm the real Agent invokes the script before each use.

`verify` checks integrity, APPROVED / DEPLOYED status and loading permission; it does not call `check-tool`. Optional `submit` / `status` use a separate `AGENT_MANAGER_SCANNER_TOKEN` with `scanner:submit` / `scanner:read-own-results` respectively. Verifier follows Agent instructions; mandatory enforcement needs an actual Loader, Hook or SDK integration.

`submit` includes the name read from `SKILL.md` and a file fingerprint, which the server checks against the uploaded files. A missing name fails locally. `--no-cache` sends `force_rescan` to rerun detection on an existing content version accessible to this credential; it does not create a new content version. Enable Sandbox or LLM separately when required.

## HTTP 全链路回归 / HTTP end-to-end regression

在仓库根目录运行：

```bash
uv run pytest tests/test_skill_verifier_e2e.py -q -s
```

测试使用临时数据库、签名密钥、管理员身份和本机 HTTP 端口，调用实际 Agent / 凭证 / 下载 / Scanner / Runtime / 审计路由，解压服务端 ZIP 后以独立 Python 进程执行。覆盖中英文与 Codex / Claude Code 安装目录、上传与状态查询、审批与授权、成功校验、内容篡改、身份或凭证异常、网络不可达和重新检测。每轮输出 `acceptance-evidence.json` 路径，包含退出码、加载标记和审计记录，不包含完整凭证。

测试加载器使用 `verify && 后续动作`，成功时生成加载标记，任何失败均不得生成。该结果验证实际脚本与平台的行为，不证明第三方桌面宿主会自动调用 Verifier。测试只使用本地基础扫描与人工审批样例，不验证外部扫描器、LLM、Sandbox 的检测能力；管理台表单需单独人工验收。

**English:** Run the command above from the repository root. The test starts real project routers on a loopback HTTP port with temporary databases, signing keys and an administrator identity. It downloads and extracts the actual ZIP, then executes its Python CLI in separate processes. It covers both languages and Codex / Claude Code directory layouts, submission/status, approval/authorization, successful verification, tampering, identity/credential failures, connectivity failure and forced rescanning. Each run prints the path to `acceptance-evidence.json`, containing exit codes, load markers and audit records without full credentials. A conditional test Loader creates a marker only after successful verification. This proves CLI/API behavior, not automatic invocation by third-party desktop hosts. The fixture uses local basic checks and manual approval; external scanner, LLM and Sandbox detection capabilities and management UI acceptance are separate checks.

## 真实 Claude Code 宿主验收 / Real Claude Code acceptance

本机安装 Claude Code CLI，并已在 `~/.claude/settings.json` 的 `env` 中配置可用的 Anthropic-compatible 模型地址、模型名及凭证时，可从仓库根目录手动执行：

```bash
uv run python demo/agent-manager-skill-verifier/run_host_acceptance.py \
  --output-dir /tmp/verifier-host-evidence
```

输出目录须为空。此命令会调用现有模型服务，产生实际用量，不随 pytest 自动执行。它复用开发测试环境启动隔离 HTTP 服务，下载真实 Verifier ZIP，安装到隔离的 Claude 配置目录；工作目录和安装目录包含空格。日常 Claude 配置不修改，完整凭证不写入输出，临时宿主配置和安装目录在结束时清理。

首轮请求明确本会话“每次先验证”的使用规则，后续同一会话仅请求使用目标 Skill。依次测试首次成功、重复成功、本地内容变化后拒绝、恢复后成功、缺少运行凭证时拒绝、凭证吊销后拒绝。验证和业务脚本由 Claude Code 作为独立工具调用发起，不使用 `verify && 业务动作` 代替宿主判断。验收核对独立 Verifier 命令、工具结果、目标读取/执行顺序、业务标记及平台审计；失败轮次不得出现目标读取或执行。原始宿主事件经凭证脱敏后与结构化证据保存在输出目录。

Claude Code 正常结束并报告“拒绝使用”时，其进程退出码可能为 0；应检查 Verifier 工具调用的退出码和后续行为。一次六场景验收只证明该宿主版本、模型、会话规则及配置下的观察结果。需要与模型遵循指令无关的强制拦截时，仍须接入 Loader / Hook / SDK。

**English:** Install Claude Code CLI and configure a working Anthropic-compatible endpoint, model and credential in the `env` section of `~/.claude/settings.json`. Run the command above from the repository root with an empty output directory. This opt-in command makes real model calls and incurs usage; it is not run automatically by pytest. It uses the development test environment to start an isolated HTTP service, downloads the real ZIP and installs it under an isolated Claude configuration directory. Both paths include spaces. It leaves everyday Claude settings unchanged, redacts credentials from output and cleans up temporary host configuration on exit.

The first request establishes the verify-before-every-use rule; subsequent requests in the same session only ask to use the target Skill. The six cases cover first/repeated success, tampering, restoration, missing runtime credentials and revocation. Claude issues verification and business execution as separate tool calls. Acceptance checks Verifier commands and tool results, target access ordering, business markers and platform audit; denied turns must neither read nor execute the target. Redacted host events and structured evidence are saved in the output directory. Claude's overall exit code may be 0 when it correctly reports refusal: inspect the Verifier tool exit and subsequent actions. These observations apply to the tested host version, model, session rule and configuration. Model-independent enforcement still requires Loader / Hook / SDK integration.

## 真实 Codex 宿主验收 / Real Codex acceptance

本机 Codex 已登录且 CLI 支持当前配置的模型时，执行：

```bash
uv run python demo/agent-manager-skill-verifier/run_host_acceptance.py \
  --host codex --output-dir /tmp/verifier-codex-evidence
```

可用 `--codex-bin /absolute/path/to/codex` 指定已安装的其他 CLI。若模型服务提示 CLI 版本过旧，应使用兼容版本再验收；模型请求未成功不属于 Verifier 校验失败。

Codex 执行 Verifier 的 `exec_command` 应显式传 `login: false`，使用当前启动环境。实际排查中，登录 Shell 执行路径曾读到与启动时传入值不同的平台地址。缺少凭证时应停止，不从登录 Shell 或历史会话补回。还应确认 Shell 环境过滤规则允许运行凭证进入验证进程，并允许访问平台地址；只检查变量是否存在，不输出凭证明文。

脚本保留现有登录凭证位置和模型选择，使用 `--ignore-user-config` 隔离其他用户配置，安装到临时项目的 `.agents/skills/`。六次请求通过明确的会话 ID 恢复同一 Codex 会话；判断依据为原生 `command_execution` 的命令、退出码和时序，以及实际业务标记与平台审计。工作目录和平台数据会清理，Codex 原生会话记录按宿主常规方式保留。模型调用会产生实际用量。

首轮同样明确“每次使用前验证”，后续仅要求使用 Skill。重复、篡改、恢复、缺少凭证、吊销场景均检查新的 Verifier 调用，不以 Codex 最终回复或整体退出码作为通过依据。该验收仍属于特定宿主、模型与规则下的行为观察，不替代 Loader / Hook / SDK 的强制执行边界。

**English:** With Codex already signed in and a CLI compatible with the configured model, run the command above. Use `--codex-bin /absolute/path/to/codex` to select another installed executable. Upgrade to a compatible CLI when the model service rejects an old version; a failed model request is not a Verifier decision. The script retains existing authentication and model selection, isolates other user configuration with `--ignore-user-config`, and installs into a temporary project's `.agents/skills/`. It resumes the same explicit session ID for all six requests and checks native command events, actual exit codes, ordering, business markers and platform audit. Temporary workspace/platform data is removed; native Codex session history remains in its normal location. Model calls incur usage. The first request establishes the verify-before-each-use rule. Later requests only ask to use the Skill; each must invoke Verifier again. These finite observations do not replace mandatory Loader / Hook / SDK enforcement.

Explicitly set `login: false` in Codex `exec_command` when running Verifier. The login-shell execution path was observed to read a different platform URL from the one supplied at launch. Stop on missing credentials instead of restoring them from a login shell or session history. Ensure shell environment filters pass the runtime credential and network policy permits the platform endpoint. Check presence without printing credential values.
