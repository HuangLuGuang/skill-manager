# Remote Sandbox Mock Quick Start

这份文档用于快速联调 Agent Manager 的 `remote` sandbox 模式。

## 1. 启动 mock sandbox 服务

```bash
cd /Users/huangluguang/Desktop/Project/agent-manager/demo/remote-sandbox-mock
uv sync
uv run uvicorn app:app --host 0.0.0.0 --port 8194 --reload
```

健康检查：

- `http://127.0.0.1:8194/health`

## 2. 启动 Agent Manager

如果你用集成后台：

```bash
cd /Users/huangluguang/Desktop/Project/agent-manager
UV_CACHE_DIR=/tmp/uv-cache uv run --project backend uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

## 3. 在系统设置页切换 Sandbox 后端

打开系统设置，把 Sandbox 配置改成：

- 后端类型：`remote`
- 远程 Sandbox URL：`http://127.0.0.1:8194`

保存后，状态区应显示：

- `Sandbox 后端: remote`

## 4. 提交一个带脚本的 skill

推荐直接测试：

- 正常 skill
- 恶意 skill

例如：

- `/Users/huangluguang/Desktop/Project/agent-manager/tests/skills/exfiltrator.zip`

如果该 skill 触发了 sandbox，你在详情页应该能看到：

- `运行时: remote`
- `Sandbox 说明`
- `stdout / stderr`

mock 服务会根据脚本内容模拟输出：

- 含 `requests.post` 或 URL：stderr 加网络访问提示
- 含 `eval(` / `exec(`：stderr 加动态执行提示

## 5. 结果验证

详情页里关注这些字段：

- `Sandbox 执行结果`
- `Probe 策略`
- `退出码`
- `stdout`
- `stderr`

原始报告 JSON 中应包含：

```json
"sandbox_analysis": {
  "runtime": "remote"
}
```

## 6. 用完后切回 Docker

如果你想恢复本机 Docker probe：

- 系统设置 -> Sandbox 配置 -> 后端类型改回 `docker`

或者设置环境变量：

```bash
export AGENT_MANAGER_SANDBOX_RUNTIME=docker
```
