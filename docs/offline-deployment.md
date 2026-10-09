# 离线部署现场实施指南

本文档用于现场实施人员在客户内网环境快速部署 Agent Manager。

## 交付物

根据服务器架构，准备对应的安装包。CI 普通版本 tag（如 `1.0.6`）生成 x86 包，
带 `_arm` 的 tag（如 `1.0.6_arm`）生成 ARM 包，同时兼容 `v` 前缀。以下以 `1.0.6` 为示例，现场命令中的版本号应替换为实际交付版本：

```text
agent-manager_1.0.6_arm.tar.gz    # ARM 服务器
agent-manager_1.0.6_x86.tar.gz    # x86 服务器
```

安装包内主要包含：

```text
docker-compose.yaml
.env.example
start.sh                             # 加载镜像、启动、检查
upgrade.sh                           # 指定安装包升级
deploy/offline.py                     # 脚本共用逻辑（Python 标准库）
deploy/nginx/default.conf
release-provenance.json
docs/offline-deployment.md
docs/docker-deployment.md
scanner/releases/                    # 客户端发布文件
docker_images/<arch>/agent-manager-images-<tag>.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
```

安装包已包含平台、Worker 和内部扫描服务镜像，现场无需构建镜像。
包内 `docker-compose.yaml` 的应用镜像直接使用发布版本，例如 `agent-manager-backend:1.0.6`；
ARM 包使用完整版本 `1.0.6_arm`。配置中的旧 `TAG` 不再决定包内应用镜像版本。
交付包按部署清单组装，仓库源码树、测试及构建工具不进入包；镜像包含运行所需程序。
ARM tag 为 `1.0.6_arm` 时，包名为 `agent-manager_1.0.6_arm.tar.gz`，
内部镜像文件为 `docker_images/arm/agent-manager-images-1.0.6_arm.tar.xz`。
加载时以实际文件名为准，镜像版本可查看 `release-provenance.json`。

## 部署前检查

单节点生产环境建议准备 `16 vCPU`、`32 GiB` 内存和 `500 GiB` 可用 SSD/NVMe 空间。
这是容量规划起点，实际资源按客户数据量调整。

确认服务器架构：

```bash
uname -m
```

常见对应关系：

```text
x86_64   -> 使用 agent-manager_1.0.6_x86.tar.gz
aarch64  -> 使用 agent-manager_1.0.6_arm.tar.gz
arm64    -> 使用 agent-manager_1.0.6_arm.tar.gz
```

现场需要 Bash、Python 3（仅标准库，无需 pip 安装依赖）、Docker 和支持 `--wait-timeout` 的 Compose。
确认命令可用，当前用户有 Docker 访问权限：

```bash
python3 --version
docker --version
docker compose version
```

如果现场没有 Docker，先按客户环境使用安装包内的 Docker 安装程序完成安装，再确认上述命令可运行。

## 解压并启动

以下以 x86 包为例，ARM 服务器换用对应的 `_arm.tar.gz`：

```bash
tar -xzf agent-manager_1.0.6_x86.tar.gz
cd agent-manager
./start.sh
```

脚本自动加载包内 `.tar.xz` 镜像、核对 Docker 和镜像架构、在缺少 `.env` 时复制配置模板，
初始化缺失的签名密钥（已有密钥继续使用），然后启动服务。启动过程中禁止在线拉取和现场构建。
最后等待服务健康，并通过 Nginx 请求首页；全部通过才返回成功。默认最多等待 300 秒，可调整：

```bash
./start.sh --wait-timeout 600
```

首次生产部署应先准备配置，再运行脚本：

```bash
cp .env.example .env
# 编辑 .env，完成以下生产配置
./start.sh
```

为 `SECRET_KEY`、`AGENT_MANAGER_SANDBOX_API_KEY`、`AGENT_SECURITY_WORKER_TOKEN`、
`AIG_SCAN_SERVICE_TOKEN` 设置独立随机凭据，设置 `ENFORCE_SECURE_STARTUP=true`，
并设置至少 12 个字符的 `INITIAL_ADMIN_PASSWORD`。直接使用模板启动采用本地测试配置；
初始密码留空时的行为见下文。更多配置见 [Docker 部署文档](docker-deployment.md#生产部署)。

## 使用安装包升级

在原安装目录执行，安装包路径可以是绝对路径或相对于当前命令目录的路径：

```bash
./upgrade.sh /path/to/agent-manager_1.0.7_x86.tar.gz
# ARM 服务器使用 agent-manager_1.0.7_arm.tar.gz
```

旧安装目录还没有 `upgrade.sh` 时，先将新包解压到另一个目录，从新包调用并指定原安装目录：

```bash
/path/to/new/agent-manager/upgrade.sh /path/to/agent-manager_1.0.7_x86.tar.gz --install-dir /opt/agent-manager
```

脚本会：

1. 解压到原安装目录下的临时目录，检查包内容、版本及 Docker 架构。
2. 在 `backups/时间-随机后缀/` 中备份旧 Compose、Nginx 配置、部署脚本、版本信息、配置模板、部署文档、客户端发布目录及现有 `.env`。
3. 加载并验证新镜像，然后覆盖本次部署文件、更新客户端发布文件；现场 `.env` 保持不变，旧版本镜像归档保留。
4. 在原安装目录重建容器，保留 Docker 命名卷，等待健康检查并检查 Nginx 首页。

可追加 `--wait-timeout 600` 延长等待。脚本不会执行 `docker compose down -v`。
部署文件备份**不包含数据库、签名密钥和数据卷内容**；生产升级前应单独完成业务数据备份。
如果原来通过 `COMPOSE_PROJECT_NAME` 自定义项目名，升级时继续使用原值，保证连接原有数据卷。
新版 Compose 和 Nginx 配置会覆盖现场对这两个文件的直接修改，旧配置保留在备份目录。

升级失败时返回非零退出码，并显示备份路径；先检查容器状态和日志。启动新版本可能已经执行数据库迁移，
需要结合数据迁移情况制定恢复步骤，仅恢复旧 Compose 不能保证完成业务回滚。
备份目录含现场配置，应限制访问。仅使用可信来源的正式安装包。

## 验证启动

查看容器状态：

```bash
docker compose ps
```

所有核心服务应为 `running` 或 `healthy`。如有服务启动失败，查看后端日志：

```bash
docker compose logs --tail=100 backend
```

浏览器访问：

```text
http://<服务器IP>
```

### 管理员初始密码

默认管理员用户名为 `admin`。首次创建账号时会使用 `.env` 中的
`INITIAL_ADMIN_PASSWORD`。按上面的快速启动步骤设置后，登录时输入该密码。
如果首次启动前留空，系统会生成随机初始密码；生产安全模式则要求预先设置至少
12 个字符的密码，不会自动生成随机密码。

升级时保留原数据库和数据卷。只要数据库中已经存在该用户名的账号，登录仍使用原密码；
后来修改 `.env` 中的 `INITIAL_ADMIN_PASSWORD` 并重启容器，不会修改已有账号的密码。
如果更换数据库、删除数据卷，或修改 `INITIAL_ADMIN_USERNAME` 使系统找不到该账号，
则会按首次创建账号处理。登录后可从右上角账号菜单选择“修改密码”，输入当前密码和新密码；
有账号管理权限的管理员可在“系统管理 → 账号管理”中重置其他账号的密码。

只有未启用安全启动校验、数据库中没有该管理员账号且初始密码留空时，系统才会生成随机
密码。若此前以这种方式安装，可在安装目录执行下列命令查看当时保存的密码：

```bash
docker compose exec backend cat /app/runtime/data/initial-admin-password
```

文件保存的是当时生成的初始值，后续改密不会更新；文件存在或不存在都不能单独证明
当前登录密码。更多说明见 [Docker 部署文档](docker-deployment.md#管理员初始密码与升级)。

## 常用运维命令

停止服务：

```bash
docker compose down
```

重新启动：

```bash
docker compose up -d
```

查看后端日志：

```bash
docker compose logs -f backend
```

查看 Sandbox 日志：

```bash
docker compose logs -f sandbox
```

## 业务验收

登录管理台后，确认页面可访问，Worker 和内部扫描服务状态正常。需要验证扫描能力时，
先配置评估模型与获得授权的扫描目标，再提交测试任务，并记录任务状态与结果。
容器健康只表示服务已启动，不能代替实际扫描验收。详细验收和 Worker 运维步骤见
[Docker 部署文档](docker-deployment.md)。

## 现场注意事项

- 版本以包内 `docker-compose.yaml` 的镜像引用和 `release-provenance.json` 为准。
- ARM 和 x86 安装包不要混用。
- 当前交付的 `docker-compose.yaml` 固定使用宿主机 80 端口，并用五个 Docker 命名卷保存后端数据、上传文件、SQLite、Registry 和内部扫描任务数据；这些配置不是 `.env` 变量。现场确需调整时，应修改 `docker-compose.yaml`，记录现场差异后再启动。
- 域名、TLS 证书和外部负载均衡属于 Compose 入口之外的现场网络配置，不要只修改 `.env` 后假定已经生效。
- 脚本自动加载 `.tar.xz` 镜像；手动加载时可使用 `xz -dc ... | docker load`。
