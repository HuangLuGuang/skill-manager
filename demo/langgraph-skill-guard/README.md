# LangGraph Skill Guard Demo

这个 demo 演示的是：

1. 在 LangGraph agent 暴露 skill 能力之前，先用 Agent Manager 做：
   - 本地签名校验
   - `can-load` 状态校验
2. 校验通过后，才把本地 skill 包装成可调用工具
3. 每次读文件或执行脚本前，再用 Agent Manager 调 `check-tool`

## Why LangGraph Needs A Custom Loader

LangGraph / LangChain 没有像 Agno 那样现成的 `Skills(loaders=[...])` 机制。

所以这个 demo 的做法是：

- 先把一个本地 skill 目录封装成 `LoadedSkill`
- 再把它的能力注册成 LangChain tools
- LangGraph agent 只能通过这些受保护的 tools 访问 skill

## Files

- [main.py](/Users/huangluguang/Desktop/Project/skill-manager/demo/langgraph-skill-guard/main.py)
- [pyproject.toml](/Users/huangluguang/Desktop/Project/skill-manager/demo/langgraph-skill-guard/pyproject.toml)
- [AGENTS.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/langgraph-skill-guard/AGENTS.md)

## Install

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/langgraph-skill-guard
uv sync
```

## Environment

```bash
export AGENT_MANAGER_BASE_URL="http://127.0.0.1:8080"
export DEEPSEEK_API_KEY="your-deepseek-key"
```

可选：

```bash
export LANGGRAPH_MODEL="deepseek-chat"
export LANGGRAPH_BASE_URL="https://api.deepseek.com"
export LANGGRAPH_API_KEY="$DEEPSEEK_API_KEY"
export AGENT_MANAGER_ACCESS_TOKEN="smsc_live_xxx"
export AGENT_ID="langgraph-skill-guard-demo"
```

如果不设置 `AGENT_MANAGER_ACCESS_TOKEN`，demo 会走旧的 `/api/v1/runtime/...` 兼容路径；接入后台服务或生产环境时应使用带 runtime scope 的接入 Token。

## Agent Manager API

推荐先启动不带后台登录的 Agent Manager API：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
uv run agent-manager-api --host 0.0.0.0 --port 8080
```

## Prepare A Real Skill

默认示例用的是 Agno cookbook 里的真实 skill：

- `/Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow`

先把它提交到 Agent Manager：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
uv run agent-manager submit /Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow
```

## Run

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/langgraph-skill-guard
uv run python main.py
```

也可以自定义：

```bash
uv run python main.py \
  --skill-name git-workflow \
  --skill-path /Users/huangluguang/Desktop/github/agno/cookbook/02_agents/16_skills/sample_skills/git-workflow \
  --question "请总结这个 skill 的用途，并生成一个 conventional commit message"
```

## What Gets Verified

在 agent 真正开始前，会先做：

1. 对本地 skill 目录计算签名
2. `POST /api/v1/access/runtime/verify-skill-signature`
3. `GET /api/v1/access/runtime/can-load/{skill_name}`

在 tool 调用时，会再做：

1. `GET /api/v1/access/runtime/check-tool`
2. 只有允许后才会：
   - 读取 `SKILL.md`
   - 读取 reference
   - 执行脚本

## Current Tool Mapping

- `read_skill_manifest` -> `Read`
- `read_skill_reference` -> `Read`
- `run_skill_script` -> `Bash`

## Notes

- 这个 demo 默认使用 DeepSeek 的 OpenAI 兼容接口；也可以把模型地址指到 Agent Manager 的模型网关 `/v1`
- 如果 skill 没通过验证，agent 不会被创建
- 如果 tool 不被允许，对应调用会直接抛错
