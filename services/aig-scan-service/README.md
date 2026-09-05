# AI-Infra-Guard 内部扫描服务

该目录把固定版本的 Tencent AI-Infra-Guard 封装为 Agent Manager 的内部执行服务，供 `agent-security-worker` 调用。它不是面向用户的公共 API，也不暴露上游 Web UI。

## 固定版本与离线构建

- 上游版本固定为 `v4.6.0` / `e8931cc68001b66ad024fd87ef07394e9e96524a`。
- 完整上游源码、许可证和 NOTICE 随仓库及离线镜像交付，构建期间不执行 `git clone`。
- Go 与 Python 基础镜像使用 digest 固定；Go 二进制按 `TARGETARCH` 分别编译，不使用架构标签伪装。
- Python 上游依赖使用 `AIG-PromptSecurity/uv.lock`，服务封装依赖使用带哈希的 `requirements.lock`。
- `deploy/agent-security/upstreams.lock.json` 记录源码树、锁文件、本地安全修改和基础镜像。

## 调用与安全边界

服务随默认 `docker compose up -d` 启动，只在 Compose 的 `aig-control` 网络中提供 `8093` 端口，不映射到宿主机。包括 `/healthz` 在内的健康、任务创建、查询、结果和取消接口都要求 `Authorization: Bearer <AIG_SCAN_SERVICE_TOKEN>`。Backend、Worker 和服务使用同一个 Token；`.env.example` 提供本地开发占位值，生产需设置独立的高强度随机 Token。`AIG_SERVICE_URL` 配置调用地址，`AIG_SERVICE_TOKEN` 默认引用 `AIG_SCAN_SERVICE_TOKEN`。

容器以 UID/GID `10002:10002`、只读根文件系统、删除全部 Linux capability 和 `no-new-privileges` 运行。`/tmp` 用于上游临时数据库及报告，`/var/lib/aig-wrapper` 只保存不含目标凭据的任务恢复状态。上游日志和数据库写入路径已修改，禁止记录模型 Token、目标凭据、原始 Prompt 或原始 Response。

请求采用严格白名单和大小限制：模型红队只允许内置的小型数据集、限定攻击技术及最多 100 条 Prompt；基础设施扫描限制目标数量、超时、Header 和模型字段。Worker 仍须在把结果写入平台前执行响应结构校验和敏感字段处理。

## 任务恢复与 Kill Switch

服务为每个 Agent Manager attempt 保存上游 session ID。Worker 重试时应使用相同幂等键恢复已有 session，而不是重复创建扫描。服务启动后会核对上游任务状态；无法确认的任务会标记为错误，不会假装完成。

取消接口会终止承载 AI-Infra-Guard 的进程组并重新拉起干净的上游服务，因此返回 `execution_stopped=true` 表示计算进程已停止，而不只是更新数据库状态。镜像验收脚本会比较取消前后的上游 Agent PID 来验证这一点。

## 构建与验收

```bash
./build.sh --aig-scan-service
./scripts/verify-aig-scan-service-image.sh agent-manager-aig-scan-service:latest amd64
./scripts/verify-aig-scan-service-image.sh agent-manager-aig-scan-service:latest arm64
```

验收会检查真实镜像架构、固定版本标签、非 root/只读/无网络运行、健康状态、许可证与 SBOM，并创建和取消一个真实上游基础设施扫描任务。门禁还在容器内导入真实红队依赖，避免镜像表面健康但运行时模块缺失。CI 的离线发布流水线会对 AMD64、ARM64 分别执行同一套检查。

本地单元测试：

```bash
UV_CACHE_DIR=/private/tmp/skill-manager-uv-cache \
uv run pytest \
  tests/test_aig_scan_service.py \
  tests/test_aig_service_client.py \
  tests/test_agent_security_worker_deployment.py -q
```

## 已知边界

- 模型红队是动态测试，必须提供可访问的模型端点和短期凭据；扫描会真实消耗目标模型与评估模型额度。
- 基础设施扫描会主动访问目标地址。部署方必须通过网络策略限制允许的目标范围，不能把容器隔离当成目标授权。
- Wrapper 会在下发前校验 DNS 和双重 CIDR，但该校验不等同于内核级出站防火墙；生产环境仍应在容器网络或主机侧限制实际 egress。
- 当前上游报告不保证提供完整目标/评估模型 Token 计量；缺失时平台明确标记 `unavailable_from_upstream`，不估算或伪造用量。
- 上游任务数据库位于临时目录，服务恢复依赖封装层的持久化记录与上游可查询状态；无法核对时按错误处理。
- 扫描成功只表示本次选定规则和输入正常执行，不表示目标绝对安全。
