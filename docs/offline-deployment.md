# 离线部署现场实施指南

本文档用于现场实施人员在客户内网环境快速部署 Agent Manager。

安装或升级后，在“系统管理 → License 授权”导出当前部署申请，由厂商独立签发工作站生成 License 后导入。
没有有效授权时新增与扫描受限。可信公钥随后端镜像交付，签发私钥不进入客户安装包。
备份业务数据时同时备份 data 卷中的 `license/state.db`，保持部署标识、已接收修订及授权历史。
详见 [离线授权操作与执行边界](license.md)。

## 交付物

按服务器架构选择安装包，以下版本号请替换为实际交付版本：

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
deploy/offline.sh                     # 脚本共用逻辑（Bash）
deploy/nginx/default.conf
release-provenance.json
release-info                         # 版本、平台（两行文本）
docs/offline-deployment.md
docs/docker-deployment.md
scanner/releases/                    # 客户端发布文件
docker_images/<arch>/agent-manager-images-<tag>.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
```

安装包包含运行镜像和部署文件，应用版本已固定。版本与架构见 `release-provenance.json`。

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

现场需要 Bash、GNU tar/coreutils（含 timeout）、util-linux 的 flock、gzip、awk、Docker 和支持健康等待、镜像列表输出及当前编排格式的 Compose。
确认命令可用，当前用户有 Docker 访问权限：

```bash
docker --version
docker info
docker compose version || docker-compose version
```

如果现场没有 Docker，先按客户环境使用安装包内的 Docker 安装程序完成安装，再确认上述命令可运行。

打包时会将附带 Docker 安装程序的二进制安装权限固定为 `0755`，不受现场 `umask 027/077` 影响。
旧安装程序使用 `cp`，可能将 `/usr/local/bin/docker-init` 安装为 `0750` 或 `0700`，
导致非 root 扫描容器启动时报 `exec: "/sbin/docker-init": permission denied`。
已有现场若确认该文件权限异常，由管理员执行 `chmod 755 /usr/local/bin/docker-init` 后重新运行 `bash start.sh`。
若权限正常仍失败，继续检查实际 init 路径、挂载限制及主机安全策略。

脚本优先使用 `docker compose`，也支持兼容的 `docker-compose`。Compose 需支持
`up --wait --wait-timeout`、`config --images` 和 `env_file.required`。
下文手动命令以 `docker compose` 为例，使用独立程序时替换为 `docker-compose`。

检查失败时会停止操作并明确提示：

| 提示 | 处理方式 |
| --- | --- |
| Docker 未安装或未加入 PATH | 安装包内的 Docker 安装程序完成安装后，确认 `docker --version` 可运行 |
| 无法连接 Docker 服务 | 先核对 `docker context show` 和 `DOCKER_HOST`；本机 systemd 环境检查 `systemctl status docker`，确认需要后运行 `sudo systemctl start docker`；rootless 使用 `systemctl --user status docker` |
| 当前用户无权访问 Docker | 使用有权限的账号，或请管理员配置 Docker 用户组后重新登录；rootless 检查当前用户的 socket/context |
| 两种 Compose 命令均不可用 | 安装 Compose 插件或独立程序，确认对应的 `version` 命令可运行 |
| Compose 版本不兼容或配置无法解析 | 更新 Compose，并检查 `.env` 和 `docker-compose.yaml` 的格式 |
| 检查超时或其他连接错误 | 运行 `docker info` 排查 context、远端地址、TLS 和认证配置 |

## 解压并启动

### 生产配置

为 `SECRET_KEY`、`AGENT_MANAGER_SANDBOX_API_KEY`、`AGENT_SECURITY_WORKER_TOKEN`、
`AIG_SCAN_SERVICE_TOKEN` 设置独立随机凭据，设置 `ENFORCE_SECURE_STARTUP=true`，
并设置至少 12 个字符的 `INITIAL_ADMIN_PASSWORD`。直接使用模板启动采用本地测试配置；
初始密码留空时的行为见下文。更多配置见 [Docker 部署文档](docker-deployment.md#生产部署)。

### 解压与启动

以下以 x86 包为例，ARM 服务器换用对应的 `_arm.tar.gz`：

```bash
tar -xzf agent-manager_1.0.6_x86.tar.gz
cd agent-manager
cp .env.example .env
# 编辑 .env，完成上述生产配置后启动
./start.sh
```

首次启动默认监听宿主机 80 端口。需要自定义端口时：

```bash
./start.sh --port 8088
# 访问 http://<服务器IP>:8088
```

`--port` 接受 1–65535，保存为安装目录 `.env` 中的 `HTTP_PORT`。
以后不带 `--port` 启动，以及运行 `upgrade.sh`，都会沿用这个端口；再次指定可更改端口。
脚本以安装目录 `.env` 为端口配置来源，其他配置项和凭据保持原样。
请确保所选端口可用。Sandbox 的本机端口仍为 `127.0.0.1:8194`。

脚本自动加载包内 `.tar.xz` 镜像、核对 Docker 和镜像架构、在缺少 `.env` 时复制配置模板，
初始化缺失的签名密钥（已有密钥继续使用），然后启动服务。启动过程中禁止在线拉取和现场构建。
最后等待服务健康，并通过 Nginx 请求首页；全部通过才返回成功。

签名密钥随数据卷保存，启动和升级沿用已有密钥。详细检查与恢复见
[AIDR 策略签名密钥](docker-deployment.md#aidr-策略签名密钥)。

默认最多等待 300 秒，可调整：

```bash
./start.sh --wait-timeout 600
```

## 获取并导入授权文件

1. 安装完成后，以管理员登录，打开 **系统管理 → License 授权**。填写厂商提供的客户编号和客户名称，导出 `customer-request.json`。
2. 将申请文件交给厂商，获取签发的 `.license` 授权文件。
3. 在同一页面选择授权文件，点击 **验证并导入**，确认状态为“有效”，并核对有效期、模块和客户端额度。

详细操作见 [License 操作指南](license.md)。升级和备份时保留数据卷中的授权状态与签名密钥。

### 交付检查

实际交付还应逐项确认：

- [ ] 包来源、版本、provenance 与目标架构匹配，安装包可以解压，文件清单完整。
- [ ] 在目标离线环境运行包内 `start.sh`，镜像加载、签名初始化、六个服务健康及首页检查通过。
- [ ] 从实际部署导出申请、签发并导入，在授权范围内完成扫描、网关与防护业务验收。
- [ ] 对实际新旧安装包执行 `upgrade.sh`，确认原项目名、`.env`、签名身份、业务数据与授权保留。
  脚本会替换主 Compose；使用自定义公钥挂载时，在维护窗口重新合并现场挂载配置并重建 backend，核对授权有效后再恢复业务。
- [ ] 备份可恢复；恢复后的部署标识、密钥、授权和业务记录与备份一致。

共享服务器上的复验应使用独立项目、端口、网络和空卷，并同时隔离 Sandbox 发布端口；
具体边界及收尾检查见 [隔离验证](docker-deployment.md#隔离验证与已验证范围)。

## 使用安装包升级

在原安装目录执行，安装包路径可以是绝对路径或相对于当前命令目录的路径：

```bash
./upgrade.sh /path/to/agent-manager_1.0.7_x86.tar.gz
# ARM 服务器使用 agent-manager_1.0.7_arm.tar.gz
```

升级已有安装时，可将新包解压到另一个目录，使用新包中的 `upgrade.sh` 并指定原安装目录：

```bash
/path/to/new/agent-manager/upgrade.sh /path/to/agent-manager_1.0.7_x86.tar.gz --install-dir /opt/agent-manager
```

脚本会：

1. 解压到原安装目录下的临时目录，检查包内容、版本及 Docker 架构。
2. 在 `backups/时间-随机后缀/` 中备份旧 Compose、Nginx 配置、部署脚本、版本信息、配置模板、部署文档、客户端发布目录及现有 `.env`。
3. 加载并验证新镜像，然后覆盖本次部署文件、更新客户端发布文件；现场 `.env` 保持不变，旧版本镜像归档保留。
4. 在原安装目录重建容器，保留 Docker 命名卷，等待健康检查并检查 Nginx 首页。

升级保留 `.env` 中的 `HTTP_PORT`，新 Compose 使用该端口，因此无需在升级时重新指定。
客户端安装程序和更新文件随包放在 `scanner/releases/`，升级时备份并更新该目录，
由后端通过只读挂载提供下载；自定义端口后从同一管理台地址下载客户端即可。

可追加 `--wait-timeout 600` 延长等待。脚本不会执行 `docker compose down -v`。
部署文件备份**不包含数据库、签名密钥和数据卷内容**；生产升级前应单独完成业务数据备份。

其中 `backend_data` 卷的 AIDR P-256 私钥必须随原数据恢复。客户端已固定对应公钥，
重新生成私钥会改变信任身份；需要轮换时应同步更新客户端信任，不能将删除密钥作为常规升级步骤。

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
http://<服务器IP>            # HTTP_PORT=80
http://<服务器IP>:8088       # 示例：使用 start.sh --port 8088
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

| 操作 | 命令 |
| --- | --- |
| 停止服务 | `docker compose down` |
| 启动服务 | `docker compose up -d` |
| 查看后端日志 | `docker compose logs -f backend` |
| 查看 Sandbox 日志 | `docker compose logs -f sandbox` |

## 业务验收

登录管理台后，确认页面可访问，Worker 和内部扫描服务状态正常。需要验证扫描能力时，
先配置评估模型与获得授权的扫描目标，再提交测试任务，并记录任务状态与结果。
容器健康只表示服务已启动，不能代替实际扫描验收。详细验收和 Worker 运维步骤见
[Docker 部署文档](docker-deployment.md)。

## 现场注意事项

- 版本以包内 `docker-compose.yaml` 的镜像引用和 `release-provenance.json` 为准。
- ARM 和 x86 安装包不要混用。
- HTTP 入口由安装目录 `.env` 的 `HTTP_PORT` 控制，首次默认 80；通过 `./start.sh --port <端口>` 保存并应用，升级继续沿用。
- 五个 Docker 命名卷 `backend_data`、`backend_uploads`、`backend_sqlite`、`agent_manager_registry` 和 `aig_scan_jobs` 保存后端数据、上传文件、SQLite、Registry 和内部扫描任务数据。卷配置位于 `docker-compose.yaml`，现场确需修改时应记录差异，并在升级后核对。
- 域名、TLS 证书和外部负载均衡属于 Compose 入口之外的现场网络配置，不要只修改 `.env` 后假定已经生效。
- 脚本自动加载 `.tar.xz` 镜像；手动加载时可使用 `xz -dc ... | docker load`。
