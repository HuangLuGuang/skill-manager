# P7-12 本机隔离 Compose 与 Worker 韧性证据

> 结论：A7-03 已在本机 ARM64 隔离 Compose 项目中通过。该结果证明 Compose 服务健康以及 Worker
> 中断、租约恢复、升级和明确回滚流程可执行；它不是银行验收环境证据，也不替代 x86_64/ARM64
> 正式完整离线包安装。

## 环境与隔离边界

- 日期：2026-08-30
- 架构：ARM64
- Compose 项目：`agent-security-p712-local`
- 独立资源：专用网络及四个以 `agent-security-p712-local_` 开头的数据卷
- 现有项目保护：未启动、修改或复用原 `skill-manager-*` 容器及数据卷
- Backend：从当前工作树构建，镜像
  `sha256:4666f8e894fffa47992003abbd8f86d55f4e7ce12b9e753f6f8672147df77b4d`
- 初始 Worker：已保留旧版 ARM64 镜像
  `sha256:4470db72284d205c6561c7fbe55e49dbd4e8a6d97a1012f21e1cc8bdd724c055`
- 升级 Worker：P7 ARM64 镜像
  `sha256:8d1cb1bd932bcc0d37cbb8b266faad61290479e60f80e6b12b1f8e911e63381f`
- 测试只使用 `control_plane_validation`，不访问真实 Agent、模型或 MCP Tool。
- 管理 JWT 和 Worker Token 仅在进程内传递；证据只保留 Worker ID 与 Token 前缀。

## 核心服务健康

隔离项目的 Backend、Frontend、Sandbox、Nginx 均进入 `healthy`，Nginx 通过独立项目发布本机
80 端口。Worker 使用非 root、只读根文件系统、无额外 capability 和 Compose 默认资源限制。

Worker `asw_304ec2ca7a55453c977338f430ab4b6f` 启动后：

- 状态：`active`
- Token 前缀：`amsw_8wBbEex`
- 心跳：已登记
- X25519 公钥指纹：
  `3ebbe4f6e9a094c501b3537e5f07842d80dc0f9c51920e771d65b2d3f7938b60`
- 容器健康：`healthy`

验收结束后已吊销该身份并停止 Worker，避免测试凭据继续有效。

## 中断与租约恢复

任务 `asj_ac4956096aee42b087b1495ab798b574` 由上述 Worker 领取后状态为 `running`、`attempt=1`。
停止 Worker 并等待 10 秒租约到期，管理员执行 `POST /api/v1/agent-security/workers/recover`：

```json
{
  "timed_out": 0,
  "retried": 1,
  "failed": 0
}
```

任务随后变为 `pending`，停止原因为 `lease_expired_retry`。重启同一 Worker 后任务再次领取并以
`attempt=2`、`succeeded` 完成。平台没有保留过期租约，也没有把中断时的不完整结果报告为安全。

## 升级验证

只重建 Worker，核心服务未重启：

- 目标标签：`p7-12-local-upgrade`
- 目标镜像：`sha256:8d1cb1bd932b...`
- 新容器：`4c287e20ac94`
- 健康状态：`healthy`
- 回归任务：`asj_168e28e12159458b9e16ea7089e815e3`
- 任务结果：`succeeded`

## 明确回滚验证

Worker 回到已保留的明确旧镜像，核心服务仍未重启：

- 回滚标签：`p7-12-local-base`
- 回滚镜像：`sha256:4470db72284d...`
- 新容器：`2cef51c70c96`
- 健康状态：`healthy`
- 回归任务：`asj_4aa5425913af4ad89d1d32f74396c2b7`
- 任务结果：`succeeded`

## 适用边界

本证据满足 A7-03 的本地 Compose/Worker 韧性验证。以下项目仍未满足：

- 银行环境真实主机部署和业务验收。
- 授权真实 Agent 与外部 Provider 扫描。
- 本次 A7-03 演练当时未覆盖完整双架构离线包；后续 A7-04 已补充 ARM64 原生与 x86_64 模拟
  完整包验证，但正式 tag 在银行两种目标主机的安装仍未执行。
- 银行网络、资源容量、TLS、Secret 管理和变更窗口约束下的重复演练。
