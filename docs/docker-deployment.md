# Docker 部署

以下命令都在当前项目根目录执行。

## 在线部署

```bash
cp .env.example .env
./build.sh --all
docker compose up -d
docker compose ps
```

访问：

```text
http://localhost
```

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
scanner/releases/agent-manager-client-26.03.15-darwin-aarch64.dmg
scanner/releases/agent-manager-client-26.03.15-darwin-x86_64.dmg
scanner/releases/agent-manager-client-26.03.15-windows-x86_64.exe
scanner/releases/agent-manager-client-26.03.15-linux-x86_64.AppImage
```

Docker Compose 已将宿主机 `scanner/releases` 只读挂载到后端。部署完成后，管理员可在“终端管理 → 安装客户端”按系统和版本下载；新增版本只需把新的 release 文件复制到该目录，无需重建镜像。

## 35 自动部署与离线发布

GitLab Runner `35-ubuntu` 使用 `agent-manager-release` 标签，流水线分为两个独立任务：

- `deploy-35`：只构建 x86 镜像、更新 Compose 并执行健康检查。代码合并并推送到 `dev` 时自动执行，镜像版本为 `dev-提交短哈希`。
- `offline-package`：推送正式版本标签时，在快速部署成功后自动生成 x86、ARM 离线包并上传 S3。

```bash
git tag v1.0.1
git push origin v1.0.1
```

标签推送后，35 会先完成快速部署，再自动生成并上传客户离线包。

发布产物保存在：

```text
/home/ubuntu/releases/agent-manager_v1.0.1_arm.tar.gz
/home/ubuntu/releases/agent-manager_v1.0.1_x86.tar.gz
```

如需企业微信通知，在 GitLab 项目的 `Settings → CI/CD → Variables` 中添加掩码变量 `WECHAT_WEBHOOK_URL`。只有在 `v*` 发布标签已配置为 Protected tag 时才同时勾选 Protected，否则标签流水线读不到该变量。正式发布标签使用 `v数字.数字.数字` 格式；`client-vYY.MM.DD` 仍由 GitHub Actions 构建并同步桌面客户端。

35 上 Docker daemon 使用外网代理拉取基础镜像，Backend 的 Debian 与 GitHub 下载分别通过 `BUILD_APT_PROXY`、`BUILD_GIT_PROXY` 使用代理，Python 包通过 `BUILD_PYPI_INDEX` 使用清华源；npm 保持直连。Docker 代理配置位于 `/etc/systemd/system/docker.service.d/http-proxy.conf`；修改后执行 `sudo systemctl daemon-reload && sudo systemctl restart docker`。

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
用户名：admin
密码：Admin@123
```
