# macOS AIDR 执行器

原生组件提供 ES 进程归属、签名策略、文件打开控制和精确实例响应。桌面“运行治理 → 系统采集”按客户端策略选择模式：默认仅审计订阅 fork/exec/exit；拦截额外订阅 AUTH_OPEN 并读取签名进程响应命令。模式变化关闭旧订阅、补传并重新启动；实际原生心跳确认模式，失败显示具体原因。平台入口是“客户端详情 → 行为审计 → 系统事件”。

## 桌面开始与停止

1. 配置客户端设备连接；在平台客户端策略中开启系统通道。在“策略与审批 → 系统采集策略”发布有效的 Agent 根可执行文件归属策略。根必须是有有效代码签名的实际 Mach-O 文件，脚本包装路径不适用。平台服务需要配置 `AIDR_POLICY_SIGNING_KEY_FILE`。
2. 在桌面“运行治理 → 系统采集”点击“开始采集”。先用已有设备凭证读取有效目标、策略版本和公开的 P-256 验签公钥，再通过 macOS 管理员授权部署组件、启动独立 root 管理进程。桌面保持普通用户权限。设备凭证不放进命令参数。
3. 缺少完整磁盘访问权限时，使用页面的系统设置入口，为 `/Library/Application Support/AgentManagerRuntime/system/bin/aidr-enforcer` 授权；“显示组件”定位该文件。管理员密码授权不能替代该权限。授权后重新开始。
4. 页面只有收到真实 ES 订阅后的原生健康记录才显示“采集中”，同时展示最近进程事件、上传 ACK、待发数量和稳定失败码。启动平台策略中的 Agent 后，核对平台实际进程事件。已有进程不会因进程快照自动获得已确认归属。
5. “停止采集”关闭订阅、回收原生子进程，再使用现有严格 ACK 队列做最多 5 秒的收尾上传。未确认记录留在原设备/平台绑定的 root 私有目录，下一次启动继续补传。停止成功与队列排空分别展示。关闭桌面窗口不会停止独立采集；每次最多运行 24 小时。重启机器不会自动启动采集。

安装目录由 root 管理；每个用户通过固定、仅该用户可连接的 Unix socket 查询状态及停止。私有凭证、公钥和队列按平台/设备隔离。安装使用互斥锁，桌面按钮与命令入口均防止重复启动。状态通过正在运行的管理进程读取；旧状态文件不能证明仍在采集。运行时每 10 秒重查平台开关与策略，关闭通道、撤销凭证或策略过期会停止采集。

## 开发与正式发布

开发构建由打包脚本显式设置开发标记；仅在 SIP 已关闭时支持安装。首次安装或源组件内容变化时，在 root 目录暂存组件，完成 ad-hoc 签名，并在原生采集器签名中嵌入 `com.apple.developer.endpoint-security.client=true`。后续开始会核对已安装内容和签名；未变化的组件不重新签名。程序不会修改 SIP 或 TCC 数据库。

正式系统采集组件必须使用 Developer ID、Apple 批准的 ES entitlement，并随产品完成公证。Developer ID 打包目标需要在构建机钥匙串中提供签名身份，由 `APPLE_SIGNING_IDENTITY` 指定；原生资源使用 hardened runtime、时间戳和 ES entitlement 签名。没有正式签名的普通发布包不能通过系统采集安装校验。开发包、本机订阅成功和代码测试均不能代替正式发行验收。

**English:** Open **Runtime governance → System collection** in the desktop. Enable the platform system channel and publish a valid signed Agent executable attribution policy first. Start uses macOS administrator authorization to install/update components and launch an independent root collector; the desktop stays unprivileged. Grant **Full Disk Access** to the installed aidr-enforcer separately. Collection is reported only after a real ES subscription heartbeat. Stop unsubscribes, reaps the native process and performs a bounded final upload; unacknowledged records survive for the next start. Closing the desktop leaves collection running; each run is limited to 24 hours, with no automatic restart after reboot. Development ad-hoc signing occurs only on installation/update with SIP already disabled. Production requires Developer ID, Apple ES approval and notarization.

## 人工验收清单 / Manual acceptance

- [ ] 普通用户打开客户端 → 开始 → 取消管理员授权；显示已取消，未新增 root 采集进程。Cancel authorization: cancelled state and no new collector.
- [ ] 快速重复点击开始，只有一个授权请求、一个管理进程和一个原生订阅。Repeated clicks: a single authorization and collector.
- [ ] 完成管理员授权但未授予 FDA：显示明确权限原因及设置入口，不显示采集中。Missing FDA: actionable error, never Collecting.
- [ ] 授予 FDA 后开始；确认桌面 UID 非 0、管理/原生进程 UID 为 0，且真实订阅后显示采集中。Verify privilege separation and subscription.
- [ ] 策略生效后启动匹配的 Agent，核对桌面最近事件、上传 ACK 和平台同一 monitor/sequence/PID 的进程事件。Match real events end to end.
- [ ] 停止后确认 native 退出、订阅关闭、root 管理进程退出；平台收到停止健康记录，待发数量为 0 或明确保留。Stop, reap and verify queue disposition.
- [ ] 再次开始，确认组件哈希、签名和安装修改时间不变；升级组件才更新签名。Restart without re-signing.
- [ ] 平台短时离线后停止；保留待发记录，再启动后补传。Test offline stop and recovery.
- [ ] 缺失组件、无有效策略、策略过期、平台关闭通道、错误签名分别显示可定位原因。Test start/runtime failures.
- [ ] 中英文、最小窗口、长路径、切页、关闭窗口后返回均可正常操作。Check both locales and window sizes.
- [ ] 正式 Developer ID + ES entitlement + 公证包在 SIP 开启的客户机独立验收。Production acceptance on a SIP-enabled host.

## 构建与运行

网页终止确认使用最近一次有效状态，不因每 5 秒后台刷新而关闭；报告失效、来源身份改变或实例退出仍禁用，服务端独立复核。已验证与未确认超时回执分别显示。

macOS 13+，Apple Command Line Tools：

```sh
make test all
```

开发机已有相应条件时可执行 `make adhoc-sign`。正式分发需要 Apple 授予的 Endpoint Security entitlement、有效签名和相应系统授权；本仓库的开发签名测试不证明普通客户设备可直接安装。此组件是前台有时限进程，不安装 LaunchDaemon 或 System Extension。

后端设置 `AIDR_POLICY_SIGNING_KEY_FILE`，指向后端服务用户拥有且权限为 `0600` 的 P-256 PKCS8 PEM 私钥。管理员通过可信渠道将对应的 65 字节 X9.63 公钥配置到执行器；设备上传凭证不能替代策略签名。私钥不能通过设备 API 下发。密钥由部署方生成和管理，不在源码中提供默认密钥。

将构建的原生执行器、Go `agent-manager-client`、公钥部署在 root 管理的路径，创建 root 拥有的 `0700` 独立状态目录。设备凭证从受保护环境配置读入，包含 `aidr:heartbeat`、`aidr:report-events`，绑定明确设备。以下命令在已加载凭证的管理员 shell 运行，不把凭证明文放入命令参数：

```sh
/absolute/root-managed/agent-manager-client aidr-enforce \
  --native /absolute/root-managed/aidr-enforcer \
  --public-key /absolute/root-managed/policy-public-key \
  --state-dir /absolute/root-managed/runtime-state \
  --server https://platform.example \
  --client-id DEVICE_ID \
  --duration 10m
```

`AGENT_MANAGER_AIDR_TOKEN` 是默认凭证环境变量，可用 `--token-env` 指定另一个环境变量名。无需部门 ID。不要与 P1 的 `aidr-sync` 共用状态目录；单目录只允许一个写入者。策略启动时获取，此后每 10 秒刷新；响应命令每 2 秒获取，事件每秒尝试发送。平台发布版本与执行器报告版本分别显示，不能把发布成功当成已执行。

## 策略与身份

- 最多 32 个 Agent 根映像、128 条规则。路径必须是现有普通文件，应用策略时解析链接并取得设备号/inode；根映像另验证签名并匹配运行时 cdhash。新注册根需在策略应用后启动，已有未知进程不会被猜测为 Agent。
- 根路径填写真正运行的已签名 Mach-O 映像，不是 shell 启动脚本。当前桌面 Codex 的 `codex-cli/bin/codex` 是包装脚本，其真实映像为 `codex-cli/CodexCLI.app/Contents/MacOS/codex`。Universal 二进制逐个验证有界架构切片及摘要，避免默认架构与实际运行架构不同而漏认。
- 进程使用 boot ID、monitor ID、PID、PID version、启动时间识别；执行器保留完整 audit token。fork 继承、exec 更新身份、exit 移除，父退出不清除仍存活的后代。状态最多 4,096 个实例，容量或 ES 序列缺口清空不可信归属并报告缺口。
- 规则匹配规范路径或策略应用时取得的 inode，支持该文件的硬链接/符号链接别名；同一路径替换后的文件仍按路径匹配。替换后在其他路径出现的新 inode 别名需要重新发布策略。不是目录递归、任意文件系统变更或全链路数据防泄漏策略。
- 拒绝优先；未知 Agent 身份和过期策略分别采用显式动作。规则中的 `all` 作用于所有进程，请先在独立测试文件验证。未匹配资源允许。回调不执行磁盘读取、网络请求或人工审批，不启用 ES 授权结果缓存。
- 签名覆盖完整 JSON 字节、设备、版本、期限和规则。新版本落盘 fsync 后原子切换；无效签名/版本冲突保留原策略。规则更新保留未改变根映像的现有归属；移除或改变的根不再保留其范围。回滚发布历史内容的新版本，撤销发布空规则。

## 审计、故障与响应

原生审计缓冲为 1,024 条、单条最多 16 KiB；读端阻塞时不阻塞授权响应，真实审计丢失用 `aidr_enforcement_audit_gap` 和累计缺口报告。Go SQLite 队列最多 100,000 条，数据库页上限约 256 MiB；冻结批次最多 128 条/900 KB，绑定平台和设备。ACK 必须匹配设备、条数和精确上传字节 SHA-256，持久化后才删除已确认记录。既有 P1 事件、游标和冻结队列不修改。

网络不可用时继续执行有效缓存；上传队列保留，网络恢复后补传。缓存到期报告降级并执行 `expired_action`。执行器停止或失效后 ES 控制不再存在；supervisor 确认原生 EOF 后以已有 monitor 健康身份记录 `aidr_enforcement_native_exit` 并尝试上传，平台显示异常退出。没有已观测身份时不伪造健康事件。supervisor 同时失效或断网时，平台以最后一次实际报告时间判断新鲜度（10 秒），页面每 5 秒刷新，不能提供零延迟故障发现保证。停止观察页面不停止原生保护；停止前台 supervisor 会回收其原生子进程。

终止请求以设备、boot、monitor、精确进程实例和请求 UUID 绑定，平台检查可见性和管理员角色。执行器只对自己已确认的实例调用 `proc_signal_with_audittoken(SIGTERM)`，不退回仅按 PID 发送信号。下发、信号已发送、匹配 ES exit 已验证分开记录。请求期限 120 秒；重复请求不重复发送，执行器重启后的 monitor ID 不接受旧实例命令。

AUTH_OPEN 记录证明授权决定和响应状态，不能单独证明应用读取结果。已有打开句柄、mmap、rename/unlink、网络和工具调用强关联不属于此执行点，按后续阶段补充。

## 验收

自动回归：`make test all`、`go test ./internal/aidr/... ./cmd/agent-manager-client`（在 `scanner/`）、`uv run --project backend pytest tests/test_aidr_enforcement.py`。

开发机独立真实 ES 验收：`sudo backend/.venv/bin/python experiments/macos-es-poc/run_p2_native.py`（仓库根）。平台链路脚本 `run_p2_platform.py` 仅针对文档中的隔离测试后台，不能用于日常设备。

实测数据及未验项见 [已有验收记录](../../experiments/macos-es-poc/ACCEPTANCE.md)。界面手验：中英文分别检查目标/实际版本、长路径换行、历史载入与版本冲突、事件翻页、详情、终止确认与回执；普通用户不能发布策略或终止；失效报告不能显示为在线保护。

### 本机验收交接（2026-09-27）

以下入口只用于本轮隔离数据，不是日常后台。浏览器打开 `http://127.0.0.1:41879/login`，测试账号 `aidr-review`；密码在本机私有文件 `/private/tmp/aidr-p1p2-20260927/platform/fixture.json` 的 `password` 字段，验证码为 `aidr`。请在本机查看该文件，不将内容粘贴到报告或截图。进入客户端管理，打开 **AIDR P1 acceptance** 设备详情。

按以下清单各检查一次中文和英文，保存不含凭证的截图；勾选仅表示实际操作完成：

- [ ] **Agent 日志观察 / Agent log observation**：筛选会话 `01a0dfb7-98d5-7672-80eb-da96c40ffd87`，应有 10 个合并操作；依次为创建目录、写文件、读取、修改、读取、重命名、读取、true、exit 7、sleep。明确退出码应为 0、0、0、0、0、0、0、0、7、0。检查命令、目标、详情证据可读，日志证据不显示成 OS 操作证明。
- [ ] 同一入口筛选 `01a0dfdb-108a-7c33-abc0-7e80addf59b4`：应为一个调用及其结果合并成的一条操作，退出码 0。100 次文件读取是该脚本内部行为，不应虚构成 100 次 Agent 工具调用。
- [ ] **macOS 系统防护 / macOS system protection**：检查授权、进程筛选，较早记录/最近记录、详情和响应回执。历史授权应含 deny/responded；受控 sleep 响应有 verified。当前测试执行器已停止，不能仅因存在历史健康记录就显示正在保护。
- [ ] 切换英文，检查长命令、长路径换行，窄窗口、分页按钮、详情滚动和弹窗关闭；再切回中文。对比目标策略版本与实际报告版本，发布成功不等于执行器已经应用。
- [ ] 使用具有设备可见性但非管理员的测试账号检查发布/终止不可用；使用无设备权限的账号检查不能读取该设备。管理员账号成功不能替代此项；未准备这些账号则保留待验。

可在自己的 Terminal 重跑已实现的原生/平台测试，同时在上述页面观察真实到达的数据。先确认没有另一轮脚本占用 41880；不要与其他验收脚本并行运行。仓库根执行：

```sh
cd /Users/huangluguang/Desktop/Project/skill-manager
make -C client/macos-enforcer test all adhoc-sign
(cd scanner && go build -o /tmp/aidr-p2-client ./cmd/agent-manager-client)
sudo backend/.venv/bin/python experiments/macos-es-poc/run_p2_native.py
sudo backend/.venv/bin/python experiments/macos-es-poc/run_p2_platform.py
```

平台脚本需要本轮隔离后台和其私有 fixture/key 文件仍存在；不要把脚本地址改成日常平台。两脚本使用新临时目录和合成文件，不读取业务文件，不安装服务。平台脚本会改变**隔离设备**的测试策略，测试期间不要同时在页面编辑它；完成后保留测试策略及历史证据，停止自己启动的保护进程。原生脚本故意制造审计过载，报告非零审计缺口是该用例的预期降级，不是正常阶段无缺口通过的证据。

预期：脚本退出 0，打印私有 `report.json` 路径；平台报告包含 8 项检查及离线待发恢复。原生报告包含保护读取拒绝、允许读取成功、独立 cat 成功、并发/生命周期、精确终止、过期及过载降级。平台脚本中的异常退出→恢复变化较快，若页面没有实际观察到，不勾选实时降级 UI 验收；报告只证明接口链路。

本轮已完成网页策略发布、撤销、历史恢复、并发版本冲突、精确终止和真实未执行超时。可在上述构建后运行有界交互工具复验：

```sh
sudo backend/.venv/bin/python experiments/macos-es-poc/run_p2_browser.py
```

工具输出独立文件与根路径，发布初始测试策略并等待命令，15 分钟自动结束。进入设备详情的系统防护，等待目标/报告版本一致；网页发布规则后在终端输入 `probe`，检查保护拒绝、允许成功；网页撤销后 `probe` 应成功，载入历史并发布新版本后再次拒绝。`sleep` 输出本轮 PID，页面详情核对完整身份后终止，回执应 verified；`status` 查看独立退出码。`hold` 仅暂停命令下发，再 `sleep` 并从网页终止，等待 120 秒后应显示未确认超时；`release` 后 `status` 应显示它仍存活。`crash` 只对确认属于该 supervisor 的原生子进程发送 SIGKILL，页面应显示异常退出；`finish` 正常停止并回收自有进程。清理后 `report.json` 保留独立结果。不要用 `hold` 的测试代理代替真实服务可用性监控。

该工具会改变隔离设备策略，不与其他 41880 测试并行。测试前策略保存在证据目录 `previous-policy.json`；结束后通过网页载入开始前的历史版本并发布新版本恢复内容（期限重新签发），不直接修改数据库。本轮已恢复为版本 24，执行器已退出。中文版/英文版分别检查长路径、分页、详情、停止禁用和已验证/未确认超时；未准备独立可信密钥及隔离 fixture 时不要将脚本指向日常后台。

Claude、插件对照和正式分发条件尚未完成：恢复可用 Claude 模型后，在 `mktemp -d /private/tmp/aidr-claude-manual.XXXXXX` 创建的独立目录开启新会话，要求逐次工具调用完成写入 alpha、读取、修改为 beta、读取、重命名、再次读取、`/usr/bin/true`、`/bin/sh -c 'exit 7'`。保留会话 ID 和实际调用数；使用现有设备凭证及独立状态目录运行 `aidr-sync`，将 `--claude-root` 限定为该新任务的日志目录（不指定单文件才可用于自动发现验收），Codex 根指定为空的独立目录。逐条对照日志、平台和文件，不把缺少错误标记当作明确退出码。P2 Claude 保护读取还需要在策略生效后启动真实已签名 Claude 根，分别核对拒绝文件、允许文件和独立 Terminal 读取；仅 P1 上传成功不算该项通过。

插件开启对照须记录实际插件名称/版本并与关闭时的同一合成任务对照；正式分发须在具备有效签名、ES entitlement、系统授权和 SIP 开启的独立测试机验证。这些条件不由本机 ad-hoc 测试代替，不要求为复验更改当前机器 SIP。

### 网页修复复验

本轮 41879 隔离后台启用了 `--fault-marker /private/tmp/aidr-p1p2-20260927/platform/web-fault-route`。以下命令仅对该隔离壳生效，用于真实页面的错误恢复检查，不修改数据库和成功响应：

```sh
printf '%s' '/api/v1/external-ai-gateways' > /private/tmp/aidr-p1p2-20260927/platform/web-fault-route
```

重新打开默认/设备客户端策略，应显示网关失败原因、真实策略及禁用的编辑保存入口。恢复后点击“重新加载 / Retry loading”：

```sh
: > /private/tmp/aidr-p1p2-20260927/platform/web-fault-route
```

若要验证策略本身读取失败，将首条命令中的路径换为 `/api/v1/clients/aidr-p1-acceptance/governance`，测试完同样清空标记。日常后台不支持此测试开关。两个策略入口的默认权限、设备继承和客户端版本限制不因验收提升。

当前测试执行器已因受控故障退出；进程历史行应禁用终止并注明原因。响应历史分别显示“退出已验证 / Exit verified”和“有效期已结束，未确认执行 / Validity ended; execution unconfirmed”，有效期信息在详情；解析器能力取最后客户端报告，顶部 Codex 可用与诊断区历史版本缺口可同时存在。运行中网页终止已补验；super_admin 默认客户端策略编辑及外部条件待验项见已有验收记录。
