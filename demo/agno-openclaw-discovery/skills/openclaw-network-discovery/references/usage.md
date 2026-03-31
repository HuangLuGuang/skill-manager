# OpenClaw 扫描技能参考

## 支持的目标格式

- 单个 IP：`192.168.1.10`
- 单个带端口 IP：`192.168.1.10:18789`
- CIDR：`192.168.1.0/24`
- IP 范围：`192.168.1.10-192.168.1.20`
- 私网 URL：`http://192.168.1.10:18789`

## 识别特征

- 页面标题包含 `openclaw`
- 响应正文包含 `openclaw`、`open-claw`、`/api/v1/claw`
- 响应头包含 `openclaw` 或 `claw`
- API Endpoint：
  - `/api/version`
  - `/api/health`
  - `/api/v1/status`

## 推荐命令

```bash
python discover_openclaw.py --target 192.168.1.10 --port 18789
python discover_openclaw.py --target 192.168.1.0/24 --port 18789 --concurrency 50
```

## 风险提示

- 这个技能只适合内网使用
- 默认限制为私网地址
- 不建议在生产高峰期对大网段使用过高并发
