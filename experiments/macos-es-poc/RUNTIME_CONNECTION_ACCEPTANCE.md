# macOS 采集服务与客户端连接验收

日期：2026-09-23。GPT-5.6 Sol 实现，主代理独立审查并执行 sudo 实机验收。阶段结论：只读 CLI 连接链路通过；尚未交付桌面页面或正式安装服务。

## 当前实现

- 现有 `agent-manager-client runtime-watch` 提供连接入口，普通用户运行，在平台配置、数据库和诊断初始化之前分发。
- 手动启动的 Python relay 负责启动原生 ES observer，通过本地 Unix socket 发送协议版本 1 的逐行 JSON；客户端没有执行命令或修改策略的 IPC 接口。
- 双向校验 peer UID；socket 限定指定 UID、0600 权限；完整祖先目录要求 root 所有且不可被组/其他用户写入，拒绝软链接路径。observer、relay 和诊断文件也位于受保护路径。
- 消息上限 64 KiB，每个消费者队列上限 128 帧，最多 16 个连接；慢消费者断开，不阻塞其他消费者。客户端输出拥塞、断开或短写视为失败。
- 每次连接均输出 `reset=true`；hello 标记 `late_join` 和 `unknown` 基线。CLI 不维护进程树，后续消费者必须按该信号清空连接内归属，不能把当前订阅视为完整历史。
- observer 的可选周期健康输出默认关闭，relay 显式开启；分别表达连接、心跳和事件覆盖。其他平台保留编译兼容，运行时采集返回稳定的不支持错误码。

## 独立实机结果

证据目录：[`evidence/2026-09-23-runtime-connection-160757-42604/`](evidence/2026-09-23-runtime-connection-160757-42604/)，包含驱动报告、客户端 JSONL、两个 relay 和 observer 的诊断输出。

环境沿用本机 macOS、SIP 关闭、ad-hoc ES entitlement 签名。测试仅启动自身受控进程和 `/usr/bin/true`；无模型请求，也未操作已有 Agent 会话。

| 验收项 | 结果 |
| --- | --- |
| 可被其他用户写入的 socket 祖先目录 | 启动被拒绝，无 socket 创建 |
| 非授权 peer | 即使 root 可绕过文件权限，UID 不匹配时也被 relay 拒绝 |
| 普通用户连接 | 实际客户端 UID 501，经 socket 收到健康状态与真实 ES 事件 |
| 真实探针生命周期 | EXEC/EXIT 的 PID、pidversion、start time 与 root 身份一致 |
| observer 暂停 | 对本次 observer 发送 SIGSTOP 后，客户端报告 stale |
| observer 恢复 | SIGCONT 后恢复 healthy |
| relay 停止、重启 | 客户端 offline/reset 后自动重连，接收到不同 monitor_session，基线仍为 unknown |
| 客户端取消 | 退出码 0 |
| 清理 | 客户端、relay、observer/writer 进程组无残留；临时受保护部署目录已删除 |

客户端输出 41 条记录：8 条本地状态、33 条服务端帧（2 个 hello、5 个 status、26 个 event）。第一观察会话采集 237 条事件，241 条日志（含快照及心跳）全部确认写入；第二会话 2 条日志全部确认写入。两次 SUMMARY 的 gap、overflow、event_discarded、log_unconfirmed、log_dropped、log_errors、remaining 均为 0。客户端为晚加入订阅，其帧数不等于采集器总事件数。

两个 monitor_session 分别为 `7B0C40BF-1887-41EE-8B3D-84FF3EF0B2B3` 和 `2A3DB6A2-1AE6-4CEC-8385-2CA39E419119`。

## 回归与构建

- runtimeobservation 的 7 项 Go 测试在 race 模式通过，包括满管道有界失败、协议版本/长度、序列、会话变化、取消、短写和心跳缺失处理。
- 现有 agent-manager-client 与 managedclient 的 race 回归通过。managedclient 全量耗时约 61 秒；第一次统一设置 30 秒预算导致总时限耗尽，调整到 180 秒后通过，未修改该模块代码。
- 实验目录 C 回归与 49 项 Python 测试通过；其中新增 relay 用例实际验证满队列隔离及约 1 秒 drain 超时。
- 子代理完成 Linux/amd64、Windows/amd64 的 runtime 包与现有客户端测试二进制交叉编译；不是跨平台功能实测。
- 原 AUTH 源码与控制测试入口保持不变，未修改桌面 UI，未新增 UI 单元测试。

审查中实际复现并修复了 Go `File.Fd()` 将管道恢复为阻塞模式的问题。最终实现仅获取一次描述符，使用该描述符进行非阻塞写；输出失败后退出，不再向已部分写入的 JSON 帧追加状态记录。

## 能力边界

这是手动部署的开发链路，未安装 launchd，未启用阻断，未接入桌面页面、数据库事件历史或平台上传。指定用户获授权读取全机进程元数据，目前没有按进程 UID 过滤。目录 owner/mode 检查不替代正式产品的签名身份校验、安装器及完整权限审计。

此前 30 分钟稳定性结论对应当时的观察器构建。本次新增可选心跳与 relay 后完成的是上述连接、故障和回归验收，没有重新进行 30 分钟整链路性能测试。后续上线前应验证正式签名、SIP 开启环境和服务生命周期。

本阶段未提交、推送或部署到客户环境。下一阶段可实现客户端事件消费状态与桌面进程/健康视图，并按 reset、late_join 和 coverage 语义展示结果。
