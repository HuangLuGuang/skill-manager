# Agent Security Mock Target

P2 可重复验收目标，使用 Python 标准库提供 `POST /chat`。请求体格式：

```json
{"message": "{{prompt}}", "conversation_id": "optional"}
```

响应转换路径为 `reply`，会话响应路径为 `conversation_id`。特殊输入：

- `[timeout]`：延迟 3 秒。
- `[oversize]`：返回约 2 MiB 内容。
- `[malicious]`：返回 HTML、伪造密钥和原型污染字段，用于验证脱敏与安全渲染。
- `[prompt-injection]`、`[sensitive-leak]`、`[authorization-bypass]`、`[tool-abuse]`：返回四类可重复的
  风险行为。用例输入和期望稳定风险编码见 `cases.json`。

启动：

```bash
python demo/agent-security-mock-target/server.py
```

Mock 只负责提供确定性目标行为；是否形成 Finding 仍由锁定的 AI-Infra-Guard 扫描引擎和评估模型
共同判定，`expected_risk_code` 是验收预期，不是 Mock 直接伪造的扫描结果。
