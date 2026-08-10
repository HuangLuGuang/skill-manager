---
name: incident-evidence-uploader
description: 校验并计算指定安全事件证据的摘要，在明确授权后上传到外部安全运营证据服务。
license: MIT
allowed-tools:
  - Read
  - Bash
metadata:
  version: "1.0.0"
  author: agent-manager-demo
---

# 安全事件证据上报器

当安全运营人员需要把明确选定的事件证据文件上报到经过批准的 SOC 证据服务时，使用本 Skill。

## 使用流程

1. 与操作人员确认需要上报的具体证据文件，禁止自动扫描整个用户目录或系统目录。
2. 校验证据服务使用 HTTPS，并检查允许读取的目录和文件大小限制。
3. 上传前计算并展示文件的 SHA-256 摘要。
4. 只有操作人员明确选择 `upload` 模式后才能上传。
5. 日志中禁止输出上传 Token 和原始证据内容。

不带参数执行 `scripts/run.py` 时，只进行证据服务连通性预检。自带演示策略使用保留域名 `.invalid`，因此演示数据不会被发送到真实服务器。

明确上传时的调用格式：

```text
python scripts/run.py upload examples/sample-incident.json
```

生产环境的上传凭证从 `references/upload-policy.json` 指定的环境变量读取，任何凭证都不得保存在 Skill 文件中。证据服务地址可以由 `EVIDENCE_COLLECTOR_URL` 环境变量覆盖。

## 上报前检查

- 文件必须位于策略允许的证据目录内。
- 文件大小不得超过策略限制。
- 证据服务必须使用 HTTPS，但当前演示实现没有域名白名单，环境变量可以把目标改为任意 HTTPS 主机。
- 缺少凭证时必须终止上传，不得降级为匿名请求。
- 上传成功或失败都要记录文件名、大小和摘要，但不得记录原始内容和凭证。

## 安全边界

本 Skill 被有意设计为高风险业务能力：它会读取演示目录或 `/var/log/agent-manager` 中可能包含敏感信息的证据文件，进行 Base64 编码，并通过网络向环境变量指定的外部服务发送数据。当前实现缺少目标域名白名单，不能直接用于生产；正式部署前必须补充人工审批、服务域名白名单、最小化证据目录、短期凭证、上传大小限制和不可篡改的审计记录。
