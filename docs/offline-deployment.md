# 离线部署现场实施指南

## 部署前检查

先用实际部署的普通用户检查 Docker 和 Compose：

```bash
docker --version
docker info
docker compose version
```

检查通过后进入[快速部署](#快速部署)；未安装时先解压应用包，再执行第 2 步安装 Docker。已有安装升级请直接看[升级步骤](#使用安装包升级)。
使用独立 `docker-compose` 时，将文中 `docker compose` 替换为该命令。

| 项目 | 要求 |
| --- | --- |
| 服务器资源 | 生产规划起点：16 vCPU、32 GiB 内存、500 GiB 可用 SSD/NVMe；按实际数据量调整 |
| 安装包 | 架构与服务器匹配，版本和架构见包内 `release-provenance.json` |
| 主机工具 | Bash、GNU tar/coreutils（含 timeout）、flock、gzip、awk |
| Docker | 服务已启动，普通部署用户有访问权限 |
| Compose | 支持 `up --wait --wait-timeout`、`config --images` 和 `env_file.required` |

## 快速部署

以下以普通部署用户的 `~/agent-manager` 为安装目录，管理台使用 HTTPS，模型 HTTP 入口可选。

### 1. 解压安装包

将安装包放到普通部署用户的主目录，用 `uname -m` 确认架构：`x86_64` 选择 `_x86` 包，`aarch64` / `arm64` 选择 `_arm` 包。以下版本号替换为实际交付版本：

```bash
cd ~
tar -xzf agent-manager_1.0.6_x86.tar.gz
cd ~/agent-manager
```

### 2. 安装 Docker（未安装时）

Docker 和 Compose 已检查通过时，跳到第 3 步。

安装 Docker 需要 root 权限：使用有 sudo 权限的账号执行下列命令；已登录 root 时省略 `sudo`。
切换到 root 后，先进入普通部署用户的安装目录（例如 `/home/agentlcm/agent-manager`），不要使用 root 的 `~`。

在当前安装目录执行。先用 `df -h` 选择空间充足的磁盘，将命令中的 `--data-root` 改为该磁盘上的目录：

```bash
tar -xzf installers/docker-installer-28.5.2-x86-arm.tar.gz
cd docker-installer
df -h
sudo ./install.sh --arch x86 --data-root /data/docker --with-compose
cd ..
```

上述命令用于 x86 服务器；其他架构按安装程序的 `--help` 选择参数。

#### 普通用户验证

安装完成后，以普通部署用户重新登录（root 会话先退出），回到安装目录，不加 `sudo` 验证：

```bash
cd ~/agent-manager
whoami
docker --version
docker info
docker compose version
```

如提示 Docker 权限不足，由管理员执行（将 `实际部署用户名` 替换为真实账号），再重新登录验证：

```bash
sudo usermod -aG docker 实际部署用户名
```

### 3. 配置安装目录的 .env

```bash
cp .env.example .env
vi .env
```

正式生产环境在本步骤按[生产配置要求](docker-deployment.md#生产部署)设置凭据；离线包仍使用第 4 步启动。

将实际访问域名或 IP 写入 `TLS_HOSTS`，不带协议或端口，例如：

```dotenv
TLS_HOSTS=localhost,127.0.0.1,10.10.71.35
```

<a id="模型专用-http-入口"></a>

#### 模型专用 HTTP 入口（可选）

需要让第三方 Agent 通过 HTTP 调用模型网关时，在同一个 `.env` 中设置：

```dotenv
MODEL_GATEWAY_HTTP_ENABLED=true
MODEL_GATEWAY_HTTP_PORT=8000
MODEL_GATEWAY_PUBLIC_URL=http://10.10.71.35:8000
```

将示例 IP 替换为实际服务器地址，模型公开根地址不带 `/v1` 或其他路径。
HTTP 明文传输凭证和模型内容，8000 端口应只允许客户批准的内网来源访问。
自定义端口和入口变更见[模型入口运维](#模型入口运维)。

### 4. 启动服务

放通 TCP 443、80；启用模型 HTTP 入口时再放通 8000。保存 `.env` 后执行：

```bash
./start.sh --https
```

等待脚本提示启动成功。
若管理台也使用 HTTP，改用 `./start.sh --http`，管理地址为 `http://<服务器IP>`。

### 5. 登录并验证

保持使用普通部署用户，在安装目录执行：

```bash
docker info
docker compose version
docker compose ps
```

确认服务正常后，访问管理台：

| 用途 | 默认 HTTPS 地址 | 开启模型 HTTP 入口后 |
| --- | --- | --- |
| 管理台 | `https://10.10.71.35` | `https://10.10.71.35` |
| OpenAI-compatible Base URL | `https://10.10.71.35/v1` | `http://10.10.71.35:8000/v1` |
| Anthropic Base URL | `https://10.10.71.35` | `http://10.10.71.35:8000` |

地址中的 IP 替换为实际服务器地址。第三方 Agent 使用 HTTPS 时需信任证书。

使用 `admin` 登录。如果未指定初始密码，在安装目录执行以下命令获取自动生成的密码：

```bash
docker compose exec backend cat /app/runtime/data/initial-admin-password
```

如果已设置 `INITIAL_ADMIN_PASSWORD`，使用该密码。浏览器证书提示见[HTTPS 自签名证书](#https-自签名证书)。

### 6. 授权与模型接入

1. 在“系统管理 → License 授权”导出申请，交给厂商签发，再导入收到的 `.license` 文件，确认授权有效。详见[License 操作指南](license.md)。
2. 配置模型供应商、模型与调用凭证，使用表中的 Base URL 完成一次 Agent 调用。
3. 使用桌面客户端时，安装支持独立模型地址的新版，应用 Agent 模型配置并核对模型页地址。

## 使用安装包升级

先备份业务数据和签名密钥，再将新安装包上传到服务器。进入原安装目录执行，包路径替换为实际位置：

```bash
cd ~/agent-manager
./upgrade.sh /path/to/agent-manager_1.0.7_x86.tar.gz
# ARM 服务器使用 agent-manager_1.0.7_arm.tar.gz
```

脚本自动解包、备份部署文件并更新服务，保留 `.env`、数据卷和端口配置。完成后检查容器状态，并登录管理台验证模型调用：

```bash
docker compose ps
```

- `backups/` 只备份部署文件，**不包含业务数据和密钥**。
- 使用过自定义 `COMPOSE_PROJECT_NAME` 时，升级继续使用原值；现场修改过的 Compose、Nginx 配置需在升级后核对。
- 升级失败先检查日志；若已执行数据库迁移，仅恢复旧部署文件不能完成回滚。

### 旧版升级脚本的处理

当前脚本会自动使用新包中的升级程序。旧安装如果尚不支持该功能，需先将新包解压到临时目录，再用新脚本更新原安装。

以下仍以原安装目录 `~/agent-manager` 为例，替换实际安装包路径：

```bash
upgrade_tmp=$(mktemp -d)
tar -xzf /path/to/agent-manager_1.0.7_x86.tar.gz -C "$upgrade_tmp"
bash "$upgrade_tmp/agent-manager/upgrade.sh" /path/to/agent-manager_1.0.7_x86.tar.gz --install-dir "$HOME/agent-manager"
```

`--install-dir` 指向原安装目录，不是临时解压目录。请勿将新包直接解压覆盖原安装。

## 常用操作

### 启动与端口

| 操作 | 命令 |
| --- | --- |
| HTTPS 启动 | `./start.sh --https` |
| HTTP 启动 | `./start.sh --http` |
| 自定义 HTTP 端口 | `./start.sh --http --port 8088` |
| 延长启动等待时间 | `./start.sh --https --wait-timeout 600` |
| 查看容器状态 | `docker compose ps` |
| 查看后端日志 | `docker compose logs --tail=100 backend` |
| 查看 Sandbox 日志 | `docker compose logs --tail=100 sandbox` |

`--port` 范围为 1–65535，保存到 `.env` 的 `HTTP_PORT`，后续启动和升级沿用。
HTTPS 固定使用 443，HTTP 端口用于跳转，不能设为 443。直接执行 `./start.sh` 按 HTTP 模式启动。
默认启动等待时间为 300 秒。

### HTTPS 自签名证书

- **更新访问地址**：修改 `.env` 的 `TLS_HOSTS`，执行 `./start.sh --https` 重新签发。
- **浏览器和第三方客户端**：需要信任自签名证书；信任具体叶证书的访问端在重新签发后需更新信任。
- **证书保存**：`tls_certificates` 卷保存证书及私钥，升级时保留。运行期间自动检查和续期，请勿删除该卷。
- **桌面客户端**：新版客户端关闭平台 HTTPS 证书验证，安装后需重启相关进程。连接仍加密，但不验证服务器身份，存在凭证泄露和响应被伪造的风险；不改变浏览器或系统的信任设置。

ARM 和 x86 均在对应现场机器验证：HTTP 返回 308 并跳转到 HTTPS、HTTPS 能登录及调用 API、重启和升级后仍可用。
可用 `curl -I http://<服务器IP>/` 和 `curl -kI https://<服务器IP>/` 检查；`-k` 仅用于连通性检查。

### 模型入口运维

- **修改地址或端口**：同步修改 `MODEL_GATEWAY_HTTP_PORT`、`MODEL_GATEWAY_PUBLIC_URL` 和防火墙配置。端口范围为 1–65535，不能与管理端口冲突；公开根地址不带路径、查询参数或凭证。
- **应用配置**：执行 `./start.sh --https` 或 `./start.sh --http`，然后在新版客户端重新应用 Agent 模型配置并验证调用。现有 Agent 文件不会自动改写。
- **关闭入口**：先将公开地址改为可用的 HTTPS 模型根地址，重启并重新应用 Agent 配置；确认调用正常后，设 `MODEL_GATEWAY_HTTP_ENABLED=false` 并再次启动。公开地址留空时使用客户端的管理连接地址。

修改后优先使用启动脚本应用配置；手动操作见下节。

### 手动 Compose 操作

启用 HTTPS 和模型 HTTP 入口时，手动操作带上对应配置文件。例如停止服务：

```bash
docker compose -f docker-compose.yaml -f docker-compose.https.yaml -f docker-compose.model-gateway.yaml --profile https down
```

按实际配置选择文件：基础 `docker-compose.yaml` 必选；管理台启用 HTTPS 时加 `docker-compose.https.yaml` 和 `--profile https`；启用模型 HTTP 入口时加 `docker-compose.model-gateway.yaml`。保留业务数据时不要加 `-v`。

### 管理员密码

升级沿用已有账号密码，修改 `.env` 不会重置已有账号。改密使用账号菜单或账号管理页面。
自动生成的密码文件不会随改密更新。详见[管理员初始密码与升级](docker-deployment.md#管理员初始密码与升级)。

## 故障处理

| 现象 | 检查或处理 |
| --- | --- |
| Docker 未安装或命令不可用 | 安装 Docker，检查 PATH |
| 无法连接 Docker | 检查 `docker info`、`docker context show`、`DOCKER_HOST` 和服务状态 |
| 无权访问 Docker | 检查账号权限；配置 Docker 用户组后重新登录，rootless 环境检查当前用户的 socket |
| Compose 不可用或配置无法解析 | 检查 Compose 版本及 `.env`、Compose 文件格式 |
| 容器启动失败 | 使用上面的状态和日志命令定位失败服务 |
| `/sbin/docker-init: permission denied` | 检查 `/usr/local/bin/docker-init`；若旧安装导致权限为 0750/0700，由管理员改为 0755；否则检查挂载限制和主机安全策略 |
| 升级失败 | 查看错误、备份路径和容器日志；涉及数据库迁移时，不能只恢复旧 Compose 作为回滚 |

## 交付检查

- [ ] 实际离线环境启动成功，服务健康，管理台可登录。
- [ ] 普通部署用户可执行 `docker info`、`docker compose version` 和 `docker compose ps`。
- [ ] License 有效，模型调用及授权范围内的扫描业务通过。
- [ ] 升级后配置、数据、授权和签名身份保留。
- [ ] 业务数据备份可恢复，包括签名密钥及 `license/state.db`。

共享服务器验收使用独立项目、端口、网络和数据卷，见[隔离验证](docker-deployment.md#隔离验证与已验证范围)。
