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
# x86
./package-release.sh -v v1.0.0 -p linux/amd64 -i /path/to/docker-installer-28.5.2-x86-arm.tar.gz

# ARM
./package-release.sh -v v1.0.0 -p linux/arm64 -i /path/to/docker-installer-28.5.2-x86-arm.tar.gz
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
```

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
