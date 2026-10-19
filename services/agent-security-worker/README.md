# Agent Security Worker（P2/P3）

该独立进程同时支持：

- `control_plane_validation`：P1 任务领取、租约、预算和回传协议验证。
- 开放接口连接验证：带 `openapi_connection_test` 标记的控制面任务调用 `connection_probe.py`，使用登记版本的凭据和模型向 `/chat/completions` 发送最小文本对话，返回网络、TLS、认证和协议检查。HTTP 的 TLS 项为 `skipped`，HTTPS 验证证书。任务沿用原生租约、预算、地址范围和生产授权。
- `agent_risk_scan`：锁定 AI-Infra-Guard `v4.6.0` 的 Agent 动态风险扫描。
- `mcp_risk_scan`：元数据检查、只读源码快速/完整审计、四阶段动态扫描及 Crescendo/TAP 多轮红队。
  发起任务时选择模型网关中已启用的评估模型，并可分别选择分析模型和攻击模型。

AI-Infra-Guard Agent Scan 和 MCP Scan 源码随镜像交付，不在容器启动时下载。Worker 使用非 root、只读根文件
系统、`/tmp` tmpfs 和资源上限运行；它不会引入上游 Web Server、账号体系或前端。

元数据模式保留平台规则检查器，并记录 `tool_calls_performed=0`。其他模式在独立任务进程内调用
Tencent Zhuque Lab / AI-Infra-Guard `v4.6.0` 的扫描入口。源码执行器只提供作用域内的文件读取、
列举和文本搜索，不执行源码或模型生成的代码。动态工具通过 Backend 的任务租约接口调用，
由 Backend 校验冻结地址、DNS、Schema、工具范围、策略能力、网络白名单、敏感工具审批和调用预算。
源码快照和模型请求复用平台的存储/网关机制，供应商和 MCP 服务凭据保留在 Backend。

红队复用上游 Crescendo/TAP 策略，并用真实工具调用替换其默认的模型模拟目标。
报告包含阶段结果、调用 ID、JSON 和 SARIF；模型意见作为待复核风险信号。原始工具请求和返回加密存储，
安全管理员读取时记入审计。取消或预算停止后终止任务进程并清理临时目录。
功能范围及操作说明见 [项目指南](../../docs/project-guide.md#69-mcp-server-和-tool-风险扫描)。

## 凭据边界

内置 Worker 从项目根目录 `.env` 读取 `AGENT_SECURITY_WORKER_TOKEN`；Backend 读取同一个值并在建表后
幂等注册 `builtin-security-worker`，无需先在管理台创建。Worker Token 只以 SHA-256 保存，列表接口
不返回明文。手工创建的外部 Worker 仍使用管理台只展示一次的 `token_once`。启动时
Worker 生成临时 X25519 密钥对并登记公钥；Backend 只在任务领取时解密目标凭据，并生成与
Worker、任务、凭据和租约到期时间绑定的 AES-GCM 密封信封。目标凭据不会以数据库密文或长期
明文出现在任务载荷、日志或 API 响应中。

开放接口任务固定受理时的目标和凭据版本；登记更新为新版本建立独立目标及凭据，已受理任务继续使用原版本。领取时检查固定凭据仍有效，停用或吊销后阻止执行。Backend 与 Worker 需同步升级，配置和调用流程见[智能体开放接口](../../docs/external-agent-integration.md#智能体开放接口--agent-open-api)。

Agent 和 LLM 扫描在创建时选择网关评估模型。Worker 使用任务租约调用控制面的任务专属评估接口，供应商密钥保留在 Backend；模型调用复用网关隐私策略和审计。

## 构建与运行

```bash
./build.sh --all
cp .env.example .env
docker compose up -d
```

默认 Compose 会同时启动 Worker 和 `aig-scan-service`。示例包含可用的本地开发凭据；
生产需设置独立随机 Token 并启用安全启动校验。在模型网关启用模型及供应商后，即可在扫描表单选择评估模型。源码运行时，控制面和 AIG 地址应改为宿主机可访问的地址。相关环境变量用于 Worker
身份和运行凭据。直接从源码运行 Worker 时也会读取项目根 `.env`，已有进程环境变量优先；容器内
仍由 Compose 注入。修改内置 Token 并重建 Backend 与 Worker 会保留 Worker ID、使旧 Token 失效并
清空公钥/心跳以便重新登记；已吊销身份只有在配置新 Token 时才会恢复。

源码启动时 `worker.py` 会先识别项目根目录并加入 Python 模块搜索路径，再读取根 `.env`，因此不需要
额外设置 `PYTHONPATH`：

```bash
.venv-security-worker/bin/python services/agent-security-worker/worker.py
```

Agent评测适配器按所选检查项采集开始、完成和异常事件，将不可变计数快照放入租约心跳的 `scan_progress`。采集入口复用Agent Scan的检测阶段调用，准备与复核阶段不增加用例计数。心跳成功后才记录已上报快照，传输失败由后续心跳重发；长调用期间由后台续租线程发送最新计数。只上报计数，不包含对话或模型响应。Backend领取新一轮重试时清理上一轮进度，终态查询按保存的用例统计。此功能需要一起更新Backend、Worker和Web；配置与数据库结构不变。

**English:** The Agent adapter tracks selected detection checks as they start, finish or fail, and sends immutable count snapshots in lease heartbeat `scan_progress`. Reconnaissance and review do not add cases. A snapshot is marked reported only after a successful heartbeat; subsequent heartbeats retry failed sends, and the keepalive thread publishes during long calls. Only counts are sent, without dialogue or model responses. The Backend clears prior-attempt progress on a new claim and uses persisted cases for terminal counts. Update Backend, Worker and Web together; configuration and database structure are unchanged.

镜像和 Compose 都配置了健康检查。Worker 只有在成功完成控制面领取/心跳后才刷新 `/tmp` 中的
健康标记；长任务期间，成功续租也会刷新该标记，避免正常扫描被误判为失联。控制面持续不可达时
标记不会刷新，健康检查会失败。默认容忍时间为 `max(30 秒, 4 × 轮询间隔)`，这只能证明 Worker
进程与控制面的租约通道正常，不能证明外部扫描目标已经验收。

Compose 默认以 UID/GID `10001:10001`、只读根文件系统、`/tmp` tmpfs、`init`、全部 capability
删除和 `no-new-privileges` 运行，并提供以下可调资源边界：

| 变量 | 默认值 | 作用 |
|---|---:|---|
| `AGENT_SECURITY_WORKER_TMPFS_SIZE` | `64m` | 临时文件空间 |
| `AGENT_SECURITY_WORKER_PIDS_LIMIT` | `128` | 进程数上限 |
| `AGENT_SECURITY_WORKER_MEMORY_LIMIT` | `512m` | 内存上限 |
| `AGENT_SECURITY_WORKER_CPU_LIMIT` | `1.0` | CPU 配额 |
| `AGENT_SECURITY_WORKER_STOP_GRACE_PERIOD` | `30s` | 优雅停止等待时间 |
| `AGENT_SECURITY_WORKER_LOG_MAX_SIZE` | `10m` | 单个容器日志文件上限 |
| `AGENT_SECURITY_WORKER_LOG_MAX_FILES` | `3` | 保留的容器日志文件数 |

这些值是安全起点，不是容量结论。提高 Worker 并发或扫描规模前，应在目标环境记录 CPU、内存、
任务时长和失败率，再同步调整资源上限。

双架构镜像或离线归档加载后，可执行相同的发布门禁：

```bash
./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:<tag> amd64
./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:<tag> arm64
```

门禁核对镜像架构、固定 UID/GID 和内置健康命令，然后以 `--pull never`、`--network none`、只读
根文件系统和默认资源上限运行健康探测，同时检查 LICENSE、NOTICE 和 SBOM。构建机需要具备目标
架构的原生运行能力或已经正确配置的容器模拟器；脚本成功不等于 Backend、目标凭据和真实扫描已验收。

可选费用率使用每百万 Token 的微单位：

- `AGENT_SECURITY_EVALUATOR_INPUT_COST_MICRO_PER_MILLION`
- `AGENT_SECURITY_EVALUATOR_OUTPUT_COST_MICRO_PER_MILLION`

费用率未配置时仍记录估算 Token，费用为 0；模型网关的服务端计量是正式账务和审计依据。

扫描结论采用 fail-closed：评估模型在内部重试后仍返回错误，或目标扫描期间没有任何一次成功
对话时，Worker 会以稳定错误码回传失败并按策略重试，不会把不完整扫描报告为“安全”。锁定版
上游会把未分类风险默认标为 `ASI10`，Adapter 只有在 Finding 类型中也包含明确 ASI 编码时才
执行稳定风险映射；否则进入 `unmapped`。

Agent Scan 的测试用例按所选 detection skill 生成。Vendored 执行链为每个 Worker 保存 skill 名称、稳定阶段、
实际 `dialogue` 调用数、候选 Finding 数和脱敏错误；异常 Worker 不再从汇总中静默消失。规则正常完成且至少调用
一次目标、最终没有关联的确认 Finding 时才是 `passed`，其含义仅为“本次执行未观察到风险”。零调用、缺少执行
记录或旧版报告统一为 `unverified`；策略/预算阻断为 `blocked`，Worker 异常为 `error`，存在确认 Finding 为
`failed`。完整 transcript 留在加密原始产物中，不作为测试用例或通过数。

候选漏洞进入 Reviewer 前由程序附加 opaque `source_ref`。Reviewer 必须原样保留该引用；Worker 仅使用自己持有的
`source_ref → skill` 映射产生 `source_skill`，不信任模型自由生成的同名字段，也不根据标题或自然语言关键词猜测。
无法解析来源的 Finding 关联独立 `aig-rule:unmapped` 用例并标记证据不足。历史数据库记录不会自动重算；没有
`detection_executions` 的旧报告只产生 `unverified` 汇总用例。

任务级预算在多个 attempt 间累计。Worker 每次领取任务后以控制面返回的历史轮次、Token、费用、
最大并发和响应字节为基线；Agent、MCP 元数据和控制面验证三类任务都不会从 0 重新上报。后台续租
遇到单次网络、超时或 JSON 解析错误时继续重试，只记录异常类型、HTTP 状态、稳定错误码和连续失败
次数；明确收到租约无效或过期后阻止该 attempt 的后续请求，已发出的请求由客户端超时结束；日志不记录
Token、目标凭据或原始对话。

Agent 动态扫描会在任务创建、领取以及每次目标调用前重新解析并核对固定地址集合，但 HTTPX 和
WebSocket 在实际建连时仍由传输库再次解析，因此尚不是 socket 级 IP 固定。生产环境必须同时用
Worker 出站网络策略限制可达目标。
Dify 资产采集的 Console/Knowledge API 客户端直接连接已验证的 IP，重定向逐跳校验；HTTPS 保持
原域名的 Host、SNI 和证书校验。该客户端不使用环境代理。

## 上游修改和交付物

- 上游来源和哈希：`deploy/agent-security/upstreams.lock.json`
- 整树校验：`verify_vendor_tree.py`；测试和 Docker 构建使用同一确定性算法核对两个 vendored tree
- 修改说明：`UPSTREAM_MODIFICATIONS.md`
- 上游许可：镜像 `/app/licenses/LICENSE` 和 `/app/licenses/NOTICE`
- SBOM：镜像 `/app/licenses/sbom.spdx.json`

Agent 本地 Mock 位于 `demo/agent-security-mock-target/`；MCP 恶意描述、危险参数、Schema 漂移和
副作用零调用 Mock 位于 `tests/test_ai_infra_guard_mcp_adapter.py`。Mock 不伪造扫描 Finding。

MCP 源码、四阶段动态扫描和红队执行链的回归使用真实上游代码及确定性的模型/工具响应：

```bash
uv run --with mcp==2.0.0 --with loguru==0.7.3 python -m pytest tests/test_mcp_scan_execution.py -q
```

缺少这两个 Worker 依赖时，上游执行链测试会跳过；该回归不替代真实模型与业务 MCP 目标的集成验收。
