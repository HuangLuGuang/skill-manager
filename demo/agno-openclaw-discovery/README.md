# Agno OpenClaw Discovery Demo

这个 demo 做两件事：

1. 把 OpenClaw 内网发现逻辑封装成一个 Agno skill
2. 用一个 Agno agent 去加载这个 skill，并调用 skill 脚本执行扫描

主要文件：

- [main.py](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery/main.py)
- [SKILL.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery/skills/openclaw-network-discovery/SKILL.md)
- [discover_openclaw.py](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery/skills/openclaw-network-discovery/scripts/discover_openclaw.py)
- [usage.md](/Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery/skills/openclaw-network-discovery/references/usage.md)

## Install

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery
uv sync
```

## Environment

```bash
export DEEPSEEK_API_KEY="your-deepseek-key"
export AGNO_MODEL_ID="deepseek-chat"
export AGNO_MODEL_BASE_URL="https://api.deepseek.com"
```

可选：

```bash
export OPENCLOW_TARGET="192.168.1.10:18789"
```

## Run

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery
uv run python main.py
```

也可以直接传参数，这样更适合实际测试：

```bash
uv run python main.py --target 127.0.0.1:18789 --port 18789 --timeout 3 --concurrency 20
```

扫描网段示例：

```bash
uv run python main.py --target 192.168.1.0/24 --port 18789 --concurrency 20
```

## Direct Script Test

如果你想先跳过 Agent，直接测试 skill 脚本：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager/demo/agno-openclaw-discovery/skills/openclaw-network-discovery/scripts
uv run python discover_openclaw.py --target 127.0.0.1:18789
```

## Notes

- 这个 skill 只允许私网 IP、CIDR、私网 URL 或私网地址范围
- 默认端口是 `18789`
- 识别结果会分为 `confirmed`、`suspicious`、`open_non_http`
- Agent 现在被要求必须先执行脚本，再基于脚本 JSON 结果回答
