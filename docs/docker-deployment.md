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

## 35 自动发布

GitLab Runner `35-ubuntu` 使用 `agent-manager-release` 标签。推送平台版本标签后，它会在 `10.10.71.35` 上依次完成：

1. 校验 Docker 安装包、桌面客户端发布目录、S3 和 ARM 模拟环境。
2. 构建 x86 镜像，更新 Compose，健康检查通过后发送企业微信通知。
3. 生成 x86 和 ARM 两套离线安装包，并恢复服务器上的 x86 镜像标签。
4. 上传两套安装包到 `s3://condi/agent-manager/`，完成后再次通知。

```bash
git tag v1.0.1
git push origin v1.0.1
```

发布产物保存在：

```text
/home/ubuntu/releases/agent-manager_v1.0.1_arm.tar.gz
/home/ubuntu/releases/agent-manager_v1.0.1_x86.tar.gz
```

如需企业微信通知，在 GitLab 项目的 `Settings → CI/CD → Variables` 中添加掩码变量 `WECHAT_WEBHOOK_URL`。只有在 `v*` 发布标签已配置为 Protected tag 时才同时勾选 Protected，否则标签流水线读不到该变量。流水线只在 `v数字.数字.数字` 格式的平台版本上运行；`client-vYY.MM.DD` 仍由 GitHub Actions 构建并同步桌面客户端。

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
