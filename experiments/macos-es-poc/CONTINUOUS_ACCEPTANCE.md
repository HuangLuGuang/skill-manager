# macOS 连续只读进程归属验收

验收日期：2026-09-23。GPT-5.6 Sol 子代理实现，主代理独立审查源码、补充负例并执行 sudo 实机验收。

结论：**本阶段 PoC 验收通过**。已验证启动前存在的受控进程通过快照候选接入 ES 归属，以及父退出后的子进程 exec/exit 继承。结果仅用于只读观察，没有接入 AUTH 阻断表。

## 实现范围

- 独立 `es-continuous-observer`，仅订阅 NOTIFY fork/exec/exit。
- 先订阅，再采集 libproc 快照；回调复制必要字段到 8192 条有界队列，按到达顺序消费。
- 快照候选使用 PID、启动时间、完整路径；候选最终读取之后生成的 ES fork，须同时匹配候选身份和真实 parent audit token 才能确认归属。
- 每个观察器启动独立状态；ES 实例身份使用 PID、pidversion、fork start time。exec 迁移身份，父退出保留仍存活后代。
- 序列缺口、重复、乱序、身份字段缺失、路径截断和容量耗尽使现有归属与候选失效。健康状态保持 degraded，后续独立 exec 可建立新归属。
- 路径匹配代表组件分类；未做代码签名认证。会话、轮次、工具语义仍为 unknown。

## 实机结果

环境：本机 macOS 27.0 / arm64，CLT SDK 27；沿用已关闭 SIP 的测试环境，以 ad-hoc entitlement 签名运行。未修改系统隐私设置，未安装常驻服务或扩展。

完整运行命令：

```sh
make adhoc-sign
sudo ./run-continuous-observation-test.sh
```

最终原始目录：`/private/tmp/macos-es-continuous.aBZCAG`。
归档：`evidence/2026-09-23-continuous/lifecycle/`；独立核验摘要：`evidence/2026-09-23-continuous/review.json`。

| 验收项 | 结果 |
| --- | --- |
| 启动前已有受控 fixture | PID 32611，快照候选 1 个，后续 fork 桥接 root 1 |
| 父退出后的后代归属 | 子 PID 32620，fork → 父 exit → 子 exec `/bin/sleep` → 子 exit；完整身份迁移及 root 1 一致 |
| Claude Code 原生 CLI | 2.1.220，仅 `--version`；PID 32621，root 2，exec/exit 身份一致 |
| Codex 原生 CLI | 0.132.0，仅 `--version`；PID 32661，root 3，exec/exit 身份一致 |
| ES 可见事件连续性 | 649 条，global sequence 0–648；每类 sequence 连续；gaps=0、overflow=0、epoch=0 |
| 快照覆盖 | partial；1 次读取失败，0 次身份变化；未推断失败具体原因 |
| 清理 | 四个测试 PID 及 fixture/observer 均无残留；未向现有 Agent 会话发信号 |

首次实机采集得到完整链路，但验收器误将 sleep 路径写为 `/usr/bin/sleep`。依据实际 `/bin/sleep` 证据修正后，重跑完整驱动通过；最终验收器又补充了错误 root identity 和快照前 fork 的拒绝检查，并对最终归档重新验证通过。

## 启动竞态与负例

主代理另以 8 个工作线程运行总计 400 次 `/usr/bin/true`，在活动期间启动观察器。归档：`evidence/2026-09-23-continuous/startup-race/`。

- 观察到 1099 条连续事件，其中 10 条在快照采集窗口内生成；ES 流 gaps=0、overflow=0。
- 这些事件在快照结束后送达，`replay=true` 为 0。**本次没有实机覆盖快照结束时内存队列已经有待回放事件的情况**，不能把晚到事件测试等同于实际缓冲回放测试。
- 快照部分覆盖：7 次读取失败，未伪报完整快照。

本地验证：

```sh
make all
./build/test-attribution
./build/test-continuous-state
/usr/bin/python3 -B -m unittest discover -p 'test_*.py'
```

两套 C 状态测试通过；实验目录 Python **37/37** 通过。覆盖 0 起始序列、时间窗口、PID/pidversion/start time 重用、候选 EXIT/EXEC 失效、父退出、exec 迁移、缺字段、父身份不符、序列缺口/重复/乱序、路径截断、4096 项容量耗尽、重启空状态，以及证据链断裂和错误 root 的拒绝。buffer overflow 的状态清空使用直接注入降级原因验证，并非实际灌满 ES 环形队列。

原有 `es_monitor.m`、`attribution.c/h`、`run-test.sh`、`run-agent-test.sh` 的 SHA256 与此前 AUTH 实机验收归档一致。本次未重复触发 Agent 模型请求或文件阻断测试。

平台全量回归不在本次范围：一次误从仓库根目录使用系统 Python 的 discovery 因缺少 FastAPI、SQLAlchemy、pytest 等依赖导入失败；随后在实验目录执行了上述 37 项有效测试。该导入失败不作为平台功能通过或失败的结论。

## 边界与下一步

这是 macOS 本地 PoC。现有静默进程仍可能仅为候选；启动前已经存在的后代不会凭 PPID 自动升级为 ES 确认。实际 Agent 的快照后 fork 桥接由可控 fixture 验证，两款真实 CLI 验证的是新启动 exec/exit；未让用户已有会话主动执行任务。

ES complete 仅表示当前订阅可见流连续，保留系统默认 mute，不代表全系统无遗漏。实际内核丢事件、队列饱和、缓冲回放、慢日志输出、长期资源稳定性与正式签名/SIP 开启环境尚待专项验收。Windows/Linux 尚未实现。下一步优先补齐上述故障注入及生命周期测试，再讨论将只读归属接入产品服务。

所有修改留在本地，未提交、推送或部署。
