# 离线部署现场实施指南

本文档用于现场实施人员在客户内网环境快速部署 Agent Manager。

## 交付物

根据服务器架构，准备对应的安装包。CI 普通版本 tag（如 `1.0.6`）生成 x86 包，
带 `_arm` 的 tag（如 `1.0.6_arm`）生成 ARM 包，同时兼容 `v` 前缀。以下以 `v1.0.0` 为示例，现场命令中的版本号应替换为实际交付版本：

```text
agent-manager_v1.0.0_arm.tar.gz    # ARM 服务器
agent-manager_v1.0.0_x86.tar.gz    # x86 服务器
```

安装包内主要包含：

```text
docker-compose.yaml
.env.example                         # 已写入本包镜像 TAG
deploy/nginx/default.conf
release-provenance.json
docs/offline-deployment.md
docs/docker-deployment.md
scanner/releases/                    # 客户端发布文件
docker_images/<arch>/agent-manager-images-<tag>.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
```

安装包已包含平台、Worker 和内部扫描服务镜像，现场无需构建镜像。
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
x86_64   -> 使用 agent-manager_v1.0.0_x86.tar.gz
aarch64  -> 使用 agent-manager_v1.0.0_arm.tar.gz
arm64    -> 使用 agent-manager_v1.0.0_arm.tar.gz
```

确认 Docker 和 Compose 可用：

```bash
docker --version
docker compose version
```

如果现场没有 Docker，先按客户环境使用安装包内的 Docker 安装程序完成安装，再确认上述两个命令可运行。

## 解压并加载镜像

ARM 服务器执行：

```bash
tar -xzf agent-manager_v1.0.0_arm.tar.gz
cd agent-manager

xz -dc docker_images/arm/agent-manager-images-v1.0.0_arm.tar.xz | docker load
```

x86 服务器执行：

```bash
tar -xzf agent-manager_v1.0.0_x86.tar.gz
cd agent-manager

xz -dc docker_images/x86/agent-manager-images-v1.0.0.tar.xz | docker load
```

以下命令均在解压得到的 `agent-manager` 目录执行。

## 快速启动

首次安装时复制配置模板，并在 `.env` 中设置登录密码：

```bash
cp .env.example .env
```

将 `.env` 中的 `INITIAL_ADMIN_PASSWORD=` 改为自己设置的密码，例如
`INITIAL_ADMIN_PASSWORD=replace-with-your-password`，然后启动：

```bash
docker compose up -d
```

这套快速启动使用模板中的本地测试配置。已有部署升级时保留原 `.env` 和数据卷，
将原 `.env` 的 `TAG` 更新为新包 `.env.example` 中的值后启动；`INITIAL_ADMIN_PASSWORD` 不会修改已有账号的密码。
正式生产环境先为 `SECRET_KEY`、`AGENT_MANAGER_SANDBOX_API_KEY`、
`AGENT_SECURITY_WORKER_TOKEN`、`AIG_SCAN_SERVICE_TOKEN` 设置独立随机凭据，
设置 `ENFORCE_SECURE_STARTUP=true` 和至少 12 个字符的 `INITIAL_ADMIN_PASSWORD`，
再初始化签名密钥并启动（已加载的镜像直接使用）：

```bash
docker compose run --rm --no-deps backend agent-manager signing-key init
docker compose up -d
```

更多配置见 [Docker 部署文档](docker-deployment.md#生产部署)。

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

- `TAG` 必须与 `.env.example` 和 provenance 中的镜像版本一致，例如 `1.0.6` 或 `1.0.6_arm`。
- ARM 和 x86 安装包不要混用。
- 当前交付的 `docker-compose.yaml` 固定使用宿主机 80 端口，并用四个 Docker 命名卷保存后端数据、上传文件、SQLite 和 Registry 数据；这些配置不是 `.env` 变量。现场确需调整时，应修改 `docker-compose.yaml`，记录现场差异后再启动。
- 域名、TLS 证书和外部负载均衡属于 Compose 入口之外的现场网络配置，不要只修改 `.env` 后假定已经生效。
- 镜像文件是 `.tar.xz`，需要用 `xz -dc ... | docker load` 加载。
