# 模型供应商 Header 模拟服务

仅用于验证模型发现、连接测试和聊天请求的认证与 Header 传递，不调用真实模型，也不生成真实扫描结论。依赖复用项目 FastAPI、Uvicorn，无新增运行时依赖。

在仓库根目录启动：

```bash
uv run python demo/model-provider-header-mock/server.py
```

供应商页面配置：

| 配置 | 值 |
|---|---|
| Base URL | `http://127.0.0.1:18089/customer/v1` |
| 协议 | OpenAI Chat Completions |
| 认证方式 | 原始 Authorization（不添加 Bearer） |
| API Key | `mock-test-key`（公开测试值） |
| 自定义 Header 名称 | `X-Customer-ID` |
| 自定义 Header 值 | `demo-customer` |
| 模型 | `header-test-model` |

保存后获取模型、添加模型并点击测试。使用网关调用名称发起非流式或流式聊天，可收到明确标注为 mock 的固定回复。缺失任意必需 Header、值不匹配、重复 Header，或误选 Bearer 都返回 401；错误仅指出 Header 名称，不回显凭证。`/health` 无需认证，仅证明服务存活。

还可模拟客户要求的 Host 覆盖：

```bash
uv run python demo/model-provider-header-mock/server.py --expected-host model.customer.test
```

此时在供应商自定义 Header 中再添加 `Host: model.customer.test`。Base URL 仍用可达地址，不必配置 DNS。也可通过 `--authorization`、`--customer-id`、`--port` 调整测试值与端口。

## 直接验证

```bash
# 正确配置：200
curl -i http://127.0.0.1:18089/customer/v1/models \
  -H 'Authorization: mock-test-key' -H 'X-Customer-ID: demo-customer'

# Bearer 模式错误：401
curl -i http://127.0.0.1:18089/customer/v1/models \
  -H 'Authorization: Bearer mock-test-key' -H 'X-Customer-ID: demo-customer'

# 流式回复：200 + SSE + [DONE]
curl -N http://127.0.0.1:18089/customer/v1/chat/completions \
  -H 'Authorization: mock-test-key' -H 'X-Customer-ID: demo-customer' \
  -H 'Content-Type: application/json' \
  -d '{"model":"header-test-model","messages":[{"role":"user","content":"hello"}],"stream":true}'
```

启用 `--expected-host` 时，上述成功示例还需添加相应 `Host` Header。后台在 Docker 中时，`127.0.0.1` 指向容器自身；macOS Docker Desktop 可将服务以 `--host 0.0.0.0` 启动，并把 Base URL 改为 `http://host.docker.internal:18089/customer/v1`。远程后台需要填写从后台可达的本机地址并开放对应端口。使用这些公开测试凭证的服务仅应在测试网络暴露。

## 验收范围

- 正确双 Header：模型发现、连接测试、流式与非流式成功。
- 删除或改错 `X-Customer-ID`、删除 API Key、切换 Bearer：401；恢复后成功。
- 配置 Host 校验时，遗漏或改错 Host：401。
- JSON 模式返回 `{"mock":true,"headers_verified":true}`，并非 Skill/Agent 风险评估结构；本服务用于连通及请求头测试，不能作为真实扫描验收依据。

## English

Run the command above from the repository root. The mock requires exact raw `Authorization: mock-test-key` and `X-Customer-ID: demo-customer` on both model listing and chat endpoints. Bearer authentication, missing, duplicate or incorrect headers return 401 without exposing credentials. Optional `--expected-host` enforces an exact Host override. The health endpoint is unauthenticated. Streaming uses SSE ending in `[DONE]`; replies are deterministic mock data, not real inference or scan judgments. Defaults bind only to localhost. Container or remote backends require a reachable address as described above. All example credentials are public test values.
