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
docker compose up -d
docker compose ps
```

本地测试不要求先创建 `.env`。Compose 会使用仅限本机开发的占位密钥，并关闭生产
安全启动校验；首次创建管理员时，随机密码保存在持久化数据卷中，可执行以下命令读取：

```bash
docker compose exec backend cat /app/runtime/data/initial-admin-password
```

访问：

```text
http://localhost
```

## 生产部署

生产环境必须创建 `.env`，替换所有 `replace-with-*` 值，并保持
`ENFORCE_SECURE_STARTUP=true`：

```bash
cp .env.example .env
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
