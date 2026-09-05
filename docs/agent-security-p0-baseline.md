# 智能体安全平台 P0 技术基线

本文档固定下一版本开发所使用的上游版本、许可边界、功能开关、稳定编码、数据迁移、Worker 和离线交付方案。机器可校验的版本信息位于 `deploy/agent-security/upstreams.lock.json`。

## 1. 上游版本基线

| 项目 | 锁定版本 | 精确 Commit | 用途 |
|---|---|---|---|
| Tencent AI-Infra-Guard | `v4.6.0` | `e8931cc68001b66ad024fd87ef07394e9e96524a` | Phase 2/3 的隔离扫描 Worker 来源 |
| DeepSeek Harness | `dsh-v0.1.2-alpha.1` | `cd5ef8148158c3a752a658978873241fdf8e2bbc` | Session 事件模型和 Trajectory UI 参考 |

禁止使用 `main`、`master`、未锁定分支或仅有版本名称没有 Commit 的来源构建扫描 Worker。升级上游时必须同时更新 lock、许可清单、兼容测试和本文件。

AI-Infra-Guard Agent Scan 的首期目标类型以锁定版本的 Provider 实现为准，包括 Dify、Coze、OpenAI-compatible、Anthropic、Google、Cohere、Hugging Face、Replicate、通用 HTTP 和 WebSocket。列表的机器可读版本在 lock 文件中，产品页面不能维护另一份不同的硬编码清单。

## 2. 许可和复用边界

AI-Infra-Guard 根许可证为 Apache-2.0，并包含强制归属 NOTICE。发生源码复制、修改或二进制分发时必须：

1. 随产物提供其 `LICENSE` 和 `NOTICE`。
2. 在产品文档、关于页面或发行说明中展示“Based on Tencent Zhuque Lab AI-Infra-Guard”。
3. 标记修改过的上游文件。
4. Worker 首次构建时生成 SBOM，并审查解析后的传递依赖许可证。

DeepSeek Harness 为 MIT。本项目 P0 仅参考设计，不引入其包或源码，因此当前没有运行时 NOTICE 交付项；未来若复制实质代码，必须保留 MIT 许可声明。

完整复用清单见 `deploy/agent-security/THIRD_PARTY_NOTICES.md`。

## 3. 默认启用和紧急关停

| 环境变量 | 默认值 | Feature ID | 控制范围 |
|---|---|---|---|
| `AGENT_SECURITY_SCANNING_ENABLED` | `true` | `agent_security_scanning` | Agent/MCP 安全扫描基线和后续扫描 API、菜单 |
| `RUNTIME_TRACE_ENABLED` | `true` | `runtime_trace` | 统一轨迹基线和后续轨迹 API、菜单 |

常规 Compose 部署不在 `.env` 暴露这两个配置，安装后页面默认启用。变量只保留为运维紧急
关停手段；只有通过容器覆盖显式设为 `false` 时，才执行以下行为：

从早期 P0 版本升级时，如果旧 `.env` 留有值为 `false` 的同名变量，应删除后重建 Backend；
任何显式环境变量都会覆盖代码中的默认开启值。

- `/api/system/capabilities` 返回对应能力 `false`。
- 管理台不渲染对应菜单。
- 直接访问功能路由会回到平台总览。
- 直接调用受控后端 API 返回 404 和稳定 `error_code`，避免暴露未启用接口。
- 前端读取能力失败时按全部关闭处理，不使用上次缓存放行。

P2 已启用 AI-Infra-Guard Agent Scan Adapter，P3 已启用 MCP 元数据扫描 Adapter，P4 已启用统一
轨迹 API、Agent SDK 和网关发布。DeepSeek Harness 风格的对话/轨迹可视化仍属于 P5；基线页面
必须明确展示该边界，不能把 P4 后端能力表述成前端时间线已经完成。

## 4. 稳定编码

编码的代码源位于 `backend/feature_flags.py`，以下值在已有客户端使用后不能修改语义：

### 4.1 Feature ID

- `agent_security_scanning`
- `runtime_trace`

### 4.2 P0 Error Code

- `agent_security.feature_disabled`
- `runtime_trace.feature_disabled`
- `agent_security.baseline_unavailable`
- `agent_security.baseline_invalid`

### 4.3 后续阶段预留状态编码

- 扫描任务：`pending`、`running`、`succeeded`、`failed`、`cancelled`、`timed_out`、`blocked`
- 轨迹完整度：`full`、`gateway_partial`、`model_only`、`mcp_only`
- 执行模式：`passive`、`read_only`、`active_safe`、`active_full`
- 事件来源：`agent_sdk`、`model_gateway`、`mcp_gateway`、`runtime_governance`、`knowledge_connector`、`security_worker`
- 审计事件：`security_target.created`、`security_target.updated`、`security_target.credential_rotated`、`security_scan_policy.updated`、`security_scan_task.created`、`security_scan_task.cancelled`、`security_scan_report.exported`、`runtime_trace.raw_payload_viewed`、`runtime_trace.exported`

新增后端错误必须返回稳定 `error_code` 和 `error_params`，前端不得通过中文或英文错误文本判断业务逻辑。

## 5. 数据库迁移方案

Phase 1 新增表时遵循当前 SQLAlchemy `Base.metadata` 模型，但生产升级不能只依赖 `create_all`：

1. 新表由 SQLAlchemy 模型声明并通过 `create_all` 创建。
2. 对已有表增加列、索引或约束时，在 `backend_schema_migrations` 中增加唯一迁移名称。
3. 每个迁移必须幂等，事务内执行，成功后写入迁移名称和时间。
4. 迁移测试同时覆盖空数据库和上一版本数据库升级。
5. 不允许在应用请求处理过程中临时改变 Schema。

P1 已新增 `security_targets`、`security_target_credentials`、`security_scan_policies`、
`security_scan_tasks`、`security_scan_cases`、`security_findings`、`security_scan_artifacts` 和
`security_scan_workers`，并写入幂等迁移标记 `agent_security_p1_v1`。P2 通过幂等迁移
`agent_security_p2_v1` 增加加密扫描选项、会话状态、引擎版本、Finding 指纹/处置、加密原始
产物和 Worker 临时公钥字段。P4 已创建 `runtime_trace_sessions`、`runtime_trace_events`、
`runtime_trace_payloads`、`runtime_trace_ingest_batches` 和 `runtime_trace_exports`，迁移标记为
`runtime_trace_p4_v1`。

## 6. Worker 镜像方案

Phase 1 已新增独立镜像 `agent-manager-security-worker:<TAG>`：

- P2/P3 镜像包含锁定的 AI-Infra-Guard Agent Scan/MCP Scan 源码、依赖约束、许可证、NOTICE 和 SBOM；容器
  启动时不执行 clone/install。
- Worker 不复用主 Backend 的进程权限和凭据。
- 主平台通过任务租约分发任务，Worker 使用独立最小权限凭证领取和回传结果。
- Agent 扫描目标凭据通过 Worker X25519 公钥、HKDF-SHA256 和 AES-GCM 生成与任务、Worker、
  凭据及租约到期时间绑定的短期密封信封，不返回数据库密文或长期明文。
- 出站网络由环境策略、CIDR/域名白名单和预算控制。
- 镜像同时支持 `linux/amd64` 和 `linux/arm64`。
- AI-Infra-Guard 原始 Web Server、账号体系和前端不进入产品运行拓扑。

## 7. 离线部署方案

正式离线包必须在联网 CI 构建阶段完成以下工作：

1. 使用 lock 中的 tag 和 Commit 获取、校验上游源码。
2. 构建 Worker 镜像并生成 SBOM、LICENSE 和 NOTICE 交付物。
3. 将 Worker 镜像和现有平台镜像一起保存到 `docker_images/<arch>/`。
4. 离线现场只执行 `docker load` 和 Compose 启动，不访问 GitHub、PyPI 或 npm registry。
5. 离线验收通过断网启动、健康检查和一个本地 Mock 扫描任务证明。

后端基线读取本地 lock 文件，启动和请求处理均不访问上游仓库。P2 Worker 已加入
`build.sh --all`、默认 Compose 服务和离线镜像保存清单；锁定源码和 Python
依赖在联网构建阶段进入镜像，运行时不会访问 GitHub 或 PyPI。

## 8. P0 可测试接口

管理员登录后：

- `GET /api/system/capabilities`：查看两个功能开关和锁定版本摘要。
- `GET /api/v1/agent-security/baseline`：默认返回 AI-Infra-Guard 基线。
- `GET /api/v1/runtime-traces/baseline`：默认返回 DeepSeek Harness 参考基线。

这三个接口不启动扫描、不采集轨迹、不调用外部网络。
