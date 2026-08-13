# Customer Operations MCP Demo

This deterministic demo supports the help-center scenario “MCP high-risk customer operation approval”. It contains only fictitious records and exposes two Tools:

- `customer_search`: read-only customer lookup.
- `customer_suspend`: changes a fictitious customer's service state and is intended to be marked high risk in Agent Manager.

## 中文说明

这个可复现案例用于演练“高风险 MCP 客户操作审批”，只包含虚构客户数据：

- `customer_search`：只读客户查询，作为低风险 Tool。
- `customer_suspend`：改变虚构客户的服务状态，应在平台中配置为高风险 Tool。

首次使用包含该案例的源码版本时，重新构建 Backend，并启动可选示例服务：

```bash
./build.sh --backend
docker compose --profile examples up -d mcp-demo backend nginx
docker compose ps mcp-demo
```

该服务只连接 Compose 应用网络，不发布宿主机端口。默认上游凭证为
`Bearer mcp-demo-change-me`；除一次性演示外，应通过 `.env` 设置
`MCP_DEMO_TOKEN` 覆盖它。

平台默认阻止 HTTP 和私网 MCP 目标。仅在本地隔离演示中，使用下方命令取得 Compose
应用网络的准确子网，把 `mcp-demo` 和输出的 CIDR 加入
`MCP_OUTBOUND_ALLOWLIST`，同时设置 `MCP_ALLOW_HTTP=true`，然后重建 Backend。
生产环境必须使用 HTTPS、安全注入的凭证和范围更窄的出站白名单。

在“模型网关 → MCP 服务”以 `customer-ops` 作为 Server 标识登记
`http://mcp-demo:8091/mcp`，发现两个 Tool；把 `customer_suspend` 配置为高风险，
再创建标识也为 `customer-ops` 的虚拟网关并发布两个 Tool。随后创建只允许访问该网关的
MCP 接入凭证，通过本目录的 `call_demo.py` 演练：

```bash
export MCP_GATEWAY_TOKEN="amat_xxx"
python3 demo/mcp-customer-operations/call_demo.py search
python3 demo/mcp-customer-operations/call_demo.py suspend
```

第一次暂停操作应以退出码 `3` 返回审批申请 ID，且不会到达示例服务。审批后携带同一
申请 ID 重试，并在 MCP 调用审计中核对最终结果。审批是同一凭证、网关、Tool 和 Tool
Schema 的限时授权，不绑定单次参数，也不是一次性授权；应使用较短有效期。执行
`docker compose restart mcp-demo` 可恢复初始虚构数据。

## Start with Docker Compose

Rebuild Backend once after obtaining a release that contains this demo, then start the optional example service:

```bash
./build.sh --backend
docker compose --profile examples up -d mcp-demo backend nginx
docker compose ps mcp-demo
```

The service is only attached to the Compose application network and is not published on a host port. Its initial upstream credential is `Bearer mcp-demo-change-me`; override `MCP_DEMO_TOKEN` in `.env` outside disposable demonstrations.

Agent Manager blocks HTTP and private destinations by default. For this local-only demo, obtain the Compose application network subnet:

```bash
APP_NETWORK="$(docker inspect "$(docker compose ps -q backend)" \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  | grep '_app$' | head -n 1)"
docker network inspect "$APP_NETWORK" --format '{{(index .IPAM.Config 0).Subnet}}'
```

Set `MCP_ALLOW_HTTP=true` and add both `mcp-demo` and the exact printed subnet to `MCP_OUTBOUND_ALLOWLIST`, then recreate Backend. These settings are for the isolated local demo only; production MCP services should use HTTPS and a narrow destination allowlist.

## Verify the upstream directly

```bash
docker compose exec backend python - <<'PY'
import json, urllib.request
body = {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
request = urllib.request.Request(
    "http://mcp-demo:8091/mcp",
    data=json.dumps(body).encode(),
    headers={"Authorization":"Bearer mcp-demo-change-me","Content-Type":"application/json"},
)
print(urllib.request.urlopen(request).read().decode())
PY
```

Register `http://mcp-demo:8091/mcp` in MCP Governance with Server slug `customer-ops`, discover the Tools, mark `customer_suspend` as high risk, and publish both Tools through a gateway whose slug is also `customer-ops`. If different slugs are required, pass them to the caller with `--server-slug` and `--gateway-slug`.

Create an MCP gateway credential allowed to access `customer-ops`, then call through Agent Manager:

```bash
export MCP_GATEWAY_TOKEN="amat_xxx"
python3 demo/mcp-customer-operations/call_demo.py search
python3 demo/mcp-customer-operations/call_demo.py suspend
```

The first suspend call exits with code `3` and prints an approval request ID. It has not reached the demo server. Approve the request in “MCP Governance → Call Approvals”, then retry with the same ID:

```bash
python3 demo/mcp-customer-operations/call_demo.py suspend \
  --approval-request-id mcpapr_xxx
```

Approval creates a time-bound authorization for the same credential, gateway, Tool, and Tool Schema. It is not restricted to one argument set. Use a short validity period and review Call Audit after execution.

Restarting the demo service resets its in-memory customer state:

```bash
docker compose restart mcp-demo
```
