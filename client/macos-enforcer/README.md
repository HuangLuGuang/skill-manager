# macOS AIDR 执行器

原生组件提供 ES 进程归属、签名策略、文件打开控制和精确实例响应。桌面“运行治理 → 系统采集”按客户端策略选择模式：默认仅审计订阅 fork/exec/exit 和文件 create/close(modified)/rename/unlink 通知；拦截额外订阅 AUTH_OPEN 并读取签名进程响应命令。模式变化关闭旧订阅、补传并重新启动；实际原生心跳确认模式，失败显示具体原因。平台入口是“客户端详情 → 行为审计 → 系统事件”。

## 桌面开始与停止

1. 配置客户端设备连接；在平台客户端策略中开启系统通道。在“策略与审批 → 系统采集策略”发布有效的 Agent 根可执行文件归属策略。根必须是有有效代码签名的实际 Mach-O 文件，脚本包装路径不适用。平台服务需要配置 `AIDR_POLICY_SIGNING_KEY_FILE`。
2. 在桌面“运行治理 → 系统采集”点击“开始采集”。先用已有设备凭证读取有效目标、策略版本和公开的 P-256 验签公钥，再通过 macOS 管理员授权部署组件、启动独立 root 管理进程。桌面保持普通用户权限。设备凭证不放进命令参数。
3. 缺少完整磁盘访问权限时，使用页面的系统设置入口，为 `/Library/Application Support/AgentManagerRuntime/system/bin/aidr-enforcer` 授权；“显示组件”定位该文件。管理员密码授权不能替代该权限。授权后重新开始。
4. 页面只有收到真实 ES 订阅后的原生健康记录才显示“采集中”，同时展示最近系统事件、上传 ACK、待发数量和稳定失败码。在平台策略中的 Agent 发起新操作，核对实际事件。已有 Agent 在下一条 ES 消息按路径、inode 和运行映像签名核验归属；未建立父子关系的已有子进程可能无法归属。
5. “停止采集”关闭订阅、回收原生子进程，再使用现有严格 ACK 队列做最多 5 秒的收尾上传。未确认记录留在原设备/平台绑定的 root 私有目录，下一次启动继续补传。停止成功与队列排空分别展示。关闭桌面窗口不会停止独立采集；持续运行至主动停止、系统通道关闭或进程退出。重启机器不会自动启动采集。

安装目录由 root 管理；每个用户通过固定、仅该用户可连接的 Unix socket 查询状态及停止。私有凭证、公钥和队列按平台/设备隔离。安装使用互斥锁，桌面按钮与命令入口均防止重复启动。状态通过正在运行的管理进程读取；旧状态文件不能证明仍在采集。运行时每 10 秒重查平台开关与策略，关闭通道、撤销凭证或策略过期会停止采集。

## 开发与正式发布

开发构建由打包脚本显式设置开发标记；仅在 SIP 已关闭时支持安装。首次安装或源组件内容变化时，在 root 目录暂存组件，完成 ad-hoc 签名，并在原生采集器签名中嵌入 `com.apple.developer.endpoint-security.client=true`。后续开始会核对已安装内容和签名；未变化的组件不重新签名。程序不会修改 SIP 或 TCC 数据库。

正式系统采集组件必须使用 Developer ID、Apple 批准的 ES entitlement，并随产品完成公证。Developer ID 打包目标需要在构建机钥匙串中提供签名身份，由 `APPLE_SIGNING_IDENTITY` 指定；原生资源使用 hardened runtime、时间戳和 ES entitlement 签名。没有正式签名的普通发布包不能通过系统采集安装校验。开发包、本机订阅成功和代码测试均不能代替正式发行验收。

**English:** Open **Runtime governance → System collection** in the desktop. Enable the platform system channel and publish a valid signed Agent executable attribution policy first. Start uses macOS administrator authorization to install/update components and launch an independent root collector; the desktop stays unprivileged. Grant **Full Disk Access** to the installed aidr-enforcer separately. Collection is reported only after a real ES subscription heartbeat. Stop unsubscribes, reaps the native process and performs a bounded final upload; unacknowledged records survive for the next start. Closing the desktop leaves collection running; collection continues until stopped, disabled by policy or the process exits, with no automatic restart after reboot. Development ad-hoc signing occurs only on installation/update with SIP already disabled. Production requires Developer ID, Apple ES approval and notarization.

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

开发机已有相应条件时可执行 `make adhoc-sign`。正式分发需要 Apple 授予的 Endpoint Security entitlement、有效签名和相应系统授权；本仓库的开发签名测试不证明普通客户设备可直接安装。此组件由独立 supervisor 管理，不安装 LaunchDaemon 或 System Extension。

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

- 最多 32 个 Agent 根映像、128 条规则。路径必须是现有普通文件，应用策略时解析链接并取得设备号/inode；根映像另验证签名并匹配运行时 cdhash。已运行根在下一条真实 ES 消息验证身份，后代通过已观察到的 fork/exec 关系纳入。
- 根路径填写真正运行的已签名 Mach-O 映像，不是 shell 启动脚本。当前桌面 Codex 的 `codex-cli/bin/codex` 是包装脚本，其真实映像为 `codex-cli/CodexCLI.app/Contents/MacOS/codex`。Universal 二进制逐个验证有界架构切片及摘要，避免默认架构与实际运行架构不同而漏认。
- 进程使用 boot ID、monitor ID、PID、PID version、启动时间识别；执行器保留完整 audit token。fork 继承、exec 更新身份、exit 移除，父退出不清除仍存活的后代。状态最多 4,096 个实例，容量或 ES 序列缺口清空不可信归属并报告缺口。
- 规则匹配规范路径或策略应用时取得的 inode，支持该文件的硬链接/符号链接别名；同一路径替换后的文件仍按路径匹配。替换后在其他路径出现的新 inode 别名需要重新发布策略。不是目录递归、任意文件系统变更或全链路数据防泄漏策略。
- 拒绝优先；未知 Agent 身份和过期策略分别采用显式动作。规则中的 `all` 作用于所有进程，请先在独立测试文件验证。未匹配资源允许。回调不执行磁盘读取、网络请求或人工审批，不启用 ES 授权结果缓存。
- 签名覆盖完整 JSON 字节、设备、版本、期限和规则。新版本落盘 fsync 后原子切换；无效签名/版本冲突保留原策略。规则更新保留未改变根映像的现有归属；移除或改变的根不再保留其范围。回滚发布历史内容的新版本，撤销发布空规则。

## 操作内容与覆盖范围

系统事件记录有界原文 argv（最多 8 KiB / 256 项）、执行时工作目录、程序路径、所属 Agent 根路径、可确认的父进程身份、退出码或信号，以及从内核启动时间计算的进程存活时间。命令参数不脱敏；超限或非 UTF-8 参数只保留可表示的前缀并标记不完整。历史记录缺少的新字段不会补造。fork/exec 共享精确进程身份关系；exec 更换映像后清除旧命令，进程退出和来源缺口清理内存元数据。

仅审计模式也记录 create、修改后的 close、rename、unlink。文件变化只说明内核观察到相应操作，不代表文件正文或模型输出。详情按 boot/monitor/PID/pidversion/start_us 关联此进程最近 200 条记录，展示命令、文件变化、退出结果和可展开的归属链；完整原始字段位于技术诊断。默认“命令与文件变化”筛除 fork 和健康事件，可切换事件类型查看。

客户端插件检查显式传入 `AGENT_MANAGER_ACTIVITY=client_probe`，采集器读取这一个标记并随子进程传播，不上传完整环境变量。此标记仅用于“客户端声明的自检”展示，可选择显示；不参与授权或归属判断。旧记录没有标记，不能追溯判定为自检。程序路径必须出现在策略中；Codex 包装脚本与真正可执行文件应区分。平台的采集范围显示配置目标，在线心跳不代表所有 Agent 已覆盖。

离线租约仍有期限，已认证在线设备在剩余期限的四分之一（最多 6 小时）内自动续签；管理员配置版本与签名版本分别比较，续签不使编辑草稿冲突，真正的并发配置修改仍返回冲突。桌面采集使用 `--duration 0` 持续运行；CLI 可指定正数时长用于短时验收。supervisor 断开后原生进程退出，待发队列保留。

**English:** System events now include verbatim bounded arguments (8 KiB / 256 items), execution cwd, executable and Agent root paths, known parent identity, normalized exit code/signal and process lifetime. Audit mode also records create, modified close, rename and unlink notifications. Details show the exact process instance’s latest 200 events and keep raw JSON under diagnostics. Output bodies, file contents and model messages belong to other sources. Client checks carry a display-only provenance marker; it grants no authority. Existing signed roots are verified on their next ES event; old descendants without observed ancestry can remain unattributed. Online lease renewal preserves the editor’s configuration version. Desktop collection runs until stopped, disabled or exited, with explicit bounded durations available for CLI acceptance.

### 本次 UI 人工验收 / UI acceptance

- [ ] 中文/英文：默认列表能直接读懂命令、工作目录、退出码/信号；长参数换行、不撑宽抽屉。
- [ ] 在配置中的真实 Agent 执行临时文件 create/write/rename/delete 和 exit 0/7；按 monitor、进程身份核对客户端、平台详情和实际文件变化。
- [ ] 先启动 Agent 再开始采集，新操作建立根归属；未配置 Agent 不报告为已覆盖。
- [ ] 自检筛选即时生效；健康/fork 可单独查看；详情只关联精确实例，不混入 PID 重用或其他设备。
- [ ] 编辑策略期间发生自动续签，草稿不丢失且可保存；另一管理员发布配置则提示刷新。
- [ ] 超长参数显示截断；包含引号、中文、换行的原文可读，旧记录按实际缺失展示。
- [ ] 开始 → 真实事件 → 严格上传确认 → 平台展示 → 停止与回收；离线恢复、取消授权及重复点击沿用下列清单。

**English:** Verify both locales, long arguments and drawer width; real Agent command/file/exit events end to end; pre-existing roots and excluded targets; probe/type filters and exact-identity detail; renewal during editing versus administrator conflict; truncation and historical records; start/upload/stop plus the lifecycle checklist below. No UI unit tests were added.

## 审计、故障与响应

原生审计缓冲为 1,024 条、单条最多 64 KiB；读端阻塞时不阻塞授权响应，真实审计丢失用 `aidr_enforcement_audit_gap` 和累计缺口报告。Go SQLite 队列最多 100,000 条，数据库页上限约 256 MiB；冻结批次最多 128 条/900 KB，绑定平台和设备。ACK 必须匹配设备、条数和精确上传字节 SHA-256，持久化后才删除已确认记录。既有 P1 事件、游标和冻结队列不修改。

网络不可用时继续执行有效缓存；上传队列保留，网络恢复后补传。缓存到期报告降级并执行 `expired_action`。执行器停止或失效后 ES 控制不再存在；supervisor 确认原生 EOF 后以已有 monitor 健康身份记录 `aidr_enforcement_native_exit` 并尝试上传，平台显示异常退出。没有已观测身份时不伪造健康事件。supervisor 同时失效或断网时，平台以最后一次实际报告时间判断新鲜度（10 秒），页面每 5 秒刷新，不能提供零延迟故障发现保证。停止观察页面不停止原生保护；停止前台 supervisor 会回收其原生子进程。

终止请求以设备、boot、monitor、精确进程实例和请求 UUID 绑定，平台检查可见性和管理员角色。执行器只对自己已确认的实例调用 `proc_signal_with_audittoken(SIGTERM)`，不退回仅按 PID 发送信号。下发、信号已发送、匹配 ES exit 已验证分开记录。请求期限 120 秒；重复请求不重复发送，执行器重启后的 monitor ID 不接受旧实例命令。

AUTH_OPEN 记录证明授权决定和响应状态，不能单独证明应用读取结果。文件创建、修改后关闭、移动/重命名和删除另以通知事件记录；这不包含文件正文、终端 stdout/stderr、网络请求或模型交互。

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

## 网络连接快照 / Network socket snapshots

系统采集在 ES 确认进程归属后，通过 macOS `proc_pidinfo(PROC_PIDLISTFDS)` / `proc_pidfdinfo(PROC_PIDFDSOCKETINFO)` 读取 TCP/UDP 套接字；ES 本身不提供通用网络连接订阅。读取前后使用 `proc_pidpath_audittoken` 的内核 idversion 校验和进程启动时间校验，并在输出前重新查询 ES 归属与策略版本。已有但从未被 ES 观察的进程不会仅凭 PID 加入范围。

实现字段为采样时间、本地/远端 IP 与端口、TCP/UDP、采样时 TCP 状态、原有精确进程身份与 Agent 归属。UDP 仅记录有远端端点的套接字，状态未知。方向、域名、DNS、连接开始/完整时长、收发累计字节数不可得，保持未知/缺省；socket buffer 当前占用不是传输总量。TCP ESTABLISHED 只说明采样时的 TCP 状态。快照不证明 HTTP 成功、模型交互或数据外传。

约每秒采样，仅首次、状态变化及每 30 秒持续观察生成记录。一次循环最多 256 个目标进程、每进程 1024 个描述符、256 条输出；进程间检查 200ms 时间预算，轮转处理剩余目标。最多缓存 8192 个套接字观察。达到预算或读取失败报告 `partial`，权限错误报告 `permission_denied`。短连接/瞬时失败可能完全漏采；消失不生成关闭事件。观察 ID 按精确进程实例和套接字内核身份/代次维护，原始内核地址不上传；中断观察后生成新 ID，不按 IP/端口合并。重启和采样缺口不保持连接连续性。平台仅汇总当前页同一观察 ID 的记录，并可展开每条原始记录。

网络读取在现有原生进程的主循环内，无额外子进程或订阅；管理员授权、ES entitlement 和完整磁盘访问沿用当前组件要求，套接字读取失败不终止进程/文件通道。停止后不再采样，原上传队列按严格 ACK 排空，未确认记录保留。网络有独立 `network_health`（source/state/sampled_at_ns），旧客户端缺省表示未报告。先部署平台再更新客户端；旧平台的严格 schema 会拒绝新字段并保留未 ACK 批次。

### 技术路线与 Apple 依据

| 方式 | 能力与边界 | 授权/发行与开销 |
| --- | --- | --- |
| Endpoint Security | 精确进程/文件来源；本项目订阅没有 TCP/UDP 连接事件 | 现有 root、ES entitlement、完整磁盘访问；正式包保留 Apple ES 授权、Developer ID 和公证 |
| libproc 快照（本次实现） | 可见套接字端点与 TCP 状态；不完整，不保证失败/关闭/短连接 | 复用现有 root 组件；不添加网络扩展 entitlement。SIP 已关闭开发包可测试；正式 ES 发行要求不变。轮询成本与目标进程和 FD 数量相关，受预算限制 |
| Network Extension 内容过滤系统扩展 | `NEFilterSocketFlow`、源进程 audit token、newFlow/flowClosed/statistics 及字节报告，可作为未来事件路线；newFlow 不等于 TCP 成功 | 独立系统扩展、`content-filter-provider-systemextension`、宿主 `com.apple.developer.system-extension.install`、匹配签名/描述文件、扩展与网络过滤授权；正式包 Developer ID/公证。需核对版本与可导出元数据接口，不能把 DataProvider 的数据沙箱当成可任意上传的通道。本次未实现或验证 |
| 包捕获 | 包级时间/端点可观察，不能单独证明精确进程归属，TLS 不提供明文 | 不采用；不能用时间邻近猜归属 |

Apple 官方资料：[libproc 实现及 audit-token idversion 比较](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.c)、[socket_info 字段](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info.h)、[Network Extension 配置](https://developer.apple.com/documentation/xcode/configuring-network-extensions)、[源进程 audit token](https://developer.apple.com/documentation/networkextension/nefilterflow/sourceprocessaudittoken)、[流事件和统计报告](https://developer.apple.com/documentation/networkextension/nefilterreport)、[系统扩展测试](https://developer.apple.com/documentation/driverkit/debugging-and-testing-system-extensions)。Apple 说明 SIP 关闭可取消部分系统扩展开发签名/公证检查，但这不证明 Network Extension 的装载、描述文件、用户授权及报告链路已通过。本机无可用代码签名身份；本次不修改 SIP/TCC，也不把 ad-hoc 包当成正式包。

**English:** This implementation samples attributed processes' TCP/UDP sockets through libproc; it is not a complete network-flow event stream. It validates audit-token idversion and process start time before/after reads, then rechecks ES attribution and policy. Endpoint addresses, ports and sampled TCP states are available. Direction, domain, DNS evidence, byte totals and full duration remain unknown. Missing sockets do not synthesize close or failure. Snapshot IDs distinguish socket generations; kernel addresses stay local. Sampling is bounded, approximately once per second, with change records and 30-second continuing observations. Independent network health reports incomplete or denied reads without claiming process/file health proves network coverage. Stop and strict-ACK recovery reuse the existing collector lifecycle. Upgrade the platform before clients; old records and frozen queues remain intact. A Network Extension flow-event provider is a separate, unimplemented distribution/authorization route. Formal ES signing and notarization requirements remain unchanged.

### 2026-10-07 验证状态 / Validation status

已通过：`make test` 的真实本地 IPv4/IPv6 TCP、connected UDP、同端点两个独立 socket、对端 FIN 的 CLOSE_WAIT、PID-version/启动时间不匹配拒收；采样器测试归属表的范围排除、重复采样抑制和 ES 缺口后新观察 ID（独立测试驱动，不代表真实 Agent ES 归属）。Go 记录与冻结队列恢复/错误 ACK 保留测试、相关采集生命周期回归；平台网络入库/重复投递/筛选/精确进程上下文/字段拒收测试。中英文 i18n、平台和开发桌面包构建通过。

实机已通过：用户管理员授权后运行新版 root 采集器，仍使用原策略版本 8 的 Claude 范围。2026-10-07 11:12–11:14（Asia/Shanghai），真实 Claude 2.1.220 主进程 PID 83622 向本地受控 HTTP 503 服务请求；其 SessionStart Hook 子进程 PID 83639 建立 IPv4/IPv6 TCP 和 connected UDP。平台收到 12 条网络记录、9 个不同观察 ID：主进程 5 条、子进程 7 条（3 个 TCP 建立、3 个 CLOSE_WAIT、1 个 UDP 未知）。同目标两条 TCP 使用不同 ID；对照独立进程 PID 83623 没有任何系统记录。此测试没有模型成功响应；Hook 子进程不是模型驱动工具调用。

本次 monitor `7b280954-51bc-46b2-ba10-c536a659356f` 的记录通过现有冻结队列与严格 ACK 上传；客户端报告最近上传确认、待上传 0，平台入库后通过真实中英文页面核对 IPv6 端点、长路径、进程归属、2 次采样展开和原始序列。修复实机发现的采样历史未传入详情、变化快照误标“相同状态”、重复命令标题。11:14:46 页面停止后，平台收到 sequence 374 的停止健康回执，网络状态 stopped，待上传 0；root 管理 PID 77820 与原生 PID 77822/77825 均已退出。网络文件队列本身未以提权方式直接读取；入库、上传确认与停止回执按该 monitor 核对。

其余实机验证：等待授权及采集中禁用开始按钮；此前 150 秒授权超时回到停止；平台网络筛选立即生效，中英文真实详情在 692px 窗口可换行；插件接入与行为审计抽屉宽度一致。取消授权分支已实测：用户点击“不允许/取消”后，桌面明确显示“已取消管理员授权，未启动采集”，开始按钮恢复、停止按钮禁用；没有 root/native 采集进程或控制 socket，待上传仍为 0，平台最后记录仍为原采集会话的停止回执。

未完成：真实模型服务成功调用、网络通道实机离线恢复、真实权限拒绝及组件启动失败；相关队列/ACK 和生命周期自动测试不替代这些现场分支。完整短连接/失败事件、累计字节数、域名/方向及完整持续时间不在当前快照能力内。权限拒绝不通过修改 TCC/SIP 测试。人工清单见客户端文档。

**English:** Real desktop authorization started the upgraded collector under the existing Claude-only policy. Claude PID 83622 requested a controlled local HTTP 503 endpoint; its SessionStart Hook child PID 83639 opened IPv4/IPv6 TCP and connected UDP sockets. Twelve network records covered nine observation IDs; TCP establishment and peer FIN/CLOSE_WAIT were observed, UDP remained unknown, and independent PID 83623 was excluded. This is an actual Agent request to a local stub plus a startup-Hook child, not a successful model-service call or model-driven tool execution. Upload confirmation, zero backlog, platform insertion and bilingual real-record details passed. Desktop stop produced sequence 374 with network stopped and zero backlog; all three privileged processes exited. Live cancellation passed: the desktop reported authorization cancelled, restored Start and disabled Stop; no privileged collector or control socket remained, backlog stayed zero and the platform retained the previous stopped receipt. Live offline recovery, permission denial and component failure remain unverified. Automated queue and lifecycle tests are separate evidence. Full short-flow/failure capture and flow statistics are unsupported by this snapshot route.
