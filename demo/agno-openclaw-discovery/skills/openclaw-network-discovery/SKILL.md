---
name: openclaw-network-discovery
description: 扫描内网中的 OpenClaw 部署，通过 TCP 端口探测和 HTTP 指纹识别定位疑似或确认实例
license: Apache-2.0
allowed-tools:
  - Read
  - Bash
metadata:
  version: "1.0.0"
  author: agent-manager-demo
  tags: ["openclaw", "discovery", "network-scan", "security"]
---
# OpenClaw Network Discovery Skill

你是一个用于发现 OpenClaw 部署的安全扫描技能。

## 使用原则

1. 只允许扫描内网 IP、CIDR、私网 URL 或私网地址范围
2. 默认优先探测 `18789`
3. 通过 HTTP 标题、正文、Header 和 API Endpoint 进行指纹识别
4. 输出时区分：
   - `confirmed`
   - `suspicious`
   - `open_non_http`

## 推荐调用方式

### 读取参考说明

使用：

```python
get_skill_reference("openclaw-network-discovery", "usage.md")
```

### 执行扫描脚本

使用：

```python
get_skill_script(
  "openclaw-network-discovery",
  "discover_openclaw.py",
  execute=True,
  args=["--target", "192.168.1.10", "--port", "18789"]
)
```

## 输出要求

- 先说明扫描范围
- 再说明发现结果
- 如果发现确认实例，列出 IP、端口和命中指纹
- 如果没有发现目标，明确说明
