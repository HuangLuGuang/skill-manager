# Dify Runtime Adapter

适配版本：Dify `1.15.0`、graphon `0.5.3`。将 Python 接入包挂载到 Dify 的 `api` 和 `worker`，通过 `sitecustomize` 安装运行检查点。平台复用运行凭证、RuntimeTask、RuntimeAction、RuntimeApproval 和运行轨迹。

## 管控范围

| 能力 | 执行位置 |
| --- | --- |
| 节点、模型调用观察 | 工作流节点上下文、ModelInstance |
| HTTP 目标和方法 | HTTP 节点解析参数后、发请求前 |
| 工具名称和参数摘要 | ToolEngine 调用前 |
| Code 节点代码摘要 | CodeExecutor 提交 Sandbox 前 |
| 知识库范围 | Knowledge Retrieval 节点执行前 |
| 工作流版本准入 | 标准化节点与连线的 SHA-256 |
| 人工审批 | 节点首个受控调用前暂停；通过 Dify 原生持久化检查点恢复 |
| 简单先后顺序规则 | 当前运行已有成功动作的节点类型 |

规则按列表顺序首个匹配生效。`after_node_type` 表示同一次运行已有该类型的成功动作，不代表数据来源分析。观察模式记录策略判断但允许执行；管控模式在授权服务不可达时阻止新增受控调用。结果及观察事件写入本地 SQLite 队列后重试；队列满时管控模式阻止新增调用，观察模式输出事件丢失告警。

审批绑定运行、节点执行 ID、调用序号、参数摘要和策略版本。批准不直接执行工具；恢复后还要消费一次性授权。授权消费响应丢失时，管控模式停止，避免猜测并重复执行。已开始的外部副作用不能撤回。

当前范围为经过这些检查点的调用。插件进程内部网络、Sandbox 内部系统调用、HTTP 重定向后的每次网络跳转不属于此 Adapter 的逐次授权范围。需要这些边界时应配合出口代理、Sandbox 策略及模型/MCP 网关。仅进程在线不代表完整覆盖；升级 Dify 必须重新适配并执行验收。

## 接入

1. 在 Agent 资产管理中创建 Dify 目标，配置准确的 Workspace ID、App ID；创建平台 Agent。
2. 打开“Dify 运行接入”，绑定目标与 Agent，并填写实例标识。
3. 在凭证中心创建绑定此 Agent 的运行凭证：`runtime:trace`，管控另需 `runtime:govern`。凭证的用户/用户组须与资产归属一致。
4. 准备两个权限为 `0600` 的 JSON 文件：

`config.json`：
```json
{
  "server_url": "https://agent-manager.example.com",
  "applications": [{
    "binding_id": "替换为平台绑定ID",
    "workspace_id": "替换为Dify工作区ID",
    "app_id": "替换为Dify应用ID",
    "mode": "observe"
  }]
}
```

`credentials.json`：
```json
{"替换为平台绑定ID": "替换为实际运行凭证"}
```

5. 在可访问 Docker 的宿主机生成接入目录：

```bash
python3 integrations/dify-runtime/install.py \
  --compose /srv/dify/docker/docker-compose.yaml \
  --project dify \
  --config /secure/config.json \
  --credentials /secure/credentials.json \
  --output /srv/dify/agent-manager-adapter
```

`--compose` 可重复，顺序须与原部署一致。脚本检查镜像版本与已有 `sitecustomize`，保留原 PYTHONPATH，复制无额外依赖的 Adapter，创建 API/Worker 独立队列目录。输出目录必须尚不存在。平台地址应从容器可达；容器的 `127.0.0.1` 指向容器自身。

6. 等运行中工作流结束，在维护窗口使用原部署参数并添加生成的覆盖文件：

```bash
docker compose -p dify \
  -f /srv/dify/docker/docker-compose.yaml \
  -f /srv/dify/agent-manager-adapter/compose.json \
  up -d --no-deps --force-recreate api worker
```

原部署的环境文件、其他 Compose 文件及副本配置也应保留。后续部署继续携带覆盖文件。新增挂载与环境变量需要重建容器。非默认容器用户须预先配置配置文件读取权及队列目录写入权。

API 容器地址改变后，使用静态上游解析的 Nginx 需在 API 就绪后执行 `docker compose` 加原部署参数及 `exec nginx nginx -s reload`，刷新上游地址。SQLite 队列应由同一 Docker 主机中的进程访问；macOS/Windows 宿主机不要同时直接打开运行中容器的 WAL 数据库，诊断请在容器内执行或先制作一致性备份。

7. 在观察模式确认进程检查点和实际节点事件；再对测试应用启用管控，验证拒绝目标的接收端为零请求、批准后只执行一次、拒绝/过期/策略变更后不执行。切换到管控后确认进程已收到新模式。最后收到的模式保存在队列数据库中，重启后继续使用；新建队列目录时使用交付配置中的启动模式。

## 策略示例

```json
{
  "default": "allow",
  "approved_graphs": [],
  "approval_seconds": 120,
  "max_actions": 500,
  "rules": [
    {"rule_id": "review-post", "node_type": "http-request", "method": "POST", "effect": "approval"},
    {"rule_id": "block-after-retrieval", "host": "external.example.com", "after_node_type": "knowledge-retrieval", "effect": "deny"}
  ]
}
```

`approved_graphs` 为空表示未启用版本准入；填入运行记录或 DSL 资产报告中的工作流摘要后，只允许这些版本的受控动作。调整规则时平台递增策略版本，旧的待审批或未消费授权失效。

卸载：停止新任务并等已有工作流结束，移除覆盖文件参数，使用原部署参数重建 API/Worker。保留队列直到事件补传完毕；不要直接删除正在使用的接入文件。

## English

Supports Dify 1.15.0 with graphon 0.5.3. Mount the generated package into API and Worker, then recreate both services with the original Compose arguments plus `compose.json`. Credentials must belong to the asset owner and have `runtime:trace` and, for enforcement, `runtime:govern`.

The adapter observes workflow/model events and authorizes HTTP, tool, code and retrieval calls at the listed invocation points. Policies support graph digests, ordered rules, one-time authorization and approval through Dify's persisted workflow checkpoints. Prior-step rules match completed action types, not data lineage. Verify actual side effects separately from heartbeat receipt.

Plugin internals, sandbox system calls and individual redirected HTTP hops need separate controls. Enforce mode blocks new controlled calls when authorization is unavailable. Observe mode permits execution and logs telemetry loss if its bounded queue is full. Preserve queue files for delivery; revalidate every Dify upgrade.
