# Docker 部署

以下命令都在当前项目根目录执行。

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

```bash
./build.sh --all
cp .env.example .env
docker compose up -d
docker compose ps
```

镜像已构建或加载后，复制 `.env.example` 即可直接启动全部基础服务，包括扫描 Worker 和
AI-Infra-Guard 内部服务，无需额外 profile。Apple Silicon 构建时使用
`./build.sh --all --platform linux/arm64`。示例和 Compose 缺省值使用公开的本地开发占位密钥，
并关闭生产安全启动校验；首次创建管理员时，随机密码保存在持久化数据卷中，可执行以下命令读取：

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
空的 `INITIAL_ADMIN_PASSWORD` 会生成随机初始密码，也可以设置自己的强密码：

```bash
cp .env.example .env
# 编辑 .env，设置独立随机凭据和 ENFORCE_SECURE_STARTUP=true
./build.sh --all
docker compose run --rm --no-deps backend agent-manager signing-key init
docker compose up -d
docker compose ps
```

生产模式不会接受本地占位密钥，也不会恢复公开固定管理员密码。签名私钥必须在启动
服务前通过上述显式命令预置；生产副本不会在启动或公钥查询时各自生成身份。多副本
部署必须挂载同一份只读私钥或由统一密钥管理系统下发。

升级前执行以下只读检查，确认不存在已批准或已部署但未声明工具权限的 Skill：

```bash
uv run agent-manager registry audit-tool-permissions
```

命令发现条目时退出码为 `2`。这些条目升级后会被 fail-closed 授权阻断，应先补充
`allowed_tools` 并重新审批，不能通过恢复“空声明全放行”绕过。

Compose 入口 Nginx 会把管理 API `/api/` 和 MCP Streamable HTTP 数据面 `/mcp/` 转发到 Backend；MCP Client 应使用 `http(s)://部署域名/mcp/{gateway_slug}`，不需要直接暴露 Backend 端口。旧版 `/sse/` 当前未实现，也不配置转发。

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
统一 Finding 模型，并执行锁定的 AI-Infra-Guard Agent Scan、模型红队、基础设施扫描及 MCP 元数据适配器。P4 已提供统一
轨迹 API、Agent SDK 和模型/MCP/治理发布；P5 已提供对话/轨迹双视图、证据检索和受控导出，
但不宣称等同于完整 DeepSeek Harness 前端。
Backend 从镜像内的
`/app/deploy/agent-security/upstreams.lock.json` 读取版本清单，请勿把该路径改为网络地址。
详细边界见[智能体安全平台 P0 技术基线](agent-security-p0-baseline.md)。

### 独立扫描 Worker 与 AI-Infra-Guard 内部服务

Worker 同时运行 `control_plane_validation`、`agent_risk_scan`、`dify_asset_inventory`、
`mcp_risk_scan`、`llm_redteam_scan` 和 `ai_infrastructure_vulnerability_scan`。模型红队和基础设施任务由固定版本的 `aig-scan-service` 在私有
`aig-control` 网络执行，服务端口不映射到宿主机。内置 Worker 无需先在
管理台创建身份：在项目根目录 `.env` 只配置一次 `AGENT_SECURITY_WORKER_TOKEN`，Backend 建表后会以
固定名称 `builtin-security-worker` 幂等注册，Worker 容器读取同一个值。令牌必须以 `amsw_` 开头，
前缀后至少包含 32 个 URL-safe 字符。示例已提供本地开发占位值；生产用
`printf 'amsw_%s\n' "$(openssl rand -hex 32)"` 生成独立随机值。生产安全启动会拒绝公开的开发凭据。

再为 Worker 配置一个 OpenAI-compatible 评估模型，并生成独立的内部服务 Token；推荐使用本平台模型网关，
并为专用 LLM API Key 只授权扫描所需模型。仅执行 MCP 元数据扫描时不需要评估模型；执行 Agent
风险扫描、LLM 红队或需要模型辅助的基础设施扫描时必须配置。`AIG_SCAN_SERVICE_TOKEN` 至少包含 32 个
随机 URL-safe 字符，由 Backend 健康检查、Worker 与内部服务共同使用，不能和 Worker Token、评估模型 Key 或目标凭据混用。然后执行：

```bash
./build.sh --all
docker compose up -d
docker compose ps agent-security-worker aig-scan-service
```

`.env.example` 列出 `AIG_SERVICE_URL`、`AIG_SERVICE_TOKEN` 和 Worker 控制面地址。
Compose 默认使用容器 DNS：`http://aig-scan-service:8093` 和 `http://backend:8000/api/v1/agent-security`。
本地源码运行 Backend/Worker 时，将它们改为可访问的宿主机地址，并为内部服务发布仅本机可访问的端口。
评估模型 Key 和模型名默认为空，不影响服务启动、控制面验证和 MCP 元数据扫描；实际模型扫描前必须配置真实值。

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

`AGENT_SECURITY_WORKER_TOKEN` 和评估模型 API Key 都是运行凭据，不是页面功能开关，不能写入
镜像或提交到 Git。根目录 `.env` 适合本地和受控离线部署；生产环境可由 Secret 管理能力以同名
环境变量注入。评估模型 Key、Worker Token 和扫描目标凭据是三类独立凭据，不能混用。
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
3. 分别提交一个授权的 Agent Mock、Dify 资产清单、MCP 元数据、受控 LLM 红队和授权网络端点扫描，确认任务从
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

P1 安全配置默认使用 SQLite，不新增数据库服务。`request_leases` 表协调共享同一 SQLite 文件的多 Worker 并发额度；它不支持多个主机各自使用独立 SQLite 文件时共享额度。MCP 上游默认只允许 HTTPS，可用 `MCP_OUTBOUND_ALLOWLIST` 配置允许的域名、通配域名或 CIDR。审计签名密钥通过 `AUDIT_SIGNING_PRIVATE_KEY_PATH` 持久化，`SECURITY_AUDIT_EXPORT_PATH` 是可选的追加式 JSONL 导出位置。

## 构建脚本

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
./package-release.sh -v v1.0.0 -p linux/arm64 -i /path/to/docker-installer-28.5.2-x86-arm.tar.gz -c /path/to/client-releases
```

输出：

```text
agent-manager_v1.0.0_x86.tar.gz
agent-manager_v1.0.0_arm.tar.gz
```

安装包内包含：

```text
docker_images/x86/agent-manager-images-v1.0.0.tar.xz
docker_images/arm/agent-manager-images-v1.0.0.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
scanner/releases/agent-manager-client-26.03.15.1-darwin-aarch64.dmg
scanner/releases/agent-manager-client-26.03.15.1-darwin-x86_64.dmg
scanner/releases/agent-manager-client-26.03.15.1-windows-x86_64.exe
scanner/releases/agent-manager-client-26.03.15.1-linux-x86_64.AppImage
```

Docker Compose 已将宿主机 `scanner/releases` 只读挂载到后端。部署完成后，管理员可在“客户端管理 → 安装客户端”按系统和版本下载；新增版本只需把新的 release 文件复制到该目录，无需重建镜像。

## 自动部署与离线发布

内部 GitLab Runner 使用 `agent-manager-release` 标签，流水线分为两个独立任务：

- 快速部署任务：只构建 x86 镜像、更新 Compose 并执行健康检查。代码合并并推送到 `dev` 时自动执行，镜像版本为 `dev-提交短哈希`。
- `offline-package`：推送正式版本标签时，在快速部署成功后自动生成 x86、ARM 离线包并上传 S3。
  上传前会分别验证两个包中的 `release-provenance.json`，要求版本等于 tag、Commit 等于流水线
  Commit、架构匹配，并且来自干净的 `git_clone`；任一不一致都会阻止发布。

```bash
git tag v1.0.1
git push origin v1.0.1
```

标签推送后，发布环境会先完成快速部署，再自动生成并上传客户离线包。

发布产物保存在：

```text
/home/ubuntu/releases/agent-manager_v1.0.1_arm.tar.gz
/home/ubuntu/releases/agent-manager_v1.0.1_x86.tar.gz
```

如需企业微信通知，在 GitLab 项目的 `Settings → CI/CD → Variables` 中添加掩码变量 `WECHAT_WEBHOOK_URL`。只有在 `v*` 发布标签已配置为 Protected tag 时才同时勾选 Protected，否则标签流水线读不到该变量。正式发布标签使用 `v数字.数字.数字` 格式；`client-vYY.MM.DD.N` 仍由 GitHub Actions 构建并同步桌面客户端。

内部发布环境的 Docker daemon 使用外网代理拉取基础镜像；GitLab CI 还通过 `BUILD_DOCKER_PROXY` 仅为 Buildx 进程设置 `HTTP_PROXY`/`HTTPS_PROXY`，确保 Docker Hub token 鉴权请求走代理。Backend 的 Debian 与 GitHub 下载分别通过 `BUILD_APT_PROXY`、`BUILD_GIT_PROXY` 使用代理，Python 包通过 `BUILD_PYPI_INDEX` 使用清华源；npm 保持直连。Docker 代理配置位于 `/etc/systemd/system/docker.service.d/http-proxy.conf`；修改后执行 `sudo systemctl daemon-reload && sudo systemctl restart docker`。

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

```text
用户名：默认 admin
密码：部署前在 `.env` 中设置的 `INITIAL_ADMIN_PASSWORD`
```
