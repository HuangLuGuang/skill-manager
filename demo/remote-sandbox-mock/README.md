# Remote Sandbox Mock

这是一个本地 mock 的远程 sandbox 服务，用来联调 Agent Manager 的 `remote` sandbox 后端。

它不提供真正的隔离执行，只是模拟独立执行服务的协议，方便你先验证：

- 系统设置里的 `remote` sandbox 配置
- Agent Manager 提交 skill 时走远程 probe
- 详情页展示 `Sandbox 执行结果`

## 启动

```bash
cd /Users/huangluguang/Desktop/Project/agent-manager/demo/remote-sandbox-mock
uv sync
uv run uvicorn app:app --host 0.0.0.0 --port 8194 --reload
```

默认地址：

- `http://127.0.0.1:8194`

## 配置 Agent Manager

在系统设置页把 Sandbox 配置改成：

- 后端类型：`remote`
- 远程 Sandbox URL：`http://127.0.0.1:8194`

也可以用环境变量：

```bash
export AGENT_MANAGER_SANDBOX_RUNTIME=remote
export AGENT_MANAGER_SANDBOX_URL=http://127.0.0.1:8194
```

## 协议

请求：

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

返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "stdout": "mock sandbox executed",
    "stderr": "",
    "exit_code": 0,
    "duration_ms": 10
  }
}
```

## 模拟行为

为了便于联调，mock 服务会根据代码内容返回不同结果：

- 包含 `requests.post` / `http://` / `https://`
  - stderr 里写网络访问提示
- 包含 `eval(` / `exec(`
  - stderr 里写动态执行提示
- `metadata.args` 包含 `--help`
  - stdout 返回 help 风格文本

这样你可以直接拿恶意 skill 和正常 skill 做对照测试。
