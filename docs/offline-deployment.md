# 离线部署现场实施指南

本文档用于现场实施人员在客户内网环境快速部署 Agent Manager。

## 交付物

现场至少需要拿到一个安装包：

```text
agent-manager_v1.0.0_arm.tar.gz    # ARM 服务器
agent-manager_v1.0.0_x86.tar.gz    # x86 服务器
```

安装包内通常包含：

```text
docker-compose.yml
.env.example
docker_images/<arch>/agent-manager-images-v1.0.0.tar.xz
installers/docker-installer-28.5.2-x86-arm.tar.gz
```

## 部署前检查

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

如果现场没有 Docker，先从安装包内的 `installers/docker-installer-28.5.2-x86-arm.tar.gz` 按客户环境安装 Docker。

## ARM 快速启动

```bash
tar -xzf agent-manager_v1.0.0_arm.tar.gz
cd agent-manager

xz -dc docker_images/arm/agent-manager-images-v1.0.0.tar.xz | docker load

cp .env.example .env
TAG=v1.0.0 docker compose up -d
docker compose ps
```

## x86 快速启动

```bash
tar -xzf agent-manager_v1.0.0_x86.tar.gz
cd agent-manager

xz -dc docker_images/x86/agent-manager-images-v1.0.0.tar.xz | docker load

cp .env.example .env
TAG=v1.0.0 docker compose up -d
docker compose ps
```

## 启动验证

查看容器状态：

```bash
docker compose ps
```

所有核心服务应为 `running` 或 `healthy`。

查看日志：

```bash
docker compose logs -f
docker compose logs -f backend
```

浏览器访问：

```text
http://<服务器IP>
```

默认账号：

```text
用户名：默认 admin
密码：部署前在 `.env` 中设置的 `INITIAL_ADMIN_PASSWORD`
```

## 常用运维命令

停止服务：

```bash
docker compose down
```

重新启动：

```bash
TAG=v1.0.0 docker compose up -d
```

查看后端日志：

```bash
docker compose logs -f backend
```

查看 Sandbox 日志：

```bash
docker compose logs -f sandbox
```

## 现场注意事项

- `TAG` 必须和安装包版本一致，例如 `v1.0.0`。
- ARM 和 x86 安装包不要混用。
- 如果客户现场需要修改端口、数据目录或外部地址，先修改 `.env`，再执行 `docker compose up -d`。
- 镜像文件是 `.tar.xz`，需要用 `xz -dc ... | docker load` 加载。
