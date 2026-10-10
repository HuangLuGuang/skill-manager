# 已运行 Agent 只读发现：独立验收

日期：2026-09-23。GPT-5.6 Sol 子代理实现，主代理审查、修正字段并独立执行测试。本轮未提交、推送或部署。

## 结论与范围

**本机只读发现 PoC 验收通过。** 能识别已安装组件、当前正在运行的 Codex 桌面后端，以及独立启动的真实 Claude Code/Codex CLI。覆盖不完整时准确报告 partial，不把快照关系当作 ES 授权依据。

本轮没有实现任意既有会话的连续 ES 归因，也没有建立 session/turn/tool-call 关联。所有新发现结果都与原有 AUTH 归因表隔离，现有用户会话未被登记为阻断目标。

## 新增能力

| 文件 | 职责 |
| --- | --- |
| `observe_agents.py` | 安装组件目录、签名元数据、libproc 只读快照与覆盖报告 |
| `snapshot_attribution.py` | 精确路径匹配、PID+启动时间身份、可见父子链推断与冲突处理 |
| `src/snapshot_launcher.c` | 暂停启动自己创建的测试子进程，握手后恢复；超时和信号清理 |
| `run_observation_test.py` | 无模型调用的两个真实 CLI 发现测试 |
| `test_snapshot_attribution.py`、`test_process_reader.py`、`test_snapshot_launcher.py` | 身份、采集覆盖、预算、中断和清理回归 |

`catalog_path_match` 只表示可执行路径与当前安装目录匹配，不表示代码签名验证通过。`codesign -d` 的输出属于元数据，记录 `verification=not_performed`。

快照同时复读启动时间、父 PID 和可执行路径，过滤采样中已观察到的变化。直接命中目录的组件标为 snapshot，可见父子链推断为 inferred；链路缺失、冲突或不能读取时保持未知。快照不是原子操作，仍不能排除未观察到的 ABA 变化。

主代理额外修正：推断出的普通后代使用 `component_role=unclassified_descendant`、`root_candidate=false`，根组件类型单独保存在 `root_component_role`，避免把后代误标为新 Agent 根。

## 独立执行与证据

环境：macOS 27.0 arm64。新增观察命令均以普通用户运行，无需 sudo，不读取进程 argv、环境变量、Prompt 或客户文件内容。安装目录中的 plist 和代码签名元数据用于组件识别。

```sh
make all
./build/test-attribution
python3 -B -m unittest discover -v -p 'test_*.py'
python3 -B observe_agents.py
python3 -B run_observation_test.py
```

- C 状态机回归通过；Python **32/32** 测试通过。
- 反例覆盖：同名但不同路径、父 PID 重用为相同 Agent 路径、父进程晚于子进程创建、重复 PID 冲突、多根进程、父退出、身份读取失败、二次进程列表读取失败、时限/分类预算不足、helper 不作为根。
- launcher 真实子进程测试覆盖：启动失败、握手超时、父进程终止、子进程执行超时；均确认子进程已回收。

### 已运行进程快照

最终快照列出 777 个 PID，稳定读取 584 个进程记录，192 个身份读取失败；跳过 PID 0。状态为 **partial**。`identity_unavailable` 不能进一步证明失败是权限不足还是进程退出，报告不臆测原因。

精确命中的实际运行组件：

| 类型 | 数量 | 说明 |
| --- | --- | --- |
| Codex backend | 3 | `/Applications/ChatGPT.app/Contents/Resources/codex`，PID 9662、58990、91770 |
| GUI | 1 | ChatGPT 主程序，仅组件，不作为归属根 |
| helper | 10 | 当前运行的 Renderer/Service 等辅助进程，不作为归属根 |
| tool_host | 1 | codex-code-mode-host，单独识别，不作为归属根 |

上述是采样时的数量，不是静态资产总数。分类预算未耗尽、未发现冲突 PID。已存在的进程只读取元数据，没有发送信号或改变其权限。

### 两个真实 CLI

| 客户端 | 测试进程 PID | 实际版本输出 | 结果 |
| --- | --- | --- | --- |
| Claude Code | 14657 | `2.1.220 (Claude Code)` | 原生入口 snapshot 命中，恢复后 --version 正常退出 |
| Codex CLI | 14659 | `codex-cli 0.132.0` | 原生 backend snapshot 命中，恢复后 --version 正常退出 |

测试由普通用户创建独立的暂停进程，先通过 libproc 确认其可执行路径和启动时间，再恢复执行 `--version`。这两项测试模型请求数为 0，不能用来证明模型工具调用成功。

最终检查未发现这两个 PID、snapshot-launcher 或 ES monitor 残留。

## 基础阻断回归与 Claude 当前阻塞

父代理额外以 sudo 重跑已有基础测试：保护文件 **100/100 拒绝**、允许文件 **100/100 成功**，普通进程对照、监控退出后恢复及清理均通过。

原有 `es_monitor.m`、`attribution.c/h`、`run-test.sh`、`run-agent-test.sh` 的 SHA-256 与上一轮验收时一致。本轮没有改动原有系统控制路径。

Claude 真实模型调用也复查了：本次连续返回 **502 / server_error**，尚未执行文件工具。父代理终止本次隔离测试，退出码 130，测试文件与进程已清理。此前 401 的历史记录仍有效，但本次 502 不能证明认证已恢复，也不能证明仍是同一认证故障；完整 Claude 工具阻断验收继续保留为未通过。

## 证据与下一步

本实验目录下 `evidence/2026-09-23-observation/`（Git 忽略）保存：最终 live-snapshot、real-cli JSON、清理记录、源码/构建指纹、100/100 回归与 Claude 服务失败记录。原始进程信息不纳入提交。

下一步建议实现“启动时快照与后续 ES 通知的安全衔接”：先订阅、缓冲事件，再核对稳定身份建立映射，覆盖快照期间 fork/exec/exit、采集丢失及父退出。只有实测证据足够的关系才升级为系统事件确认的归属；会话和工具语义仍需要插件或日志证据。独立修复/恢复 Claude 服务调用后，再补其完整文件阻断验收。
