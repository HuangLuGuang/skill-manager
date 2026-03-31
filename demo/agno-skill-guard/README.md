# Agno Skill Guard Demo

这个示例演示的是：

1. Agent 在加载本地 skill 前先计算签名
2. 调用 Skill Manager 的运行时接口验证本地签名
3. 再调用 `can-load` 做注册状态检查
4. 用 Agno 的 `Skills(loaders=[LocalSkills(...)])` 真正加载 skill
5. 用 Agno `tool_hooks` 拦截 skill 工具调用并走 `check-tool`

这个 demo 适合指导别人把 Agno Agent 接到当前 Skill Manager 系统上。

## Demo Scope

这个样例刻意只用一个 Agent，不引入 Team 或 Workflow，方便先把“安全加载 skill”这条链路跑通。

## Files

- [main.py](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard/main.py)
  Agno demo 主程序
- [AGENTS.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard/AGENTS.md)
  Agno 开发约束
- [pyproject.toml](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard/pyproject.toml)
  demo 依赖

## Start The Skill Manager API

推荐直接启动不带后台登录的 Skill Manager API，方便外部 Agent 直接调用：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
uv run skill-manager-api --host 0.0.0.0 --port 8080
```

如果你用的是集成后的后台服务 `backend.main:app`，当前 `/api/v1` 仍然挂在后台登录态后面，不适合外部 Agent 直接接。真正面向 Agent 的 token 鉴权后面还要补。

## Install Demo Dependencies

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard
uv sync
```

## Quick Start

下面这组命令可以从零开始把 demo 跑起来。

### 1. 退出旧虚拟环境

如果你之前激活过 `.scan-venv`，建议先退出，避免一直看到 `VIRTUAL_ENV` warning：

```bash
deactivate 2>/dev/null || true
```

### 2. 启动 Skill Manager API

打开一个终端窗口：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
uv sync
uv run skill-manager-api --host 0.0.0.0 --port 8080
```

### 3. 配置 Agno demo 依赖和模型环境变量

打开第二个终端窗口：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard
uv sync
export SKILL_MANAGER_BASE_URL="http://127.0.0.1:8080"
export DEEPSEEK_API_KEY="your-deepseek-key"
```

如果 Skill Manager 服务端设置了 `SKILL_MANAGER_SIGNING_KEY`，这里也要设置同一个值：

```bash
export SKILL_MANAGER_SIGNING_KEY="same-key-used-by-skill-manager"
```

### 4. 提交一个真实 skill

这里用 Agno cookbook 里的 `git-workflow` 做正常样例：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
uv run skill-manager submit /Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow
```

如果你想让脚本执行也通过，确认这个 skill 在 `allowed-tools` 里声明了 `Read` 和 `Bash`。

### 5. 运行正常样例

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard
uv run python git_workflow_demo.py
```

预期结果：

- demo 会先本地计算 skill 签名
- 再请求 Skill Manager 做验签和 `can-load`
- 通过后才创建 Agno `Skills(loaders=[LocalSkills(...)])`
- 然后 agent 读取 skill 内容并输出结构化结果

### 6. 运行恶意 skill 阻断样例

先把恶意样例解压并提交：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
tmpdir=$(mktemp -d)
unzip -q /Users/huangluguang/Desktop/Project/skill-manager/tests/skills/exfiltrator.zip -d "$tmpdir"
uv run skill-manager submit "$tmpdir/exfiltrator" --behavioral
```

再运行：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard
uv run python malicious_exfiltrator_demo.py
```

预期结果：

- 不会成功加载 skill
- 终端会打印 `Expected block: ...`
- 阻断原因通常是：
  - 自动拒绝
  - 不是 `APPROVED/DEPLOYED`
  - 或签名/运行时校验未通过

## Required Environment Variables

```bash
export SKILL_MANAGER_BASE_URL="http://127.0.0.1:8080"
export DEEPSEEK_API_KEY="your-deepseek-key"
```

可选变量：

```bash
export AGNO_MODEL_ID="deepseek-chat"
export AGNO_MODEL_BASE_URL="https://api.deepseek.com"
export AGNO_API_KEY="$DEEPSEEK_API_KEY"
export SKILL_MANAGER_SIGNING_KEY="same-key-used-by-skill-manager"
export AGENT_ID="agno-demo-agent"
```

如果服务端启用了 `SKILL_MANAGER_SIGNING_KEY`，Agent 端必须用同样的 key 计算本地签名。

这个 demo 默认使用：

- 模型：`deepseek-chat`
- 接口：`https://api.deepseek.com`

底层仍然使用 Agno 的 `OpenAIChat`，因为 DeepSeek 提供 OpenAI 兼容接口。
为了兼容 DeepSeek 不接受 `developer` role 的限制，demo 里已经显式配置了 role map，把 `developer` 映射成 `system`。
同时也关闭了 OpenAI 原生 structured output，避免 DeepSeek 对 `response_format` 的兼容性报错。

## Run

```bash
uv run python main.py \
  --skill-name byd-stock-news \
  --skill-path /absolute/path/to/byd-stock-news \
  --question "总结这个 skill 的用途，并说明它是否可以安全加载"
```

## Real Cookbook Example

这个 demo 现在还附带了一个直接可测的真实样例：

- [git_workflow_demo.py](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard/git_workflow_demo.py)

它默认使用你本地 Agno cookbook 里的真实 skill：

- `/Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow`

这个 skill 同时包含：

- `SKILL.md`
- `references/commit-types.md`
- `scripts/commit_message.py`

先把这个 skill 提交到 Skill Manager：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
uv run skill-manager submit /Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow
```

然后直接跑：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard
uv run python git_workflow_demo.py
```

这个例子更适合实际测试，因为它不是空目录，也不是手写假 skill，而是 Agno cookbook 里的真实示例 skill。

## Malicious Skill Blocking Example

如果你想测试 Skill Manager 是否会在 Agno 加载前阻断恶意 skill，可以直接跑：

- [malicious_exfiltrator_demo.py](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard/malicious_exfiltrator_demo.py)

它默认使用测试样例：

- `/Users/huangluguang/Desktop/Project/skill-manager/tests/skills/exfiltrator.zip`

这个样例的恶意点比较明确：

- 读取环境变量里的 `API_KEY`
- 向外部地址发起 `requests.post`
- 使用 `eval`

先手动解压再提交：

```bash
tmpdir=$(mktemp -d)
unzip -q /Users/huangluguang/Desktop/Project/skill-manager/tests/skills/exfiltrator.zip -d "$tmpdir"
uv run skill-manager submit "$tmpdir/exfiltrator" --behavioral
```

然后运行 demo：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-skill-guard
uv run python malicious_exfiltrator_demo.py
```

这个脚本的预期行为不是“Agent 正常回答”，而是：

- 在 Agno `LocalSkills(...)` 真正加载前
- 被本地签名校验或 `can-load` 状态校验阻断
- 最终打印 `Expected block: ...`

这更适合验证 Skill Manager 的价值点：**恶意 skill 不该被 agent 成功加载。**

## What This Demo Actually Does

### Step 1. Local Signature

Agent 先读取本地 skill 目录，使用与 Skill Manager 相同的算法计算签名。

### Step 2. Signature Verification

调用：

- `POST /api/v1/runtime/verify-skill-signature`

如果签名不一致，直接阻断加载。

### Step 3. Loadability Check

再调用：

- `GET /api/v1/runtime/can-load/{skill_name}`

如果 skill 当前不是 `APPROVED` 或 `DEPLOYED`，直接阻断。

### Step 4. Tool Guard

这个 demo 不是自己造一个假工具，而是直接使用 Agno Skills 提供的工具能力。当前会在 `tool_hooks` 里拦截这些 skill 相关函数：

- `get_skill_instructions`
- `get_skill_reference`
- `get_skill_script`

每次真正调用前，会先请求：

- `GET /api/v1/runtime/check-tool`

映射规则：

- `get_skill_instructions` -> `Read`
- `get_skill_reference` -> `Read`
- `get_skill_script(execute=false)` -> `Read`
- `get_skill_script(execute=true)` -> `Bash`

这样就能把 Agno skill 工具和 Skill Manager 的 `allowed_tools` 对齐。

## Expected Skill Declaration

如果你想让 demo 正常读取 skill 内容，skill 的 `allowed-tools` 里至少应该声明：

```yaml
allowed-tools:
  - Read
```

如果 skill 要允许执行脚本，还需要声明：

```yaml
allowed-tools:
  - Read
  - Bash
```

## Why Validation Happens Before Loading

Agno 当前常见示例是：

```python
skills=Skills(loaders=[LocalSkills(str(skills_dir))])
```

这意味着 skill 一旦交给 `LocalSkills`，Agent 就已经能访问它的 instructions、references 和 scripts。

所以这个 demo 把安全控制拆成两层：

1. **加载前校验**
   - 本地签名校验
   - `can-load` 状态校验
   - 只有通过后才创建 `Skills(loaders=[LocalSkills(...)])`

2. **工具调用时校验**
   - 用 `tool_hooks` 拦 `get_skill_*`
   - 每次调用前再走 `check-tool`

这样更接近真正的“load hook + runtime hook”效果。

## Notes

- 这是一个指导性 demo，不是生产模板。
- 生产环境建议把 Agent 自身也接入独立 token 鉴权。
- 生产环境建议把 Agent 持久化切到 Postgres，不要用 SQLite。
