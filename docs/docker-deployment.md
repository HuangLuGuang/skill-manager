# Docker 部署

以下命令都在当前项目根目录执行。

## 在线部署

```bash
cp .env.example .env
./.build.sh --all
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
./.build.sh --help

# 构建全部镜像，默认 tag 是 latest
./.build.sh --all

# 指定 tag
./.build.sh --tag v1.0.0 --all

# 指定平台
./.build.sh --platform linux/amd64 --tag v1.0.0 --all
./.build.sh --platform linux/arm64 --tag v1.0.0 --all
```

会生成这些镜像：

- `agent-manager-backend:<tag>`
- `agent-manager-frontend:<tag>`
- `agent-manager-sandbox:<tag>`
- `agent-manager-sandbox-runtime:<tag>`

## 离线部署

在有网络的机器上构建并保存镜像：

```bash
./.build.sh --tag v1.0.0 --all --save
```

生成的镜像包：

```text
docker_images/x86/agent-manager-images-v1.0.0.tar
```

ARM 平台是：

```text
docker_images/arm/agent-manager-images-v1.0.0.tar
```

把这些文件拷贝到目标机器的项目目录：

- `docker-compose.yaml`
- `deploy/nginx/default.conf`
- `.env`
- `docker_images/x86/agent-manager-images-v1.0.0.tar`

在目标机器加载镜像并启动：

```bash
docker load -i docker_images/x86/agent-manager-images-v1.0.0.tar
TAG=v1.0.0 docker compose up -d
docker compose ps
```

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
