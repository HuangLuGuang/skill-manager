# Docker Deployment

这份文档说明当前项目的容器化结构：

- `frontend`：构建并运行 Vue 前端
- `backend`：运行管理后台和 Agent Manager API
- `sandbox`：独立远程 sandbox 服务
- `nginx`：统一反向代理前后端

## 文件位置

- [docker-compose.yaml](/Users/huangluguang/Desktop/Project/skill-manager/docker-compose.yaml)
- [docker-compose.prod.yaml](/Users/huangluguang/Desktop/Project/skill-manager/docker-compose.prod.yaml)
- [backend/Dockerfile](/Users/huangluguang/Desktop/Project/skill-manager/backend/Dockerfile)
- [web/Dockerfile](/Users/huangluguang/Desktop/Project/skill-manager/web/Dockerfile)
- [services/isolated-sandbox-service/Dockerfile](/Users/huangluguang/Desktop/Project/skill-manager/services/isolated-sandbox-service/Dockerfile)
- [services/isolated-sandbox-service/Dockerfile.nsjail](/Users/huangluguang/Desktop/Project/skill-manager/services/isolated-sandbox-service/Dockerfile.nsjail)
- [deploy/nginx/default.conf](/Users/huangluguang/Desktop/Project/skill-manager/deploy/nginx/default.conf)

## 启动

先准备环境变量文件：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
cp .env.example .env
```

然后启动：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
docker compose up --build
```

或者直接用：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
make up
```

## 本地开发时的 Docker Sandbox

如果你不是用整套 compose 部署，但希望 Agent Manager 的 `docker` sandbox 能本地直接测试带常见依赖的 Python skill，先构建项目自带的运行时镜像：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
make sandbox-runtime-build
```

这会生成：

- `agent-manager-sandbox-runtime:latest`

系统设置里的 `Sandbox 镜像` 默认已经切到这张镜像。它预装了一批常见 Python 库，例如 `requests`、`httpx`、`PyYAML`、`python-frontmatter`、`rich`、`click`。

启动后：

- 浏览器入口：`http://localhost`
- Nginx 代理前端和后端
- 后端 API：通过 `/api/*` 暴露

## 健康检查

compose 里已经为这些服务加了 healthcheck：

- `frontend`
- `backend`
- `sandbox`
- `nginx`

`nginx` 会等待前端和后端健康后再进入稳定状态。

## 当前 compose 默认行为

为了让整套容器在更多机器上能直接起，`sandbox` 服务默认使用：

- `SANDBOX_SERVICE_BACKEND=subprocess`

这意味着：

- 容器编排能直接跑通
- 但这不是最终的强隔离生产模式

## 真正生产环境建议

在 Linux 生产环境里，建议把 sandbox 服务切换成：

```bash
SANDBOX_SERVICE_BACKEND=nsjail
SANDBOX_SERVICE_API_KEY=replace-with-real-secret
```

同时保证镜像或宿主环境里有：

- `nsjail`
- `python3`
- `node`

环境变量模板文件：

- [.env.example](/Users/huangluguang/Desktop/Project/skill-manager/.env.example)

如果你要直接使用生产版 sandbox 镜像，可以这样启动：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
make prod-up
```

或者：

```bash
cd /Users/huangluguang/Desktop/Project/skill-manager
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up --build
```

这个覆盖文件会把 `sandbox` 服务切到：

- [services/isolated-sandbox-service/Dockerfile.nsjail](/Users/huangluguang/Desktop/Project/skill-manager/services/isolated-sandbox-service/Dockerfile.nsjail)

## Nginx 代理规则

最外层 `nginx` 负责：

- `/` -> `frontend`
- `/api/` -> `backend`
- `/uploads/` -> `backend`

这样浏览器只需要访问一个入口。

## 数据持久化

compose 里已经给后端挂了这些 volume：

- `backend_data`
- `backend_uploads`
- `backend_sqlite`
- `agent_manager_registry`

分别对应：

- 系统数据目录
- 上传文件
- 管理后台 SQLite，同时保存 Agent Manager registry / review / audit 表
- Agent Manager 工作目录，保留上传目录、scan cache、历史 JSON 迁移源和备份

Agent Manager 现在不再把 `registry.json` 作为主存储。容器启动后会复用 `SQLITE_PATH=/app/runtime/sqlite/admin_starter.db`，并在数据库为空时自动从 `/app/runtime/agent_manager/registry.json`、`review.json`、`audit.jsonl` 迁移旧数据。迁移完成后旧 JSON 文件会保留，后续读写以 SQLite 为准。

## 默认账号

后端启动时会自动创建：

- 用户名：`admin`
- 密码：`Admin@123`

## 说明

当前容器化方案已经适合：

- 本地完整预览
- 演示环境
- 轻量测试环境

如果要进一步用于正式生产，下一步优先建议：

1. 给 `sandbox` 镜像补 `nsjail`
2. 把 `SECRET_KEY`、sandbox API key 等改成外部 secret
3. 收紧 Nginx 和 backend 的 CORS / trusted host
4. 补健康检查和资源限制

## Makefile

项目根目录新增了：

- [Makefile](/Users/huangluguang/Desktop/Project/skill-manager/Makefile)

常用命令：

```bash
make up
make down
make build
make logs
make ps
make restart
make clean
make prod-up
make prod-build
make prod-down
```
