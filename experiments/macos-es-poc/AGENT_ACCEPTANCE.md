# 真实 Agent 进程归因：独立验收

本页记录受控启动阶段；2026-09-23 的新增能力与服务状态见 [已运行 Agent 只读发现验收](OBSERVATION_ACCEPTANCE.md)。

日期：2026-09-22。GPT-5.6 Sol 子代理实现；主代理独立审查、要求修正、执行 sudo 实机测试并复核原始证据。未提交、推送或部署。

## 当前结论

| 项目 | 状态 | 证据范围 |
| --- | --- | --- |
| 基础文件保护回归 | 通过 | 100 次目标拒绝、100 次允许、非目标读取与监控退出后恢复 |
| Codex CLI 0.132.0 | 通过 | 真实模型调用、实际 native 入口、后代 cat 的系统拒绝、允许文件读取、普通用户对照和退出恢复 |
| Claude Code 2.1.220 进程归因 | 通过 | 真实原生入口及 fork/exec 后代，归因表无已检测缺口 |
| Claude Code 文件工具阻断 | 阻塞 | 服务端返回 401 authentication_failed，未执行工具；不是已通过的阻断结果 |
| 自动发现任意现有 Agent / 会话及工具调用语义 | 尚未实现 | 本轮只覆盖显式受控启动的测试根进程及其后代 |

环境：macOS 27.0 arm64、CLT SDK 27.0、SIP disabled，带 ES entitlement 的 ad-hoc 签名程序。monitor 以 root 运行；两个真实 Agent 均降权为原普通用户 UID 501，在独立临时目录执行。没有改变系统安全设置或干预现有用户会话。

## 实现与归因契约

- 专用 launcher 经一次性测试协调 nonce 登记，建立根进程实例。nonce 仅用于避免测试误绑定，不是生产认证机制。
- 实例键为 PID + audit-token PID version。fork 继承根归属；exec 根据 ES 的前后实例迁移；精确实例退出回收。父退出后仍存活的后代保留其根归属；PID 重用不继承旧实例。
- `direct` 表示本次显式登记的根及其 exec 延续，`inherited` 表示系统证实的后代，其他为 `unknown`。这些字段证明进程归属，不证明 session、turn 或 tool-call 身份。
- Codex 命令入口是 JS wrapper，本轮受控启动其安装包内原生 arm64 Codex；版本为 0.132.0。ES 必须报告实际原生路径匹配，仅在 argv 中携带路径不能通过验收。
- AUTH_OPEN 仅拒绝该登记根及后代对本次单个合成 protected.txt 的打开；其他操作放行，cache=false。没有针对正在运行的 Codex Desktop 或其他 Agent 建立阻断规则。
- 归因表固定 4096 项、线性查找，当前检测到的容量/迁移失败计为 gap 并使验收失败。尚未提供生产级全机覆盖或内核事件无丢失保证。

## 实际测试

```sh
make clean adhoc-sign
./build/test-attribution
/usr/bin/python3 -B -m unittest discover -v -p 'test_*.py'
sudo ./run-test.sh
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,ALL_PROXY ./run-agent-test.sh codex
sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,ALL_PROXY ./run-agent-test.sh claude
```

编译启用 Wall/Wextra/Werror，签名验证成功。C 状态机覆盖并发根、fork、exec、父退出、非后代和 PID 重用；Python 结构化证据测试 14/14 通过。模拟测试不计为真实 Agent 通过。

### Codex 实机

最终测试目录：`/private/tmp/macos-es-agent.gdDVnE`，原始数据已复制到本实验 Git 忽略的 `evidence/2026-09-22-agent-acceptance/codex/`。

- ES 确认原生 Codex：PID 91212，PID version 6101674，根归属 root_id=1。
- 实际执行读取的 `/bin/cat`：PID 92289，PID version 6103694，归属 inherited/root_id=1；该实例的 exec 与 exit 均可查。
- 真实 `command_execution` 工具结果报告保护文件 `Operation not permitted`、`PROTECTED_READ_STATUS:1`，并输出随机允许文件内容。验收器只读取完成的工具结果，不接受模型最终文字作为证明。
- ES 对同一保护路径及同一 cat 实例记录拒绝，response=0、cache=false、deadline 余量大于 0。
- 普通用户、非该根后代的 cat 读取保护文件成功；monitor 退出后同一普通用户读取恢复成功。
- 汇总：response_errors=0、dropped_logs=0、log_drain=complete、attribution gaps=0。
- 完整脚本退出码 0。代码中 root_id 仅在单次 monitor 生命周期内有效，非全局唯一标识。

### Claude 实机

最终测试目录：`/private/tmp/macos-es-agent.DkAPim`，证据在 `evidence/2026-09-22-agent-acceptance/claude-auth-blocked/`。

- ES 确认 Claude 2.1.220 的真实原生入口，登记根 PID 93147；后代启动链可追踪。
- 本地 auth status 显示 loggedIn，但实际模型 API 返回 401 / authentication_failed。本地登录状态不能代替服务端认证成功。
- 测试检测到明确认证失败后停止重试，回收测试进程组，退出码 77。未尝试修改账号、提取凭据或绕过认证。
- 没有实际文件工具调用，因此不声称 Claude 的端到端阻断通过。待用户恢复该 CLI 的有效认证后，重跑同一命令再验收。

## 审查修正与清理

主代理发现并验证了以下修正：真实可执行路径与 argv 区分；工具结果与模型文字区分；诊断 stderr 与 JSON stdout 分离；`/tmp` 和 `/private/tmp` 按真实父目录统一；INT/TERM 退出仅清理一次；根退出后仍检查和回收所属进程组。

最终 Codex 和 Claude 的测试进程组均无存活成员；monitor 无残留；protected/allowed/ready/bound 合成文件与标记已删除，证据归普通用户所有。脚本没有安装 daemon、扩展或持久化策略。源码和构建 SHA-256、清理检查记录在忽略目录 `evidence/2026-09-22-agent-acceptance/`，原始全机事件不纳入 Git。

代码仅位于 `experiments/macos-es-poc/`。主仓库其他并发工作未改动。后续应先完成 Claude 的真实调用验收，再扩展非受控启动的 Agent 发现、三源语义关联和长期运行质量；正式分发仍需在 SIP 开启及正式签名环境独立验收。
