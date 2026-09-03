# 离线部署现场实施指南

本文档用于现场实施人员在客户内网环境快速部署 Agent Manager。

## 交付物

现场至少需要拿到一个安装包：

```text
agent-manager_v1.0.0_arm.tar.gz    # ARM 服务器
agent-manager_v1.0.0_x86.tar.gz    # x86 服务器
```

安装包内通常包含：

```text
docker-compose.yaml
.env.example
docker_images/<arch>/agent-manager-images-v1.0.0.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
release-provenance.json
```

`release-provenance.json` 固化版本、目标架构、Git Commit、分支、来源模式和工作树是否包含未提交
修改。离线包删除 `.git` 后，现场证据采集仍以该文件核对真实构建来源；正式发布的
`worktree_dirty` 必须为 `false`。

镜像归档同时包含 `agent-manager-security-worker:<tag>`。该 Worker 使用 Compose
`agent-security` profile，常规 `docker compose up -d` 不会启动。

正式发布应从已验证的 Git tag/分支生成。仅在提交前验收当前工作树时，可以显式使用
`--source-dir`；该模式复制 Git 已跟踪文件和未被忽略的新增文件，不复制 `.env`、构建缓存等
Git 忽略内容，因此不会把本地密钥自动装入离线包：

```bash
./package-release.sh \
  --version v-next-acceptance \
  --platform linux/arm64 \
  --source-dir . \
  --installer agent-manager/installers/docker-installer-28.5.2-x86-arm.tar.gz
```

`--source-dir` 只解决“验收未提交工作树”的来源问题，不改变正式发布规则，也不能替代在目标
x86_64/ARM64 主机上的安装、健康检查和业务回归。

Frontend 镜像在安装锁定依赖后执行 `npm audit --audit-level=low`；发现任何已知 low、moderate、high
或 critical 漏洞都会中止镜像和离线包构建。该门禁依赖构建时的软件源审计数据，正式离线包应由发布
流水线在联网构建区生成，不能在隔离目标主机上通过跳过审计重新打包。

## 部署前检查

单节点生产环境建议从 `16 vCPU`、`32 GiB` 内存和 `500 GiB` 可用 SSD/NVMe
容量起步。该规格是初始容量基线，不是最低运行门槛；Skill 数量、平均包体积、历史版本、
扫描报告、审计数据和日志保留越多，所需磁盘容量越大。现场应结合数据保留周期完成容量
评估，并至少保留 `30%` 磁盘余量，避免镜像加载、升级回滚或扫描临时文件耗尽空间。

确认服务器架构：

```bash
uname -m
```

常见对应关系：

```text
x86_64   -> 使用 agent-manager_v1.0.0_x86.tar.gz
aarch64  -> 使用 agent-manager_v1.0.0_arm.tar.gz
arm64    -> 使用 agent-manager_v1.0.0_arm.tar.gz
```

确认 Docker 和 Compose 可用：

```bash
docker --version
docker compose version
```

如果现场没有 Docker，先从安装包内的 `installers/docker-installer-28.5.2-x86-arm.tar.gz` 按客户环境安装 Docker。

## ARM 快速启动

```bash
tar -xzf agent-manager_v1.0.0_arm.tar.gz
cd agent-manager

xz -dc docker_images/arm/agent-manager-images-v1.0.0.tar.xz | docker load

./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:v1.0.0 arm64

cp .env.example .env
# 编辑 .env，替换全部 replace-with-* 占位值，并保持 ENFORCE_SECURE_STARTUP=true
TAG=v1.0.0 docker compose run --rm --no-deps backend agent-manager signing-key init
TAG=v1.0.0 docker compose up -d
docker compose ps
```

## x86 快速启动

```bash
tar -xzf agent-manager_v1.0.0_x86.tar.gz
cd agent-manager

xz -dc docker_images/x86/agent-manager-images-v1.0.0.tar.xz | docker load

./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:v1.0.0 amd64

cp .env.example .env
# 编辑 .env，替换全部 replace-with-* 占位值，并保持 ENFORCE_SECURE_STARTUP=true
TAG=v1.0.0 docker compose run --rm --no-deps backend agent-manager signing-key init
TAG=v1.0.0 docker compose up -d
docker compose ps
```

## 启动验证

查看容器状态：

```bash
docker compose ps
```

所有核心服务应为 `running` 或 `healthy`。

安全 Worker 镜像门禁使用 `--pull never` 和 `--network none`，因此可证明已加载镜像能在断网、
只读根文件系统和默认资源限制下完成自检。它不连接 Backend 或扫描目标；现场仍须继续完成
Compose 健康、Worker Token、任务领取、真实授权目标以及中断/恢复测试。

查看日志：

```bash
docker compose logs -f
docker compose logs -f backend
```

浏览器访问：

```text
http://<服务器IP>
```

默认账号：

```text
用户名：默认 admin
密码：部署前在 `.env` 中设置的 `INITIAL_ADMIN_PASSWORD`
```

## 常用运维命令

停止服务：

```bash
docker compose down
```

重新启动：

```bash
TAG=v1.0.0 docker compose up -d
```

查看后端日志：

```bash
docker compose logs -f backend
```

查看 Sandbox 日志：

```bash
docker compose logs -f sandbox
```

如需验收四类安全目标，在安装目录根 `.env` 配置一次 `AGENT_SECURITY_WORKER_TOKEN`；Backend
会自动注册固定的内置 Worker 身份，Worker 读取同一个值，不需要先调用管理接口。评估模型配置也写入
同一 `.env`，并为内部固定引擎配置独立的 `AIG_SCAN_SERVICE_TOKEN`。这四类凭据相互独立，不能复用：

- Worker 身份 Token：`AGENT_SECURITY_WORKER_TOKEN`
- 内部引擎服务 Token：`AIG_SCAN_SERVICE_TOKEN`
- 评估模型 API Key
- 每个扫描目标单独加密保存的目标凭据

```bash
TAG=v1.0.0 \
  docker compose --profile agent-security up -d
docker compose ps agent-security-worker
```

Worker 与内部引擎镜像已包含锁定的 AI-Infra-Guard Agent Scan、MCP 分类契约、模型红队、基础设施扫描
源码、依赖、LICENSE、NOTICE 和 SBOM，
离线启动不访问 GitHub 或 PyPI。现场仍需准备经授权的扫描目标和可访问的评估模型；只有镜像健康
或控制面任务成功，不能描述为目标已经完成实际风险扫描。P3 MCP 扫描只读取 Gateway 元数据
脱敏快照，不执行 `tools/call`，也不需要目标凭据或评估模型；空 Tool 集合会失败关闭。该能力是
引用上游分类/净化契约的平台元数据 Adapter，不等同于完整上游动态 MCP Scan。LLM 红队会真实调用目标
和评估模型并按实际 Prompt 形成 Case；基础设施扫描会主动访问显式授权 URL，只有组件、版本和 CVE 规则
同时匹配才生成 Finding，端口或版本证据不足时显示 `unverified`。P4 统一轨迹 API、
SDK 和网关发布已经实现；P5 对话/轨迹可视化已经启用，但不等同于完整 Harness 前端。

`dify_asset_inventory` 也由同一个 Worker 离线执行，但会访问管理员明确登记的自建 Dify Console；这不是
离线包向公网回连。现场在管理台配置 Console Base URL、Workspace ID、App ID，并将 Admin API Key 作为
`dify_console_api` 目标凭据加密保存，不写入 `.env`、Compose 或验收材料。Console 采集固定使用
`include_secret=false`，手动 DSL 只作为回退。私网 Console 必须同时加入目标 CIDR 与扫描策略出站 CIDR。
若现场不允许访问 Dify Console，只能采用手动 DSL，应用详情、创建时间等 Console 独有字段会保持未采集。

Worker 默认以非 root、只读根文件系统、`/tmp` tmpfs、无额外 capability、512 MiB 内存、1 个 CPU
和 128 个进程上限运行。长任务的成功续租会刷新健康标记；控制面持续不可达时健康检查会失败。
现场如需调优，可通过 `AGENT_SECURITY_WORKER_TMPFS_SIZE`、`AGENT_SECURITY_WORKER_PIDS_LIMIT`、
`AGENT_SECURITY_WORKER_MEMORY_LIMIT`、`AGENT_SECURITY_WORKER_CPU_LIMIT`、
`AGENT_SECURITY_WORKER_STOP_GRACE_PERIOD`、`AGENT_SECURITY_WORKER_LOG_MAX_SIZE` 和
`AGENT_SECURITY_WORKER_LOG_MAX_FILES` 覆盖默认值，并把变更和压测依据记录进验收证据。

### Worker 现场验收、恢复和升级

Worker Token 和评估模型 Key 是运行凭据，不是页面启用开关；页面默认开启，无需增加功能开关。
现场应保护根 `.env` 或通过 Secret 管理系统注入同名变量，并只在证据中记录 Worker ID、Token 前缀、
镜像 ID 和时间。外部 Worker 的创建、查看和吊销接口仍保持不变：

- `POST /api/v1/agent-security/workers`
- `GET /api/v1/agent-security/workers`
- `POST /api/v1/agent-security/workers/{worker_id}/revoke`

手工创建的外部身份不支持原地轮换，仍按“创建新身份 → 切换 → 确认 → 吊销旧身份”操作。内置身份
修改 `.env` 后重建 Backend 与 Worker 即可轮换，Worker ID 不变，旧 Token、公钥和心跳状态失效；
相同 Token 的已吊销内置身份不会自行复活，必须换新 Token。现场验收至少保存以下证据：

1. `docker compose ps agent-security-worker` 的健康状态和 `docker inspect` 的镜像 ID/架构。
2. 管理接口返回的 `last_heartbeat_at` 与非空公钥指纹；响应不得保存 `token_once`。
3. 授权 Agent Mock、Dify 资产清单、MCP 元数据、受控 LLM 红队和授权基础设施端点任务的任务 ID、用例数、Finding 数、
   停止原因和产物 SHA-256。真实客户目标需要另行授权和脱敏取证。
   Dify 清单同时记录字段来源、五类覆盖状态和快照差异；任务成功不能写成资产全部验证或目标安全。
4. 最近十分钟 Worker 日志的敏感信息检查；不得收集原始 Prompt/Response、目标凭据或 API Key。

中断演练使用专用验收任务：记录任务 ID/`attempt`，执行 `docker compose stop
agent-security-worker`，等待该策略的 `lease_seconds` 到期后，由管理员调用
`POST /api/v1/agent-security/workers/recover`，再启动 Worker。预期有剩余重试次数的任务回到
`pending` 并被重新领取；重试耗尽时明确失败，不生成虚假安全结论。Worker 下一次领取也会运行同一
过期租约恢复逻辑，但验收应保存 recover API 返回的 `timed_out`、`retried` 和 `failed` 计数。

升级前必须先加载新归档并执行对应架构门禁，然后在同一 Secret 注入上下文中只重建 Worker：

```bash
./scripts/verify-agent-security-worker-image.sh agent-manager-security-worker:<new-tag> <amd64-or-arm64>
TAG=<new-tag> docker compose --profile agent-security up -d --no-deps agent-security-worker
docker compose ps agent-security-worker
```

确认健康、心跳、公钥登记和升级后扫描回归，再结束变更窗口。失败时使用保留的旧镜像回滚：

```bash
TAG=<old-tag> docker compose --profile agent-security up -d --no-deps agent-security-worker
docker compose ps agent-security-worker
```

中断、恢复、升级和回滚的完整命令边界与预期状态见
[Docker 部署说明](docker-deployment.md#worker-生命周期运维)。离线镜像门禁只证明镜像可运行；
没有任务级证据时，不能把它写成 Worker 中断恢复或客户目标扫描已经通过。

## 现场注意事项

- `TAG` 必须和安装包版本一致，例如 `v1.0.0`。
- ARM 和 x86 安装包不要混用。
- 当前交付的 `docker-compose.yaml` 固定使用宿主机 80 端口，并用四个 Docker 命名卷保存后端数据、上传文件、SQLite 和 Registry 数据；这些配置不是 `.env` 变量。现场确需调整时，应修改 `docker-compose.yaml`，记录现场差异后再启动。
- 域名、TLS 证书和外部负载均衡属于 Compose 入口之外的现场网络配置，不要只修改 `.env` 后假定已经生效。
- 镜像文件是 `.tar.xz`，需要用 `xz -dc ... | docker load` 加载。
