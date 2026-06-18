# Isolated Sandbox Service

这是 Agent Manager 的生产版远程 sandbox 服务基线实现。

它不是 mock，而是一个独立的 HTTP 服务，负责执行：

- 接收代码执行请求
- 在受限环境中运行代码
- 返回 stdout / stderr / exit code / duration

当前实现支持两种后端：

- `nsjail`
  - 面向 Linux 生产环境
  - 需要宿主机安装 `nsjail`
- `subprocess`
  - 面向本地开发和回退调试
  - 不提供强隔离

## 预装依赖

为了让内网环境下的 skill 测试更稳定，sandbox 镜像里默认预装了一批常见 Python 库：

- `requests`
- `httpx`
- `numpy`
- `pandas`
- `PyYAML`
- `python-frontmatter`
- `rich`
- `click`
- `duckduckgo-search`

这意味着很多常见的 Python skill 在测试时不需要临时联网下载依赖。

如果你修改了镜像依赖，需要重建 sandbox 容器：

```bash
cd /Users/huangluguang/Desktop/Project/agent-manager
docker compose build sandbox
docker compose up -d sandbox
```

## 启动

```bash
cd /Users/huangluguang/Desktop/Project/agent-manager/services/isolated-sandbox-service
uv sync
uv run uvicorn app:app --host 0.0.0.0 --port 8194 --reload
```

本地调试时请优先用 `uv run uvicorn ...` 启动。服务会默认使用当前进程的 Python 解释器执行 Python 代码，这样 `uv sync` 安装的常见依赖也能被 sandbox 子进程直接使用。

## 健康检查

```bash
curl http://127.0.0.1:8194/health
```

返回示例：

```json
{
  "status": "ok",
  "service": "isolated-sandbox-service",
  "backend": "nsjail",
  "available": true
}
```

## 请求协议

`POST /run-code`

```json
{
  "language": "python3",
  "code": "print('hello')",
  "preload": "",
  "enable_network": false,
  "metadata": {
    "entrypoint": "scripts/run.py",
    "args": ["--help"]
  }
}
```

## 返回协议

```json
{
  "code": 0,
  "message": "executed by nsjail backend",
  "data": {
    "stdout": "hello\n",
    "stderr": "",
    "exit_code": 0,
    "duration_ms": 14,
    "message": "executed by nsjail backend",
    "backend": "nsjail"
  }
}
```

## 生产环境建议

### 1. Linux 宿主机

建议运行在 Linux 上，并安装：

- `nsjail`
- `python3`
- `node`

### 2. 默认使用 nsjail

```bash
export SANDBOX_SERVICE_BACKEND=nsjail
export SANDBOX_SERVICE_NSJAIL_BIN=/usr/sbin/nsjail
export SANDBOX_SERVICE_DEFAULT_TIMEOUT_SECONDS=15
export SANDBOX_SERVICE_MEMORY_LIMIT_MB=256
export SANDBOX_SERVICE_CPU_LIMIT_SECONDS=10
```

### 3. 配置 API Key

```bash
export SANDBOX_SERVICE_API_KEY=change-me
```

然后在 Agent Manager 的系统设置页或环境变量里配置：

```bash
export AGENT_MANAGER_SANDBOX_RUNTIME=remote
export AGENT_MANAGER_SANDBOX_URL=http://sandbox-service:8194
export AGENT_MANAGER_SANDBOX_API_KEY=change-me
```

### 4. 本地开发回退

如果你只是本地联调服务协议，可以切换成：

```bash
export SANDBOX_SERVICE_BACKEND=subprocess
```

注意：

- `subprocess` 只用于开发
- 生产环境不要用它替代强隔离

## 当前边界

这版已经是“生产服务基线”，但还不是最终强化版。

当前还缺：

- 更严格的 nsjail 参数和自定义 seccomp 配置
- request id / trace id
- 审计日志持久化
- 并发队列和限流
- 多语言依赖镜像管理
- 更细的网络白名单

## 与 Agent Manager 的关系

这项服务只负责“执行”。

Agent Manager 仍然负责：

- 扫描
- 风险分级
- 审批
- 签名
- 部署
- 运行时治理

也就是说：

- Agent Manager 是控制面
- Isolated Sandbox Service 是执行面
