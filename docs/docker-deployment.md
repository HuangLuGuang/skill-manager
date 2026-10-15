# Docker 部署

License 状态默认保存在后端持久化 data 卷的 `license/state.db`，可信公钥由镜像内
`deploy/license/public-keys/` 提供。后端重建/升级保留该卷；自定义路径的多进程必须共享状态文件。
安装后的申请、签发和导入流程见 [离线 License](license.md)。

现场安装与升级使用交付包：首次在解压后的 `agent-manager` 目录准备生产 `.env`，执行
`./start.sh`；自定义 HTTP 端口使用 `./start.sh --port 8088`。后续在原安装目录执行
`./upgrade.sh /path/to/agent-manager_<版本>_<架构>.tar.gz`。脚本加载包内镜像并检查服务，
升级保留 `.env`、`HTTP_PORT` 和数据卷；业务数据需另行备份。
完整步骤见[离线部署现场实施指南](offline-deployment.md)，管理台中英文帮助页对应
“Docker 部署”和“Docker 运维”。

下文涉及 `build.sh` 的命令用于源码构建环境，在项目根目录执行。

## 生产环境资源推荐

单节点 Docker Compose 生产部署建议以以下规格作为初始容量基线：

| 资源项 | 推荐配置 | 容量规划说明 |
| --- | --- | --- |
| CPU | `16 vCPU` | 用于承载 Backend、静态与深度扫描、Sandbox 调度及并发管理请求。提高扫描并发或集中提交大量 Skill 时，应同步增加 CPU 配额。 |
| 内存 | `32 GiB` | 为 Backend Worker、扫描分析器、Sandbox 服务及容器页缓存预留运行空间。高并发 Sandbox 或 LLM 前处理场景应根据峰值内存继续扩容。 |
| 磁盘 | `500 GiB` 可用容量，优先 SSD/NVMe | 用于保存容器镜像、Skill 上传包、版本内容、扫描报告、审计数据、客户端发布文件和运维日志。Skill 数量多、单包较大或版本留存周期较长时，需要配置更大的数据盘。 |

以上为生产环境推荐规格，不是最低运行门槛。`2026-08-13` 已在一台共享的 `8 vCPU / 31 GiB`
测试机上完成单节点基准，用于识别 SQLite 写并发和扫描队列的容量拐点；生产仍建议保留
上述更高资源余量。完整测试环境、方法、并发结果和适用边界见
[性能基准与容量边界](performance-benchmark.md)。正式上线前应根据
Skill 总量、日增版本数、平均包体积、报告与审计保留周期、扫描并发以及备份策略进行
容量评估。建议持续监控 CPU、内存、磁盘 IOPS 和文件系统使用率，并至少保留 `30%`
磁盘余量，避免镜像升级、扫描临时文件或数据增长耗尽文件系统。生产环境应将 Docker
数据目录和持久化卷纳入监控与备份范围。

## 本地开箱启动

Skill 导入准备的并发由 `.env` 中 `AGENT_MANAGER_IMPORT_WORKERS` 控制，默认 `2`，独立于后台检测
`AGENT_MANAGER_SCAN_WORKERS=2` 和分析器 `AGENT_MANAGER_ANALYZER_WORKERS=8`。导入额度耗尽时请求等待，
普通同步 API 仍可使用自己的线程额度。更新代码/镜像和 Compose 后重建 Backend 生效；多 API 进程各有自己的额度，
总并发随进程数增加。这是工作调度限制，CPU、内存和磁盘仍需按混合负载监测。

**English:** `AGENT_MANAGER_IMPORT_WORKERS=2` independently bounds blocking import preparation per API process.
Recreate Backend after updating the image/configuration. Queued imports preserve ordinary API thread capacity;
CPU, memory and disk remain shared. See [performance validation](performance-benchmark.md#skill-导入与-api-隔离回归2026-10-14).

```bash
./build.sh --all
cp .env.example .env
docker compose up -d
docker compose ps
```

镜像已构建或加载后，复制 `.env.example` 即可直接启动全部基础服务，包括扫描 Worker 和
AI-Infra-Guard 内部服务，无需额外 profile。Apple Silicon 构建时使用
`./build.sh --all --platform linux/arm64`。示例和 Compose 缺省值使用公开的本地开发占位密钥，
并关闭生产安全启动校验。如果数据库中还没有管理员账号，且 `.env` 中的
`INITIAL_ADMIN_PASSWORD` 留空，首次启动会生成随机密码并保存在持久化数据卷中。
在项目根目录执行以下命令读取：

```bash
docker compose exec backend cat /app/runtime/data/initial-admin-password
```

访问：

```text
http://localhost
```

## 生产部署

生产环境必须创建 `.env`，为 `SECRET_KEY`、`AGENT_MANAGER_SANDBOX_API_KEY`、
`AGENT_SECURITY_WORKER_TOKEN` 和 `AIG_SCAN_SERVICE_TOKEN` 分别设置独立随机凭据，
并设置 `ENFORCE_SECURE_STARTUP=true`。`AIG_SERVICE_TOKEN` 默认引用 `AIG_SCAN_SERVICE_TOKEN`。
首次创建管理员账号前，必须在 `.env` 中设置至少 12 个字符的
`INITIAL_ADMIN_PASSWORD`；生产安全模式不会自动生成随机初始密码：

```bash
cp .env.example .env
# 编辑 .env，设置独立随机凭据、ENFORCE_SECURE_STARTUP=true 和 INITIAL_ADMIN_PASSWORD
./build.sh --all
docker compose run --rm --no-deps backend agent-manager signing-key init
docker compose up -d
docker compose ps
```

生产模式不会接受本地占位密钥，也不会恢复公开固定管理员密码。Skill Ed25519 签名私钥必须在启动
服务前预置：源码部署执行上述初始化命令，交付包的 `start.sh` 和 `upgrade.sh` 自动初始化
缺失的 Skill 密钥并沿用已有密钥；生产副本不会在启动或公钥查询时各自生成该身份。多副本
部署必须挂载同一份只读私钥或由统一密钥管理系统下发。

### AIDR 策略签名密钥

Docker Backend 入口在启动 API 前初始化并校验独立的 P-256 策略签名密钥，供原生 Hook
和系统防护策略使用。Compose 和镜像的默认配置为：

```dotenv
AIDR_POLICY_SIGNING_KEY_FILE=/app/runtime/data/signing/aidr-policy-p256.pem
```

该文件位于 `backend_data` 持久化卷。首次部署仅在文件缺失时生成无密码的 PKCS8 PEM 私钥，
权限为 `0600`，所有者为容器内服务用户；并发初始化不会覆盖先生成的完整密钥。
`docker compose up -d`、交付包 `start.sh` / `upgrade.sh` 和 CI 部署均沿用同一入口，
容器重建及旧 `.env` 未增加此配置时仍使用上述默认路径。CI 在更新服务前预检密钥，
CI 和离线脚本在启动后再次检查实际运行容器中的密钥。

已有文件的类型、所有者、权限、PEM 格式或曲线不符合要求时，启动失败并提示
`aidr.enforcement_signer_unavailable`，不会覆盖或自动更换密钥。只读挂载的已有有效密钥可正常使用。
自定义路径必须挂载到持久化存储，多副本应预置同一份密钥。修改服务 UID 时同步调整文件所有者。

仅校验当前容器中的密钥（不输出私钥、不创建文件）：

```bash
docker compose exec -T backend python -m backend.aidr_signing --check
```

如需在启动前单独初始化或检查已有密钥：

```bash
docker compose run --rm --no-deps --entrypoint python backend -m backend.aidr_signing
```

将 `backend_data` 中的该密钥纳入受控备份，恢复时保留原密钥与权限。客户端会固定策略验签公钥，
更换密钥需要同步更新客户端信任；不要通过删除密钥排查故障。私钥只保留在部署环境，
不提交到 Git、不写入镜像或离线包；License 签发私钥仍由独立签发系统保管。

### 管理员初始密码与升级

默认管理员用户名是 `admin`，可在首次创建账号前通过 `INITIAL_ADMIN_USERNAME` 修改。
`INITIAL_ADMIN_PASSWORD` 是首次创建该用户名对应账号时使用的初始密码，不是每次启动时
重新设置密码的配置项。首次部署时，在 `.env` 中填写自己的密码，例如：

```dotenv
ENFORCE_SECURE_STARTUP=true
INITIAL_ADMIN_PASSWORD=replace-with-your-strong-password
```

生产安全模式下，密码至少需要 12 个字符；留空会使首次创建管理员账号的 Backend 启动
失败。仅在未启用安全启动校验、数据库中尚无该账号且变量留空时，系统才会生成随机密码。
随机密码文件位于 Backend 持久化数据卷；可用上文的 `docker compose exec backend cat ...`
命令查看当时生成的初始值。后续改密不会更新该文件；文件存在或不存在都不能单独证明
当前登录密码。

升级时应保留原数据库和数据卷。只要数据库中已存在该用户名的账号，启动时就不会读取
`INITIAL_ADMIN_PASSWORD` 来修改密码：原密码继续有效，后来在 `.env` 中填写新值并重建
Backend 容器也不会重置密码。若换了数据库、删除了数据卷，或修改了
`INITIAL_ADMIN_USERNAME` 使系统找不到该账号，启动时会按首次创建账号处理。登录后修改
自己的密码，请使用右上角账号菜单的“修改密码”，输入当前密码和新密码；有账号管理权限的
管理员也可以在“系统管理 → 账号管理”中重置其他账号的密码。

升级前执行以下只读检查，确认不存在已批准或已部署但未声明工具权限的 Skill：

```bash
uv run agent-manager registry audit-tool-permissions
```

命令发现条目时退出码为 `2`。这些条目升级后会被 fail-closed 授权阻断，应先补充
`allowed_tools` 并重新审批，不能通过恢复“空声明全放行”绕过。

Compose 入口 Nginx 会把管理 API `/api/` 和 MCP Streamable HTTP 数据面 `/mcp/` 转发到 Backend；MCP Client 应使用 `http(s)://部署域名/mcp/{gateway_slug}`，不需要直接暴露 Backend 端口。旧版 `/sse/` 当前未实现，也不配置转发。

入口 Nginx 会用直连客户端地址覆盖 `X-Forwarded-For`，Backend 默认仅信任回环地址和
Compose 动态分配的 `172.16.0.0/12` 代理网段，因此登录日志、操作日志和访问控制读取到的
是客户端地址，而不是 Nginx 容器地址。若在入口 Nginx 前增加负载均衡器、Ingress 或 CDN，
需要先配置 Nginx Real IP 信任链，并通过 `FORWARDED_ALLOW_IPS` 收窄 Backend 信任的直连
代理网段；不要直接信任任意来源提交的转发头。

### 智能体安全能力

安全能力基线和轨迹能力基线安装后默认启用，不需要在 `.env` 配置功能开关。登录后管理台
直接显示“智能体安全”菜单。以下变量仅作为紧急关停手段保留，不进入常规 Compose 配置：

```ini
AGENT_SECURITY_SCANNING_ENABLED=false
RUNTIME_TRACE_ENABLED=false
```

只有通过 Compose override 或容器编排系统显式注入上述值时，对应菜单才隐藏，API 返回稳定
的 feature-disabled 错误。普通安装和升级不要把它们写入 `.env`。从早期 P0 版本升级时，
如果旧 `.env` 已经保存了值为 `false` 的同名变量，必须删除这两行并重建 Backend 容器，
否则环境变量仍会覆盖新的默认开启值。

当前页面和 API 已提供版本基线、四类扫描目标、策略、Agent/MCP/LLM/AI 基础设施扫描任务、Worker 协议和
统一 Finding 模型，并执行锁定的 AI-Infra-Guard Agent Scan、模型红队、基础设施扫描及 MCP 源码/动态/红队执行器。MCP 元数据模式保留平台规则适配器。P4 已提供统一
轨迹 API、Agent SDK 和模型/MCP/治理发布；P5 已提供对话/轨迹双视图、证据检索和受控导出，
但不宣称等同于完整 DeepSeek Harness 前端。
Backend 从镜像内的
`/app/deploy/agent-security/upstreams.lock.json` 读取版本清单，请勿把该路径改为网络地址。
详细边界见[智能体安全平台 P0 技术基线](agent-security-p0-baseline.md)。

### 独立扫描 Worker 与 AI-Infra-Guard 内部服务

Backend 镜像同时包含锁定版本的 `data/eval` 数据集及 LICENSE、NOTICE，供登录用户分页查看评测集 Prompt 原文。

Worker 同时运行 `control_plane_validation`、`agent_risk_scan`、`dify_asset_inventory`、
`mcp_risk_scan`、`llm_redteam_scan` 和 `ai_infrastructure_vulnerability_scan`。模型红队和基础设施任务由固定版本的 `aig-scan-service` 在私有
`aig-control` 网络执行，服务端口不映射到宿主机。内置 Worker 无需先在
管理台创建身份：在项目根目录 `.env` 只配置一次 `AGENT_SECURITY_WORKER_TOKEN`，Backend 建表后会以
固定名称 `builtin-security-worker` 幂等注册，Worker 容器读取同一个值。令牌必须以 `amsw_` 开头，
前缀后至少包含 32 个 URL-safe 字符。示例已提供本地开发占位值；生产用
`printf 'amsw_%s\n' "$(openssl rand -hex 32)"` 生成独立随机值。生产安全启动会拒绝公开的开发凭据。

在模型网关配置并启用评估模型及其供应商，发起 Agent 风险扫描或 LLM 红队扫描时选择该模型。
Worker 通过任务租约调用 Backend 评估接口。另生成独立的 `AIG_SCAN_SERVICE_TOKEN`，至少包含 32 个
随机 URL-safe 字符，由 Backend、Worker 与内部服务共同使用。然后执行：

```bash
./build.sh --all
docker compose up -d
docker compose ps agent-security-worker aig-scan-service
```

`.env.example` 列出 `AIG_SERVICE_URL`、`AIG_SERVICE_TOKEN` 和 Worker 控制面地址。
Compose 默认使用容器 DNS：`http://aig-scan-service:8093` 和 `http://backend:8000/api/v1/agent-security`。
本地源码运行 Backend/Worker 时，将它们改为可访问的宿主机地址，并为内部服务发布仅本机可访问的端口。
模型评估经 Worker 控制面地址下的任务专属接口路由到所选网关模型。

Dify 资产清单不增加 `.env` 密钥。管理员在“扫描管理 → 扫描目标”创建 Dify 目标，并按用途把 Admin API
Key 保存为加密的 `dify_console_api` 目标凭据；需要授权知识库检查时另存 `dify_knowledge_api`。部署网络必须
允许 Worker 访问显式 Console Base URL，私网地址还必须同时满足目标 CIDR 和策略出站 CIDR。不要把 Admin
API Key 写入 Compose、环境变量、目标配置或验收日志。

Worker 镜像内置健康检查，Compose 也会执行同一检查。成功领取任务、空闲心跳以及长任务期间的成功
续租都会刷新健康标记；控制面持续不可达时不会刷新。`docker compose ps agent-security-worker`
显示 `healthy` 只证明 Worker、内部引擎和控制面租约通道正常，不等于任何外部目标已完成风险扫描。

Compose 默认使用非 root、只读根文件系统、`/tmp` tmpfs、`init`、删除全部 capability 和
`no-new-privileges`，并限制为 128 个进程、512 MiB 内存、1 个 CPU。可按实测通过
`AGENT_SECURITY_WORKER_TMPFS_SIZE`、`AGENT_SECURITY_WORKER_PIDS_LIMIT`、
`AGENT_SECURITY_WORKER_MEMORY_LIMIT`、`AGENT_SECURITY_WORKER_CPU_LIMIT`、
`AGENT_SECURITY_WORKER_STOP_GRACE_PERIOD`、`AGENT_SECURITY_WORKER_LOG_MAX_SIZE` 和
`AGENT_SECURITY_WORKER_LOG_MAX_FILES` 调整；默认值是安全起点，不是银行生产容量或 SLA。

`AGENT_SECURITY_WORKER_TOKEN` 是运行凭据，不能写入镜像或提交到 Git。根目录 `.env` 适合本地和受控离线部署；生产环境可由 Secret 管理能力注入。扫描目标凭据由管理台单独配置。
吊销 Worker 后旧 Token 立即失效。
目标长期凭据保存在 Backend；领取任务时才通过 Worker 临时公钥生成租约绑定的密封信封。

#### Worker 生命周期运维

页面默认启用与 Worker 是否启动是两件事：管理页面和 API 无需 `.env` 开关；只有实际执行异步
扫描时才需要 Worker 和运行凭据。环境管理的内置身份由 Backend 自动维护；外部或扩容 Worker
仍可使用下列接口手工创建，示例中的管理
JWT 和 `token_once` 都必须通过现场 Secret 管理流程传递，不能进入命令历史、工单正文或普通日志：

```http
POST /api/v1/agent-security/workers
Authorization: Bearer <admin-jwt>
Content-Type: application/json

{"name":"bank-scan-worker-01","capabilities":["agent_risk_scan","mcp_risk_scan"],"max_concurrency":1}
```

只有手工创建响应包含只显示一次的 `token_once`；自动注册身份不会通过 API 返回明文。
`GET /api/v1/agent-security/workers` 可检查 `status`、
`last_heartbeat_at`、公钥指纹和登记时间；`POST /api/v1/agent-security/workers/{worker_id}/revoke`
用于吊销。手工身份仍没有原地轮换 Token 的接口，需创建新身份后迁移。内置身份则通过修改根目录
`.env` 中的 Token 并重建 Backend 与 Worker 完成原地轮换：Worker ID 保持不变，旧 Token 立即失效，
公钥和心跳状态会清空并由 Worker 重新登记。相同 Token 的已吊销身份不会自动恢复；必须换成新 Token
才会重新激活。若同名身份已由管理员手工创建，Backend 会拒绝启动且不会覆盖该记录。

启动后按以下顺序验收，证据中只记录 Worker ID、Token 前缀、时间和状态，不记录明文 Token：

1. `docker compose ps agent-security-worker` 显示 `healthy`。
2. 管理接口中 `last_heartbeat_at` 持续更新，且公钥指纹非空。
3. 分别提交一个授权的 Agent Mock、Dify 资产清单、MCP 元数据和源码、受控 MCP 动态/红队、受控 LLM 红队和授权网络端点扫描，确认任务从
   `pending` 进入 `running`，最终形成对应 Case、Finding/零 Finding或证据不足说明和原始产物摘要。
   Dify 项还应核对 `dify-asset-inventory@1` 加密产物、字段来源、Workspace ID 脱敏和五类覆盖状态；
   Console API 成功不代表 MCP、知识库和运行轨迹均已验证。
4. 核对 `docker compose logs --since 10m agent-security-worker`；日志不得出现 Worker Token、模型
   API Key、目标凭据或原始 Prompt/Response。

中断恢复必须使用可重复的非生产验收任务。先记录任务 ID 和当前 `attempt`，停止 Worker，
等待该任务策略的 `lease_seconds` 到期，再由管理员调用 `POST /api/v1/agent-security/workers/recover`，
或启动 Worker 让下一次领取自动执行同一恢复逻辑。若尚有重试次数，预期旧租约被清除、任务回到
`pending` 并在退避后由 Worker 重新领取；重试耗尽则应为 `failed`，不能把不完整结果标为安全。

```bash
docker compose stop agent-security-worker
# 等待该任务租约到期后，由管理员执行 recover API
docker compose start agent-security-worker
docker compose ps agent-security-worker
```

升级 Worker 前先加载目标架构镜像并运行离线镜像门禁，再只重建 Worker，不联动重启 Backend。
以下命令必须在相同的 Secret 注入上下文中执行；`OLD_TAG` 和 `NEW_TAG` 使用已经校验的明确版本：

```bash
./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:<new-tag> <amd64-or-arm64>
TAG=<new-tag> docker compose up -d --no-deps agent-security-worker
docker compose ps agent-security-worker
```

升级验收需要记录容器镜像 ID、Worker 心跳、公钥重新登记、升级前后各一项扫描结果。若健康检查或
任务回归失败，使用已保留的旧镜像明确回滚：

```bash
TAG=<old-tag> docker compose up -d --no-deps agent-security-worker
docker compose ps agent-security-worker
```

不要删除运行中的任务或数据库记录来制造“恢复成功”。升级期间停止领取的新任务会保留在队列；
已领取任务由租约到期和重试策略收敛。完成切换后再吊销不再使用的旧 Worker 身份。

费用预算需要计费时，可设置
`AGENT_SECURITY_EVALUATOR_INPUT_COST_MICRO_PER_MILLION` 和
`AGENT_SECURITY_EVALUATOR_OUTPUT_COST_MICRO_PER_MILLION`。未设置时费用记为 0，Token 仍按
Worker 估算上报；模型网关服务端计量才是正式审计依据。

`dev` 分支和正式版本 tag 的 `deploy-35` 流水线会启动默认 Compose 服务，并等待
管理入口、`agent-security-worker` 和 `aig-scan-service` 同时健康后才报告部署成功。缺少运行
Token 或任一新增服务无法通过健康检查时，部署会失败并收集对应容器日志；日志中仍不得输出凭据。

通用 HTTP 目标至少配置带 `{{prompt}}` 的请求体和响应文本路径。例如：

```json
{
  "target_type": "http",
  "endpoint_url": "https://agent.example.com/chat",
  "config": {
    "body": {"message": "{{prompt}}"},
    "transform_response": "reply",
    "session_request_path": "conversation_id",
    "session_response_path": "conversation_id"
  }
}
```

内网目标仍需目标与策略双重 CIDR 白名单。TLS 校验不可关闭。外部 SaaS 的字段以锁定版本 Provider
清单和目标创建接口校验为准；没有账号、授权目标和评估模型时，镜像健康不等于真实扫描已验收。

## 可选 MCP 业务案例

源码和离线包包含一个使用虚构客户数据的 MCP 客户操作案例，用于演练 Tool 发现、虚拟
网关发布、接入凭证、高风险操作审批和调用审计。该服务位于 Compose 的 `examples`
profile，执行常规 `docker compose up -d` 时不会启动，也不会向宿主机发布端口。

首次使用包含该案例的源码版本时，需要重新构建 Backend 镜像，再按需启动：

```bash
./build.sh --backend
docker compose --profile examples up -d mcp-demo backend nginx
docker compose ps mcp-demo
```

案例完整配置、演练步骤和恢复方式见
[`demo/mcp-customer-operations/README.md`](../demo/mcp-customer-operations/README.md)。
案例为了在隔离的 Compose 网络中复现 HTTP MCP 调用，需要显式配置 HTTP 和准确的私网
CIDR 白名单；这些配置不得照搬到生产。生产 MCP Server 应使用 HTTPS、安全注入的上游
凭证和限制到明确目标的出站白名单。

Compose 入口 Nginx 和前端静态站点均关闭了 `server_tokens`，默认错误页和 `Server` 响应头不会暴露具体 Nginx 版本。部署在外部负载均衡、Ingress 或 CDN 后面时，还需要在对应入口单独关闭版本信息。

Backend 启动时会检查旧版 Skill 数据。首次升级到版本化模型时，会把同名 Skill 合并为一个名称族、把不同内容转换为递增版本，并删除同名同内容的旧重复记录及其待审/报告/统计/扫描运行关联数据。迁移完成后会写入 `registry_migrations.skill_families_v1` 标记，后续 `docker compose up` 或容器重启不会重复执行，也不会触发重新检测。Skill 内容目录和审计日志不会被自动删除。

模型网关的 SQLite 升级迁移在 Backend 启动时执行。历史库若在 `model_providers` 表中遗留了不属于供应商配置的 `enable_compression` 必填列，Backend 会保留原有供应商记录并重建该表以移除该列；该列属于运行凭证而非上游供应商。升级前仍应备份 `backend_sqlite` 数据卷；启动后用管理台创建一个供应商，并确认 Backend 健康检查正常，作为升级验收的一部分。

P1 安全配置默认使用 SQLite，不新增数据库服务。`request_leases` 表协调共享同一 SQLite 文件的多 Worker 并发额度；它不支持多个主机各自使用独立 SQLite 文件时共享额度。MCP 上游默认只允许 HTTPS，可用 `MCP_OUTBOUND_ALLOWLIST` 配置允许的域名、通配域名或 CIDR。审计签名密钥通过 `AUDIT_SIGNING_PRIVATE_KEY_PATH` 持久化，`SECURITY_AUDIT_EXPORT_PATH` 是可选的追加式 JSONL 导出位置。

## 构建脚本

Backend 镜像通过 `uv pip install --system -e ".[scanner,compression]" -r backend/pyproject.toml python-frontmatter` 安装核心包和管理后端运行依赖。新增后端依赖需维护 `backend/pyproject.toml`；镜像构建直接读取该文件。构建阶段会实际解析一条复合 Shell 命令，确认 `tree-sitter` 与 Bash 语法库可用；CI 继续在切换运行容器前验证应用启动和 `/health`。

The backend image installs the core package and backend runtime dependencies directly from `backend/pyproject.toml`. Update that manifest when adding backend dependencies. The image build parses a compound Shell command to verify the tree-sitter runtime and Bash grammar; CI then checks application startup and `/health` before replacing running containers.

Backend 镜像中的 SkillSpector 固定为 **2.2.3**，源码提交为
`a5092dd9b9521ff57a9b53612bb129ce78019002`。升级时更新 `backend/Dockerfile`
中的固定提交，并同步本文档；
重新构建和部署 Backend 镜像后生效。

```bash
# 查看帮助
./build.sh --help

# 构建全部镜像，默认 tag 是 latest
./build.sh --all

# 指定 tag
./build.sh --tag v1.0.0 --all

# 指定平台
./build.sh --platform linux/amd64 --tag v1.0.0 --all
./build.sh --platform linux/arm64 --tag v1.0.0 --all
```

会生成这些镜像：

- `agent-manager-backend:<tag>`
- `agent-manager-frontend:<tag>`
- `agent-manager-sandbox:<tag>`
- `agent-manager-sandbox-runtime:<tag>`
- `agent-manager-security-worker:<tag>`
- `agent-manager-aig-scan-service:<tag>`

前端镜像以仓库根目录为构建上下文（`docker build -f web/Dockerfile .`）。构建阶段在
`/app/web` 编译平台，并将两端共用的事件展示模块 `client/desktop/src/event-records.js`
复制到 `/app/client/desktop/src/`，保留源码相对目录关系。最终 Nginx 镜像只接收
`/app/web/dist` 静态产物。修改跨目录共享模块时，应验证此 Docker 构建路径。
构建阶段保留 `npm audit --audit-level=low` 检查；依赖更新同步锁文件，并重新验证安全检查与镜像构建。

**English:** Build the frontend image from the repository root with `docker build -f web/Dockerfile .`.
The build stage compiles the web app in `/app/web` and copies the shared event presentation module to
`/app/client/desktop/src/event-records.js`, preserving its source-relative location. The final Nginx
image receives only the static assets from `/app/web/dist`. Validate this Docker build when changing
modules shared across directories. The build retains `npm audit --audit-level=low`; dependency updates
must include the lockfile and pass both the audit and image build again.

安全 Worker 和 AI-Infra-Guard 内部服务已加入 `--all` 和 `--save`，因此 x86/ARM 离线包会包含这两个镜像。联网 CI 在镜像中
写入锁定的 AI-Infra-Guard Agent Scan/MCP Scan 源码、约束依赖、LICENSE、NOTICE 和 SPDX SBOM；客户
现场启动时不得访问 GitHub 或 PyPI。构建会先用与测试相同的确定性整树算法校验 Agent Scan 和
MCP Scan vendored source；任一未登记文件变化都会使镜像构建失败。

正式离线发布流水线在生成每个架构的归档后，会从归档执行 `docker load`，再运行：

```bash
./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:<tag> amd64
./scripts/verify-aig-scan-service-image.sh agent-manager-aig-scan-service:<tag> amd64
./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:<tag> arm64
./scripts/verify-aig-scan-service-image.sh agent-manager-aig-scan-service:<tag> arm64
```

该门禁不拉取镜像且禁用容器网络，核对架构、非 root 用户、健康命令、许可证和 SBOM，并在只读
根文件系统及默认资源限制下实际启动。构建节点必须能原生运行目标架构，或提供经过验证的模拟器。
它验证的是安全 Worker 镜像和离线归档，不替代整个平台在客户服务器上的安装、数据迁移和业务回归。

## 打包发布

在有网络的机器上生成客户安装包：

```bash
# x86（client-releases 是 CI 下载并解压后的 agent-manager-client-update-feed）
./package-release.sh -v v1.0.0 -p linux/amd64 -i /path/to/docker-installer-28.5.2-x86-arm.tar.gz -c /path/to/client-releases

# ARM
./package-release.sh -v v1.0.0_arm -p linux/arm64 -i /path/to/docker-installer-28.5.2-x86-arm.tar.gz -c /path/to/client-releases
```

输出：

```text
agent-manager_v1.0.0_x86.tar.gz
agent-manager_v1.0.0_arm.tar.gz
```

每个安装包只包含所选服务器架构的镜像，按以下部署清单组包：

```text
docker-compose.yaml
.env.example
start.sh
upgrade.sh
deploy/offline.py
deploy/nginx/default.conf
release-provenance.json
docs/offline-deployment.md
docs/docker-deployment.md
docker_images/<x86 或 arm>/agent-manager-images-<tag>.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
scanner/releases/agent-manager-client-26.03.15.1-darwin-aarch64.dmg
scanner/releases/agent-manager-client-26.03.15.1-darwin-x86_64.dmg
scanner/releases/agent-manager-client-26.03.15.1-windows-x86_64.exe
scanner/releases/agent-manager-client-26.03.15.1-linux-x86_64.AppImage
```

仓库源码树、测试、构建脚本和开发工具不进入安装包；容器镜像保留应用运行所需的程序。
打包时将 Compose 的应用镜像引用写为实际发布版本；源码仓库内的 `latest` 开发默认值保持原样。
现场通过 `./start.sh` 自动加载镜像、初始化缺失的签名密钥、启动并检查服务；
默认 HTTP 端口为 80；`./start.sh --port 8088` 将端口写入 `.env` 的 `HTTP_PORT`，
以后启动和升级都会沿用，访问地址为 `http://<服务器IP>:8088`。
`./upgrade.sh /path/to/package.tar.gz` 自动解压、备份并更新部署文件、加载镜像、重建并检查服务。
脚本使用 Bash、Python 3 标准库和 Docker Compose，保留现场 `.env` 和数据卷。
启动和升级会检查 Docker 命令、服务连接与访问权限，优先选择可用的 `docker compose`，
否则尝试 `docker-compose`；需支持健康等待、JSON 配置输出及当前编排格式，旧版 Compose v1 需更新。
缺少程序、服务不可达、权限不足或版本不兼容时给出明确提示；处理步骤见现场实施指南的“部署前检查”。
升级备份仅覆盖部署文件，业务数据需另行备份；操作步骤见 [现场实施指南](offline-deployment.md)。
`--source-dir .` 可用当前工作区构建诊断包，正式 CI 发布使用干净的 Git clone；诊断包不能替代正式发布验证。

Docker Compose 已将宿主机 `scanner/releases` 只读挂载到后端。部署完成后，管理员可在“客户端管理 → 安装客户端”按系统和版本下载；新增版本只需把新的 release 文件复制到该目录，无需重建镜像。

## 自动部署与离线发布

内部 GitLab Runner 使用 `agent-manager-release` 标签，所有任务共用 `production-35` 资源锁：

| 推送内容 | 执行任务 | 输出 |
| --- | --- | --- |
| `dev` 分支 | `deploy-35` 构建 x86、更新 Compose、健康检查 | 35 部署，镜像版本 `dev-提交短哈希` |
| `1.0.6` 或 `v1.0.6` | `deploy-35` 成功后执行 `offline-package` | 仅 x86 包 |
| `1.0.6_arm` 或 `v1.0.6_arm` | `offline-package-arm` | 仅 ARM 包 |

从已验证的 `dev` 提交分别创建所需 tag，例如：

```bash
# x86 发布
git tag 1.0.6
git push origin 1.0.6

# 需要 ARM 时单独发布
git tag 1.0.6_arm
git push origin 1.0.6_arm
```

产物分别为 `/home/ubuntu/releases/agent-manager_1.0.6_x86.tar.gz` 和
`/home/ubuntu/releases/agent-manager_1.0.6_arm.tar.gz`。带 `v` 前缀时文件名也保留 `v`。
ARM 包内的镜像 tag、Compose 镜像引用和 provenance 版本均为完整 tag（例如 `1.0.6_arm`），
压缩包文件名只保留一次 `_arm`。ARM 作业使用独立应用镜像 tag，并在成功或失败退出时恢复
35 上共享的 `nginx:1.27-alpine` x86 镜像 tag。

每个包上传前验证 `release-provenance.json` 的版本、流水线 Commit、目标架构及干净的
`git_clone` 来源，并加载归档中的镜像执行 Worker 和 AIG Scan Service 镜像校验。
随后上传 S3、检查对象、生成具体文件的预签名下载链接；
`scripts/publish_release_notification.py` 通过 Range 请求读取文件内容，核对远端大小与本地包一致后发送通知。
企业微信最终通知使用 Markdown，包含版本、平台、文件名、文件大小、MD5 和独占一行的完整下载链接，方便复制。
签名有效期最长 7 天；若使用临时 AWS 凭据，
链接可能随凭据提前失效。下载验证或企业微信返回码异常都会使发布任务失败。

在 GitLab 项目的 `Settings → CI/CD → Variables` 中配置掩码变量 `WECHAT_WEBHOOK_URL`，
发布任务必须能够读取它。若变量设置为 Protected，需要同时保护所使用的数字版本 tag 和
带 `v` 前缀的版本 tag（包括 `_arm`）。Runner 的 AWS 凭据需要具备桶检查、对象上传及读取权限。
`client-vYY.MM.DD.N` 继续由 GitHub Actions 构建并同步桌面客户端。

内部发布环境的 Docker daemon 使用外网代理拉取基础镜像；GitLab CI 还通过 `BUILD_DOCKER_PROXY` 仅为 Buildx 进程设置 `HTTP_PROXY`/`HTTPS_PROXY`，确保 Docker Hub token 鉴权请求走代理。Backend 的 Debian 与 GitHub 下载分别通过 `BUILD_APT_PROXY`、`BUILD_GIT_PROXY` 使用代理，Python 包通过 `BUILD_PYPI_INDEX` 使用清华源；npm 保持直连。Backend 预热 tiktoken 词表的构建步骤也使用 `BUILD_GIT_PROXY` 作为 HTTPS 下载代理，仅在该步骤内生效；构建时代理不配置到运行容器。Docker 代理配置位于 `/etc/systemd/system/docker.service.d/http-proxy.conf`；修改后执行 `sudo systemctl daemon-reload && sudo systemctl restart docker`。

Backend、Sandbox（nsjail 编译阶段和运行阶段）、AIG Scan Service 镜像构建先下载 Debian 依赖，再从已下载的包执行安装。索引更新最多尝试 3 次，依赖下载最多尝试 5 次，下载失败后依次等待 5、10、15、20 秒，并复用本次构建中已下载成功的包；连续失败会终止构建。该重试用于应对依赖下载链路的临时 503 或连接超时，持续网络故障仍需排查代理及网络链路。

`build.sh` 中的基础镜像拉取（包括离线打包前的 nginx 拉取）最多尝试 5 次，失败后依次等待 5、10、15、20 秒。Sandbox 构建前也会显式拉取 `buildpack-deps:bookworm` 和 `debian:bookworm-slim`，纳入同一重试流程。重试保持指定的镜像和目标架构；全部失败会终止任务。该重试覆盖 Docker Hub 鉴权请求的临时 EOF 等拉取错误。

35 的 AIG Go 编译阶段通过 `BUILD_GOPROXY=https://goproxy.cn` 下载模块，保留 `go.sum` 和 Go 校验数据库校验。该变量由 `build.sh` 传入 Docker 构建参数，不修改 Runner 的全局代理。

## 离线部署

现场实施步骤单独维护在 [离线部署现场实施指南](offline-deployment.md)。

## 常用命令

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs -f
docker compose logs -f backend

# 停止
docker compose down

# 停止并删除数据卷
docker compose down -v
```

## 默认账号

默认用户名为 `admin`。初始密码的设置、随机密码查看以及升级后的行为见
[管理员初始密码与升级](#管理员初始密码与升级)。

Buildx 镜像构建最多尝试 3 次，失败后等待 5、10 秒，并复用构建缓存。这也覆盖 Dockerfile 构建器镜像和构建阶段内部解析基础镜像时的临时网络失败；持续失败仍会终止发布。
