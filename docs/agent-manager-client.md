# Agent Manager Client 使用说明

## 客户端菜单显示 / Client menu visibility

在“默认客户端策略”或单客户端策略弹窗的“采集与治理配置 → 客户端界面”设置菜单。客户端概览固定保留；Agent 管理、模型切换、执行记录、Agent 运行治理默认显示。全局使用显示开关，单客户端逐项选择“跟随全局 / 显示 / 隐藏”；“全部跟随全局”修改草稿，预览并保存后生效。单项覆盖不影响其他菜单继续继承。全局写入沿用超级管理员权限，单客户端写入沿用客户端管理权限及可见范围。

配置通过现有 `sync_policy` 和心跳链路下发，Go 客户端缓存后通知桌面读取，不要求重启。离线和重启沿用当前连接的缓存，切换平台清除旧绑定策略。当前页面被隐藏时返回概览，对应快捷入口同步隐藏；通知证据保留，隐藏页面的跳转入口不显示。菜单隐藏不改变后台扫描、采集和治理权限。仅菜单变化不请求额外全量扫描，也不改变运行治理目标版本；同时存在尚未同步的治理变更时，仍执行相应治理同步。

“客户端菜单配置已同步”表示客户端缓存的菜单值与当前目标相同，桌面读取后更新界面。未报告菜单能力的客户端显示升级提示；可以预先保存配置，升级后同步。最近配置回执时间以设备报告为准。

**English:** Open **Default client policy** or an individual client's policy dialog, then **Collection & governance → Client interface**. Overview is always visible. Agent management, Model switching, Execution records, and Agent runtime governance default to visible. Each client can inherit or explicitly show/hide each menu. Resetting all menus to global changes the draft until previewed and saved. Existing administrator permissions and client scope checks apply.

The existing policy task and heartbeat mechanisms deliver configuration. The Go client caches it and signals the desktop without a restart. Offline startup uses the current connection's cache; switching platforms clears the previous policy. Hidden active pages return to Overview; related shortcuts disappear while notification evidence remains. Menu visibility does not disable background features. Menu-only changes do not request a full scan or change the runtime-governance target version; pending governance changes still synchronize. “Client menu configuration synced” confirms a matching cache receipt, not that an open window rendered it. Older clients require an upgrade.

人工验收 Todo / Manual acceptance:

- [ ] 全局隐藏、单客户端明确显示、另一菜单继续继承；恢复单项和全部继承。 / Global hiding, individual overrides, independent inheritance, and resets.
- [ ] 当前页被隐藏返回概览、快捷入口联动、通知证据保留、仅概览可见。 / Active-page fallback, shortcuts, retained notifications, and overview-only layout.
- [ ] 离线重启、重连、平台切换及旧客户端升级提示。 / Offline restart, reconnect, platform switching, and older-client status.
- [ ] 中英文全局/单机编辑与预览、窄窗口和长文案；菜单变化不增加扫描或重启采集。 / Bilingual editing/preview, narrow layouts and long text; no extra scans or collection restarts for menu-only changes.

## 后台可靠性与更新 / Background reliability and updates

桌面状态通过主守护进程的本地 IPC 读取：macOS/Linux 使用当前用户私有目录中的 Unix Socket，Windows 使用仅当前进程用户可访问的 Named Pipe。一次读取使用独立 SQLite 只读事务，返回状态、资产和事件修订；Agent 管理页同时读取待处理、扫描历史及隔离副本，其他页面不读取这些分区。旧版或未运行的服务通过单次 `local-snapshot` 命令提供诊断读取，安装和修复入口仍可使用。

关闭空闲窗口会销毁 WebView，托盘及原生通知处理继续运行；无窗口时原生层负责自动更新检查。重新打开会重建窗口并恢复页面及内存中的表单草稿。打开的弹窗、已选文件、进行中的界面操作或实时系统观察会保留隐藏窗口，避免丢失操作上下文；草稿不写入磁盘。完全退出桌面进程后，桌面通知与更新检查随之结束，Go 主守护服务和独立代理仍按各自服务生命周期运行。

普通事件空队列检查只读数据库，不再申请或更新发送租约；已有发送节流、持久化重试及回执规则保持。IPC 性能、关闭窗口内存和扫描/Hook 延迟属于不同指标，需分别测量；Windows/Linux 构建通过不等于系统权限、宿主 Hook 和通知已通过实机验收。

平台状态、历史记录和模型目录刷新统一由 Go 层发送 HTTP 请求，桌面通过固定操作的本地 IPC 调用，不传递目标 URL 或凭据；旧版或停止的服务通过同一个 Go 命令实现读取与刷新。请求已经发出后发生通信中断时，不自动重放模型目录刷新。原生更新器继续负责更新包签名和系统安装。

普通事件入队事务提交后写入跨进程唤醒标记，上传器监听该标记并按数据库中的节流、重试及发送租约时间调度。空闲时每 30 秒补偿检查一次持久化队列；监听不可用或通知丢失时也依靠该检查恢复。队列仍是唯一交付依据，收到持久化回执后才删除事件。

**English:** Desktop reads use daemon-local IPC: a Unix socket in a private user directory on macOS/Linux, and a named pipe restricted to the process user on Windows. Each snapshot uses a separate read-only SQLite transaction for state, inventory and revision. Agent Management also requests pending items, scan history and recovery copies; other pages omit these partitions. A single `local-snapshot` command supports diagnostics when the daemon is older or stopped.

Closing an idle window destroys its WebView while the tray and native notification worker remain active. The native layer checks for updates while no window exists. Reopening reconstructs the window and restores its page and in-memory form draft. Open dialogs, selected files, active UI operations and live system observation retain the hidden window to preserve their context. Drafts are not written to disk. Quitting the desktop stops desktop notifications and update checks; the Go daemon and independent proxy keep their service lifecycles.

Empty ordinary-event queues require only a read, without acquiring or updating sender leases. Existing pacing, durable retries and receipt handling remain. Measure IPC latency, window memory and scan/Hook latency separately; cross-compilation does not establish native permission, host Hook or notification acceptance.

Go owns platform status, history and model-catalog HTTP calls. Desktop IPC accepts fixed operations rather than caller-supplied URLs or credentials; the same Go command supports older or stopped services. An interrupted request is not automatically replayed after transmission. The native updater retains package signature verification and OS installation.

After committing an ordinary event, producers write a cross-process wake marker. The uploader watches it and schedules work using persisted pacing, retry and sender-lease deadlines. A 30-second reconciliation timer checks the durable queue while idle or when filesystem hints are unavailable. Events are removed only after durable receipts.

- Hook 接收器继续运行在主用户守护服务内。Skill 目录监听独立启动，初始化、刷新或运行时错误记录为 `sync:watcher:error`，每 30 秒重试并触发补偿扫描；心跳、任务同步和 Hook 不依赖监听成功。监听降级期间事件驱动检测可能延迟，周期巡检继续运行。
- `receiver-status.json` 写入失败只影响状态展示，输出 `aidr_desktop_status_failed`，恢复后输出 `aidr_desktop_status_recovered`；监督器通过实际 IPC 核对接收器健康。身份绑定、策略和审计存储失败仍执行既有安全处理。
- 主服务运行锁、治理修改锁和服务协调锁使用操作系统锁，进程退出后释放，锁文件保留。不要通过时间戳或删除锁文件解除占用。兼容旧 PID 锁时，旧进程仍存活则等待退出，不靠超时抢锁。
- 自动更新先下载并验证签名，再调用 `stage-update` 将后台程序保存到 `~/.agent-manager/service/versions/<sha256>/`。初次从应用包迁移需要一次后台重启；后续桌面安装期间既有服务继续运行。新后台切换后，检查进程持锁、健康记录新鲜，以及已启用 Hook 的本地 IPC。候选启动失败时尝试恢复校验通过的原程序，并核对恢复结果。保留版本用于恢复，不随应用目录替换删除。
- 安装失败后通过保留的后台程序检查/恢复服务，仅在确认就绪后显示服务可用。`prepare-update` 仍为暂停主服务的维护命令，连接切换继续使用；自动更新改用 `stage-update`。后台版本切换前先更新命令桥，再写入私有、30 秒失效的升级标记；切换或恢复结束即清除。新命令桥和 TeleAgent 代理仅在这个窗口内对尚未建立连接的请求等待重连，单次最多 8 秒，也受宿主取消/超时限制。已接收请求按原有两秒连接期限完成审核后退出。策略拒绝、身份/协议错误和已发送但结果不明的请求不重放；等待超时仍报错，审核规则保持生效。
- TeleAgent 模型代理保持独立 LaunchAgent，主服务准备、切换、回滚均不停止它。代理配置异常单独报告，不阻止主服务恢复。模型转发独立于 Hook，工具审核仍需要有效接收器决策。

**English:** Skill watching starts independently of the user daemon's Hook, heartbeat and task loops. Initialization, refresh and runtime failures are recorded under `sync:watcher:error` and retried every 30 seconds with compensating scans. Periodic patrol continues. Telemetry write failures report stable failure/recovery codes without stopping intake; actual IPC verifies health. Identity, policy and audit-storage enforcement remain unchanged. Run, mutation and reconciliation locks use OS locks released at process exit; their persistent files must not be deleted or treated as leases. Live legacy PID owners remain exclusive.

Updates download and verify signatures before `stage-update` preserves versioned workers outside the application bundle. Initial migration and worker version switching require brief restarts; desktop installation itself leaves the worker running. Before switching, reconciliation installs the command bridge and writes a private upgrade marker that expires after 30 seconds and is removed after switching or recovery. Updated command bridges and the TeleAgent proxy retry failed connections only during this window, for at most eight seconds per request and within the host's cancellation/deadline. Accepted requests drain under their existing two-second connection deadlines. Policy denials, peer/protocol failures and ambiguous sent requests are not replayed; exhausted waits still fail. Readiness requires a live lock, fresh health and local IPC for enabled Hooks. Failed activation attempts verified rollback. Failed desktop installation checks/restarts the preserved worker and reports actual recovery status. `prepare-update` remains the explicit stop command used by connection maintenance. The independent TeleAgent proxy continues forwarding during these operations; tool review still requires a valid Hook decision.

### TeleAgent 代理自动升级与实际版本 / Proxy upgrades and running identity

macOS 代理安装将新程序保存到 `~/.agent-manager/aidr/teleagent-proxy/versions/<sha256>/`，执行候选程序的配置自检并核对摘要，成功后发布目标版本。正在运行的代理自行观察目标变化；模型转发或工具审核尚未结束时显示“等待请求结束后升级”，继续服务。空闲时停止接收并排空已有连接，复制监听描述符保留原端口和系统连接队列，再通过 `exec` 加载新程序，PID 保持不变。空闲检查后若又进入长请求，排空等待最多 100 毫秒即恢复接收，旧请求继续完成，稍后再尝试。候选检查或 `exec` 失败保留当前服务；持续忙碌会延迟升级，不强制结束请求。正常常驻进程仍为主守护服务和 TeleAgent 代理两个。TeleAgent 普通工具审核使用 4 秒等待预算，与命令 Hook 对齐，不再先于接收器的 2 秒处理期限放弃；明确升级窗口内连接失败最多等待 8 秒。已发送请求不重放，具体身份/传输/协议错误保留为稳定错误码。MCP 审核保留原有 1 秒预算，升级等待也不能超过该预算；较长主服务切换窗口可能导致 MCP 审核失败，不能将本次终端工具成功扩大为 MCP 无中断保证。

不支持该协议的旧代理需要一次空闲激活，本机已在没有已建立 TCP 连接且 TeleAgent 任务完成时执行。自动切换覆盖加载此协议后的升级；操作系统崩溃、强制杀进程及供应商故障不属于无中断保证。发布包的来源和签名校验仍由客户端更新流程负责，代理摘要检查用于确认目标程序一致。

“设置 → 后台运行”分别显示主守护服务 / Hook 与 TeleAgent 代理的实际版本、PID、启动时计算的 SHA-256 摘要、健康状态、目标摘要与升级状态。界面打开时每 5 秒刷新本地健康，业务清单仍使用事件通知。主服务健康要求新鲜健康记录、存活进程及有效运行锁；启用 Hook 时健康记录只在 IPC 验证通过后更新。代理健康来自经过认证的本地 HTTP 状态接口；旧版本只确认就绪，不猜测其运行版本。模型可用性通过真实模型请求验证。CLI 可运行 `agent-manager-client service-status`。

**English:** On macOS, installation stages an immutable digest-addressed proxy binary, runs candidate configuration preflight and verifies its digest before publishing the desired version. The running proxy waits for model forwarding and tool review to finish. It drains connections while retaining a duplicate listening descriptor and kernel backlog, then uses `exec` to load the candidate with the same PID and port. If a long request races the idle check, acceptance resumes after at most 100 ms; the existing request continues and the upgrade waits for another idle opportunity. Failed preflight or `exec` retains the current service. Continuous traffic can postpone activation. The normal persistent process count remains two. Ordinary TeleAgent tool reviews use the same four-second caller budget as command Hooks, while receiver connections retain their two-second processing deadline. Upgrade dial waits remain bounded to eight seconds. Submitted requests are not replayed; peer, transport and protocol errors retain their specific stable codes. MCP retains its one-second budget, including upgrade waits. A longer worker outage can fail MCP review; bash continuity does not establish MCP continuity. Legacy proxies need one initial idle activation; OS crashes, forced termination and vendor failures are outside this continuity contract. Package signature verification remains part of the desktop updater.

Settings → Background Operation shows each service's actual version, PID, startup-captured SHA-256, readiness, desired digest and upgrade state. Local health refreshes every five seconds while this page is visible; business state remains event-driven. Worker readiness uses a fresh health marker, a live process and an OS-held lock, with enabled Hook IPC checked before publishing health. Authenticated local HTTP establishes proxy readiness. Legacy readiness does not establish its running version; local health does not establish vendor availability. Use `agent-manager-client service-status` for JSON diagnostics.

### 当前修复验收 / Current acceptance (2026-10-13)

本机开发客户端通过 Cmd+Q 完全退出后，TeleAgent 2.7.0 会话 `ses_ecc25e41dffeOYfrgviydELPSt` 在 14:01:34–14:02:02 CST 完成真实 `NewApi/chat-flash` 请求和 10 次独立串行 `bash` 调用，全部退出码 0。模型请求开始后发布新代理；14:01:35.814–14:01:43.283 的采样显示“等待空闲”，14:01:46.900 加载新程序。代理 PID 始终为 80155，摘要从 `f0e69186fbbe` 切换到 `5de4c4539eb5`，没有手工重启代理。主守护同时由 PID 92617 切换到 95502，第 3 次工具调用跨越切换，用时 2.273 秒后成功。11 条原生助手消息均完成且无模型错误，最后一条 `finish=stop`。20 条执行前/后 Hook 按原生调用 ID 唯一匹配，并已逐条确认本地 ACK；平台记录范围 26385–26406（夹有其他事件）。最终两服务均健康、目标版本已生效、无在途请求，桌面进程不存在，工具策略未修改。

验收过程中另一次调用曾在 1 秒处提前放弃，而平台已记录接收器的允许决策；据此修正代理审核等待预算为 4 秒，并补充延迟 1.2 秒的允许/拒绝回归，确保不重放。修复后两个独立现场会话各完成 10 次调用。上述成功会话用于最终升级证据，不把之前失败计入成功。

隔离真实进程测试还覆盖完整流式响应、同 PID/端口切换、并发新连接及损坏候选拒绝：73 次并发探测成功，观察到的最大延迟约 149 毫秒，此数字仅描述该次本机夹具，不是时延 SLA。可通过 `python3 scanner/scripts/test-teleagent-upgrade.py <旧构建> <新构建>` 使用两份不同的 macOS CLI 构建复现。Go 主客户端完整包通过，节流及延迟回执场景连续 5 次通过，单轮等待预算耗尽回归通过；Hook/CLI 回归、排空/超时 race 检查与 Windows/Linux 交叉构建通过。桌面 i18n 29 项通过，开发应用构建通过；设置页的实际版本/健康信息已在中英文正常窗口检查。

**English:** With the development GUI fully exited using Cmd+Q, real TeleAgent 2.7.0 session `ses_ecc25e41dffeOYfrgviydELPSt` completed model requests and ten separate sequential bash calls between 14:01:34 and 14:02:02 CST. A candidate was published after inference began; samples recorded waiting for idle before activation. Proxy PID 80155 and its port were retained while the loaded digest changed from `f0e69186fbbe` to `5de4c4539eb5`. The daemon changed from PID 92617 to 95502; call three crossed that switch and succeeded in 2.273 seconds. All tool exits were zero, eleven native assistant messages completed without model errors, and the final message finished with `stop`. Twenty before/after Hooks matched exact native call IDs and local ACKs; platform IDs span 26385–26406 with unrelated events between them. Both services ended healthy and current, without a desktop process or policy changes.

An earlier live review exposed premature one-second cancellation despite a recorded allow decision. The four-second caller budget and delayed allow/deny regression address it; two subsequent independent live sessions each completed ten calls. An isolated real-exec fixture also retained a complete stream, PID and port, served 73 concurrent probes and rejected an invalid candidate; its approximately 149 ms maximum observed latency is not an SLA. Managed-client package, repeated pacing, round-expiry, Hook/CLI, targeted race and cross-build checks passed. Desktop i18n passed 29 checks and the development app built; running identity/readiness was inspected in both languages at the normal window size.

最终本机运行构建为 `dev / 9b548f181279`：主守护 PID 4169、代理 PID 80155，均健康且目标已生效。14:07 CST 在桌面继续退出时执行最终构建复核，真实模型返回后工具调用 `call_7936a98a3a344d949da51274` 输出 `AM_FINAL_20261013_1407`、退出码 0；平台 26452/26453 两条 Hook 均已 ACK。此构建保留 MCP 原有短预算，MCP 升级连续性尚未实测。最终开发应用包已重建。

**English:** The final local build is `dev / 9b548f181279`, with healthy daemon PID 4169 and current proxy PID 80155. At 14:07 CST, with the GUI still exited, a real model/tool smoke check completed call `call_7936a98a3a344d949da51274` with the expected marker and exit zero; platform Hooks 26452/26453 were acknowledged. This build retains the original short MCP budget; live MCP upgrade continuity remains unverified. The development app bundle was rebuilt.

新增界面人工 Todo / Remaining manual UI checks:

- [ ] 最小 900px 窗口：中英文长版本号、等待升级与失败状态换行。Minimum-width layouts with long versions and pending/failed states.
- [ ] 正式签名安装包、重新登录系统及其他操作系统现场验收；本机开发构建与交叉编译不替代这些验收。Signed packages, login recovery and other OS hosts remain separate acceptance work.

### 升级期间真实验收 / Live upgrade acceptance

2026-10-13 12:59 CST，本机在桌面客户端保持退出的情况下执行真实 `binary_changed` 升级：主守护 PID 82748 → 6332，代理 PID 4477 保持不变。升级协调耗时 4.903 秒，20 ms 间隔连接采样观察到约 3.6 秒不可连接窗口。TeleAgent 2.7.0 会话 `ses_ecc5efd16ffeuv80Wn4CGqiUQL` 连续串行完成 20 次独立 `bash` 调用，退出码均为 0；第 3 次调用 `call_b5c4e29124904b0cb5885f52` 跨越该窗口，用时 2.613 秒，等待后成功。真实 `NewApi/chat-flash` 模型调用和最终回复正常完成。对应 40 条 Hook 已逐条匹配调用 ID 与本地 ACK，无重复；平台记录范围 26108–26153（夹有其他 Agent 事件）。审核策略未修改，升级标记已清理。

后续节流修复已改为按实际发送完成时间控制，并将单轮等待预算耗尽留到下一轮；完整主客户端包复跑通过，节流间隔与延迟回执场景连续 5 次通过。验收覆盖本机开发构建的升级窗口；不代表所有宿主的超时设置或其他系统已实测。超过等待预算、异常崩溃和审批中的单次授权跨接收器重启仍按现有失败/授权规则处理。

**English:** At 12:59 CST on 2026-10-13, an actual `binary_changed` upgrade ran with the desktop exited. The daemon changed from PID 82748 to 6332; proxy PID 4477 remained unchanged. Reconciliation took 4.903 seconds; connection samples every 20 ms observed approximately 3.6 seconds without a listener. TeleAgent 2.7.0 completed 20 separate sequential native `bash` calls with exit code 0. Call 3 crossed the outage and succeeded after waiting, taking 2.613 seconds overall. Real `NewApi/chat-flash` requests and the final reply completed. All 40 before/after Hooks matched native call identities and local ACKs without duplicates; platform IDs span 26108–26153 with unrelated events between them. Policy was unchanged and the upgrade marker was removed.

Subsequent pacing changes use actual delivery completion and defer unsent records when the round expires. The complete managed-client package passed, with five consecutive passes for pacing and delayed-receipt cases. Acceptance covers the upgrade window of this local development build. Exhausted waits, crashes and pending single-use approvals across receiver restarts retain their failure/authorization semantics.

界面验收 Todo / Manual UI acceptance:

- [ ] 中英文更新弹窗：下载/验签失败、安装失败但后台可用、恢复无法确认三类提示与窄窗口长文本。Verify bilingual error states and narrow layouts.
- [ ] 正式安装包：首次后台目录迁移、升级成功、安装中断和失败恢复，同时核对 Hook 工具结果及 TeleAgent 流式响应。Verify packaged migration, interrupted installation and recovery against actual tool results and streams.
- [ ] Windows/Linux 实机验证服务安装、锁恢复与升级；交叉编译不替代系统服务验收。Verify lifecycle behavior on Windows/Linux separately from cross-compilation.

自动化验证（2026-10-13，macOS）：三个 Go 包完整回归、关键恢复路径 race 检查通过；隔离主进程强制退出后，新进程在既有重试策略内恢复 Hook IPC 并接收工具事件；独立测试 LaunchAgent 强制退出后恢复到就绪。TeleAgent 独立 LaunchAgent 使用模拟上游完成跨启动器退出及服务协调的流式响应验证。后台启动失败回滚及回滚失败使用隔离服务管理器夹具验证。Rust 测试 27 通过、3 项既有忽略；桌面 i18n 29 通过；Windows/Linux 交叉编译通过。

**English:** Automated validation on 2026-10-13 passed all three affected Go packages, targeted race checks, isolated worker crash/restart with Hook IPC intake, and real macOS LaunchAgent readiness recovery. A separate TeleAgent LaunchAgent preserved mocked upstream streams across launcher exit and reconciliation. Service-manager fixtures covered failed activation, verified rollback and failed recovery. Rust: 27 passed, 3 existing ignored; desktop i18n: 29 passed; Windows/Linux cross-builds passed.

本机应用与真实验收（2026-10-13，12:44–12:48 CST）：新版开发侧车已通过 `reconcile-service` 应用到日常 LaunchAgent，注册路径与构建产物 SHA-256 一致。迁移时曾有一次命令被 `aidr_hook_receiver_unavailable` 拦截，Hook 就绪后重试成功，证实后台切换存在短暂窗口。随后对开发客户端桌面进程发送 SIGTERM，确认桌面及开发启动器均已退出，主守护进程和 TeleAgent 代理 PID 保持不变。TeleAgent 2.7.0 的真实 `NewApi/chat-flash` 请求返回验收标记；同一会话 `ses_ecc6b5de0ffe73irhCie4WOmHd` 的 `bash` 调用 `call_ced93b6e4e20425f847f518c` 写入并读回独立验收文件，原生日志记录完成、退出码 0。对应 `BeforeToolExecute` / `AfterToolExecute` 已按调用 ID 核对平台记录 26012 / 26013 与本地 ACK（序号 25947 / 25948），执行前决策为允许。未改变工具策略。此结果覆盖本机开发客户端完全退出后的真实模型与工具调用；托盘菜单正常退出、正式签名安装包升级和其他系统仍须分别验收。

**English:** Live application and acceptance on 2026-10-13, 12:44–12:48 CST: the rebuilt development sidecar was applied to the everyday LaunchAgent using `reconcile-service`, with matching registered and built SHA-256 values. One command was rejected with `aidr_hook_receiver_unavailable` during migration and succeeded after readiness recovered, confirming the brief worker-switch window. The development GUI was then terminated with SIGTERM; neither the GUI nor its development launcher remained, while daemon and TeleAgent proxy PIDs stayed unchanged. A real TeleAgent 2.7.0 `NewApi/chat-flash` request returned the test marker. A subsequent native `bash` call wrote and read a dedicated acceptance file and completed with exit code 0. Its before/after Hooks matched platform records 26012 / 26013 and local acknowledged sequences 25947 / 25948 by native call ID, with an allow decision before execution. Tool policy was unchanged. This verifies actual model and tool access after full development-GUI termination; tray-menu quit, signed packaged upgrades and other operating systems require separate acceptance.

## 在线操作指南 / Online operating guides

### 手动配置模型 / Manual model configuration

内置模型使用平台发布的 `MODEL_GATEWAY_PUBLIC_URL`，未配置时复用客户端管理地址。
例如管理地址为 `https://server`，模型地址可以是 `http://server:8000`；OpenAI-compatible 配置追加 `/v1`。
模型切换预览显示目标地址，配置完成后的模型页显示实际读取地址，手动配置引导使用同一平台地址。
启用专用入口后需升级客户端并重新应用现有 Agent 配置；注册、心跳和凭证领取仍走管理地址。
HTTP 仅用于客户批准的内网，部署步骤见[模型专用 HTTP 入口](offline-deployment.md#模型专用-http-入口)。

English: Built-in models use the platform's `MODEL_GATEWAY_PUBLIC_URL`, or the Client management address
when unset. Switch previews show the target address; the model page reads the actual configuration, and manual
setup uses the published address. Upgrade clients and reapply existing Agent configurations after enabling
the dedicated entry. Management traffic keeps its own address. Restrict plaintext HTTP to approved networks.

在“模型切换”选择没有自动配置适配器的 Agent，打开“手动配置引导”：

1. 在 Agent 自身设置中确认自定义 Base URL、API Key、模型名称和协议选项，选择实际支持的协议。
2. 选择模型并复制地址、模型调用名称。有手动领取权限时点击“申请凭证”，随后“复制凭证”，粘贴到 Agent 并保存。无权限时按页面说明由管理员为当前客户端凭证开启手动领取权限，再点击“重新检查权限”。本次凭证仅能在 5 分钟的临时复制窗口内复制；关闭后需要重新领取，内置网关会替换上次手动申请的凭证。
3. 重启 Agent 并创建新会话，发送测试消息，在对应网关的调用记录中核对 Agent、模型及结果。完成引导只结束本次操作指引，不将调用标为已验证，也不自动写入 Agent 配置。

In Model switching, select an Agent without an automatic adapter and open the manual guide:

1. Find the Agent’s custom Base URL, API Key, model and protocol settings; select a protocol supported by the installed version.
2. Select a model and copy its endpoint and invocation name. With manual retrieval permission, request and copy a credential, paste it into the Agent, and save. Otherwise, ask an administrator to enable manual retrieval on this Client credential and recheck permission. The temporary copy is available for five minutes; closing the guide requires retrieval again, replacing the previous manual credential for the internal gateway.
3. Restart the Agent, start a new session and send a test message. Check the Agent, model and result in the relevant gateway’s call records. Finishing only confirms the guide actions; it does not mark calls as verified or write Agent configuration automatically.

授权、凭证范围及外部网关边界见[手动配置与凭证领取](model-gateway.md#手动配置与凭证领取--manual-configuration-and-credential-retrieval)。

See [manual configuration and credential retrieval](model-gateway.md#手动配置与凭证领取--manual-configuration-and-credential-retrieval) for authorization, credential scope and external gateway behavior.

平台帮助中心的 `/docs/aidr-client` 提供客户端接入、日志目录、Hook 安装/信任、系统目标与权限、停止退出和补传步骤及中英文截图。三通道比较见 `/docs/aidr-overview`，平台操作见 `/docs/aidr-platform`，审计/拦截与审批见 `/docs/aidr-policies`，Skill 异步认证见 `/docs/aidr-skill-audit`，排障与性能验收见 `/docs/aidr-troubleshooting`。

The online Help Center provides illustrated bilingual procedures at `/docs/aidr-client`, with separate guides for channel comparison, platform operations, control/content policies, asynchronous Skill certification and troubleshooting. This repository document retains implementation and integration details. Help screenshots are direct captures of the local platform and native macOS Dev client on 2026-10-10. Visible states describe that local installation; customer-device permissions and enforcement require separate validation.

## 接入后自动采集与 Hook 状态

未保存运行治理策略时，平台默认启用 Agent 日志和 Hook，关闭系统通道，Hook 使用仅审计模式；目标为本机发现的 Codex / Claude Code，普通插件自动安装和更新。客户端接入平台、取得有效策略后，主后台服务自动读取日志并启动同进程 Hook 接收器，无需再次点击“启用自动运行”。客户端启动前应先升级平台。旧协议无法应用新通道/模式时需更新客户端；旧客户端在没有显式策略时保留原有手动接收器控制。

已保存的全局策略、单台覆盖和关闭设置保持不变。单台客户端选择继承后使用当前全局策略；需要自动安装已有单机配置的插件时，在“客户端策略 → 接入与采集”将安装方式设为自动。采集正文、脱敏及截断长度仍由审计策略决定。只安装应用、尚未接入平台，不会得到上传目标。普通插件需要的宿主启用/信任，以及企业受管安装需要的管理员授权，均不能由平台代替。接收器由主后台服务监督，与日志采集在同一守护进程内运行；关闭窗口或完全退出桌面客户端后仍继续工作。通过托盘的“打开客户端窗口”或 macOS Dock 可恢复窗口。

“客户端详情 → 插件接入”和“行为审计 → 采集状态”按 Agent 直接展示：插件未安装/已安装/未发现 Agent、宿主未启用/已启用、授权待审阅/已授权/受管信任/管理员授权取消或失败/未知、本地接收器状态、最近 15 分钟 Hook 事件到达时间。安装、宿主授权、接收器和事件到达分别展示各自状态。后台每 5 分钟读取本地配置，观察有效期为 8 分钟，本地观察的宿主信任保持未知；原生授权在安装、升级、策略应用所需校验和手动诊断时核验。同时要求客户端报告未过期，接收器使用独立的 30 秒观察窗口。未发现一个目标 Agent 不再阻止检查另一个。

**English:** With no saved runtime override, the platform enables Agent logs and Hooks in audit mode, leaves system collection off and automatically installs/updates ordinary plugins for discovered Codex and Claude Code hosts. After enrollment and policy delivery, the main daemon collects logs and starts its in-process Hook receiver automatically. Existing global/device policies and explicit disabling are preserved; content capture, redaction and truncation continue to follow audit policy. Native host trust and managed-installation administrator authorization still require the appropriate user action. The daemon and its Hook receiver continue running when the desktop exits. Older protocols require a client upgrade for the new channel/mode target; their existing manual receiver controls remain available when no explicit policy owns them.

The platform shows installation, enablement, native authorization, receiver state and recent event arrival separately. Installation, host authorization, receiver health and event delivery have separate statuses. Local configuration observations run every five minutes, expire after eight minutes and report unknown host trust. Native checks run during installation, upgrades, required policy application checks and manual diagnostics. Client and receiver freshness are checked independently. Missing hosts do not prevent checking other targets.

人工验收清单 / Manual checks：① 全新客户端接入后继承默认策略，日志与 Hook 自动运行；② 全局关闭、单台覆盖关闭及恢复继承；③ 本机没有某个 Agent 时其余目标继续接入；④ Codex /hooks 待审阅与完成信任的状态变化；⑤ 受管授权取消/失败，平台保持具体状态；⑥ 桌面重开后的 Hook 自动恢复与真实事件到达；⑦ 中英文及窄屏下安装、授权、接收器和近期事件均可读。自动化回归和现有设备实页检查不代表全新安装、每种宿主授权和重登系统均已现场验收。

2026-10-07 验证：相关 Python 回归 67 项通过，观察有效期调整后相关 44 项再次通过；Go 客户端包测试和构建、平台构建及 i18n 检查通过。现有设备平台实页已核对 Codex 0.160.1 的安装、启用、授权、接收器及持续到达事件，Claude 授权保持未知；中文、英文及 390px 布局已检查。扩展 Go 测试中的 `TestDiscoverFindsSupportedAgentsAndSkills` 因发现数量与期望 14 不同失败，尚未确认其基线，不计为全套通过。新 Go 构建未替换正在运行的客户端，缺失宿主继续协调分支已做隔离回归，仍需新版客户端实机验收。

**English validation:** 67 relevant Python tests passed, with 44 rerun after the freshness change. Client package tests/build, platform build and i18n checks passed. The existing device showed Codex installation, enablement, authorization, receiver health and arriving Hooks; Claude authorization remained unknown. Chinese, English and 390px layouts were inspected. The broader Go inventory test failed its expected count of 14; its baseline remains unverified. The newly built Go binary has not replaced the running client, so missing-host reconciliation still needs live upgraded-client acceptance.


## 系统网络连接快照

桌面“运行治理 → 系统采集”统一开始和停止。平台“行为审计 → 系统事件”选择“网络连接快照”立即筛选；列表优先显示 Agent、程序、远端 IP:端口、协议、采样状态及时间，同一观察实例可展开原始快照。旧客户端显示网络状态未报告，不根据系统采集在线推断网络正常。

这是约每秒的套接字快照，仅覆盖策略内且已确认归属的进程；短连接、瞬时失败可能漏采，消失不证明关闭。TCP 状态不是 HTTP 结果。方向、域名、累计收发量和完整时长当前不可得；不采集网络正文。请先升级平台，再更新客户端并通过页面停止/重新开始以更新采集组件。历史与未 ACK 队列保留。技术路线及签名边界见 [采集器说明](../client/macos-enforcer/README.md#网络连接快照--network-socket-snapshots)。

**English:** Start/stop through Runtime governance → System collection. Filter Network socket snapshots under Behavior audit → System events. Snapshots show attributed Agent/process, remote IP:port, protocol, sampled state and time, with original observations retained. This is bounded polling, not full flow telemetry; short connections and transient failures may be missed. Missing sockets do not prove closure. Direction, domains, transfer totals and full duration are unavailable. Network health is independent; older clients remain unreported. Upgrade the platform first, then restart collection through the desktop. History and unacknowledged queues are retained.

2026-10-07 实机结果：已授权启动，真实 Claude 请求本地受控服务及其 SessionStart Hook 子进程产生 12 条网络快照（9 个观察实例），包含 IPv4/IPv6 TCP 建立、CLOSE_WAIT 和 UDP 未知；同目标连接未合并，非目标程序未纳入。平台入库、上传确认、中英文详情、停止回执与进程回收通过，停止后待上传 0。该测试没有真实模型成功响应，Hook 子进程不代表模型驱动工具。取消授权已通过：页面明确提示已取消、未启动，未残留采集进程或控制 socket；实机离线恢复/权限拒绝/组件失败仍需逐项完成，见 [详细验证状态](../client/macos-enforcer/README.md#2026-10-07-验证状态--validation-status)。

**English:** Live authorization, Claude requests to a controlled local stub, startup-Hook children, 12 network snapshots across 9 observation IDs, scope exclusion, upload confirmation, bilingual platform details and clean stop passed with zero backlog. This does not establish successful model calls or model-driven tools. Live cancellation also passed, with an explicit cancelled state and no remaining collector or control socket. Live offline recovery, permission denial and component failure remain pending.

人工验收清单（两种语言）：① 启动授权/取消、重复点击；② 真实 Agent 与其子进程访问本地受控服务，分别核对 TCP 建立、对端 FIN 和不在范围的程序；③ 同目标多次连接的观察 ID 不相同；④ 本地记录、上传 ACK、平台记录序列、页面详情一致；⑤ 网络不可读/组件失败不能显示网络正常；⑥ 离线积压恢复后无丢失/重复；⑦ 停止进程回收及队列处理；⑧ IPv6、长路径、窄屏、详情原始记录及抽屉切换宽度；⑨ 完整瞬时失败事件、完整流关闭、流量统计与真实模型调用分别记录未验证/不支持，不能以 Hook 测试或独立测试替代。


## Agent 小版本兼容与接入检查

Hook 插件接入按宿主实际提供的接口判断，不使用 Claude/Codex 精确版本白名单。后台接收器每轮检查后等待 60 秒，策略协调器按原周期检查；这两条巡检路径直接读取用户级插件配置、安装记录和产品文件，不启动宿主进程。Codex 读取 `config.toml` 中 AIDR 的本地 marketplace 与插件 manifest；Claude 读取 `installed_plugins.json`、`settings.json` 和插件 manifest。无法读取、格式不支持或来源不确定时保留未知，不猜测为卸载。本地报告使用 `adapter_available`，不宣称原生接口已验证，宿主版本留空、Hook 信任保持未知；文件及配置摘要继续上报并比较变化。

安装、升级、策略应用所需校验及手动诊断仍使用原生接口。Codex 的 App Server 即使查询参数为 `forceRefetch=false`、`marketplaceKinds=["local"]`，启动或查询也可能刷新 Git marketplace 并留下源码暂存副本，因此不用于后台周期巡检。原生接口可用、配置已启用、宿主信任、事件到达及日志采集进度分别核验。

原生查询和插件 CLI 调用使用独立的进程组（macOS/Linux）或 Job（Windows）。调用取消、超时或结束时回收本次调用所属的宿主及子进程；Windows 宿主先挂起创建，加入 Job 后才开始执行。查询回收不按进程名称查杀其他 Agent。已产生的 marketplace 缓存仍由宿主自身管理。

**English:** Periodic receiver and policy checks read user-scoped plugin settings, installation records and product files without launching the host. Local observations report `adapter_available`, unknown hook trust and no host version. Unreadable or unsupported sources remain unknown. Native checks remain available for installation, upgrades, policy application and manual diagnostics; Codex startup may refresh Git marketplaces even with local-only query parameters. Native queries and plugin CLI calls own a process group on macOS/Linux or a Job on Windows, reclaiming their processes on cancellation, timeout and completion. Windows hosts join the Job before execution. Existing marketplace caches remain host-managed. Configuration, native compatibility, trust, event delivery and log collection progress are separate evidence.

人工验收 / Manual checks：① 更新 Go 组件并重启客户端，跨越接收器及策略巡检周期确认不再为巡检启动 Codex / Claude；② 在测试配置中启用、停用插件及修改产品文件，核对平台变化报告；③ 配置损坏显示未知而非卸载；④ 安装、升级和手动诊断仍可执行原生校验；⑤ 中英文“插件来源与最近变化”和桌面接入状态文案不把配置启用当作授权或事件到达，窄屏长文案正常换行。历史暂存副本的清理独立执行。

Agent 日志按实际记录格式解析，同一格式跨小版本继续采集用户输入、过程回复、最终回复和工具操作。不再因陌生版本制造覆盖缺口；真实解析失败、截断、会话身份缺失仍按原机制报告。旧游标中纯版本提示保留历史但不再影响当前覆盖状态，原游标位置、队列、冻结批次和事件身份保持。

系统级受管安装不限定 Codex 0.159.0。安装前检查宿主原生查询接口；Codex 安装后及受管策略应用前，核对全部产品 Hook 的原生命令、启用状态、system 来源和 managed 信任，确认后才应用运行目标。安装前探测不代表受管配置已生效；Claude 当前仍按原生插件接口及系统配置检查，独立加载/信任保持原证据边界。系统事件采集继续依赖操作系统能力、授权、签名、有效进程归属策略和实际订阅，与 Agent 精确版本无关。

**升级顺序：先更新平台后端与前端，再更新桌面客户端及 Go 采集组件并重启客户端。** 新状态 `interface_compatible` 需要配套平台接收；旧客户端 `adapter_target` 报告仍可读取，并标为旧版验收报告。无需更改 Agent 配置、删除日志游标或重新创建采集队列。未知版本不自动获得信任或审批权限；拦截仍要求有效签名策略和匹配的决定。

**验证与人工清单：**本次以真实 Codex 0.160.1 完成只读插件接口与受管安装前探测；兼容协议样本覆盖不同小版本/预发行/厂商版本、方法缺失、格式错误、原生读取失败、日志正文与工具关联、旧版本提示和真实历史缺口。其他真实 Agent 版本、管理员安装/升级/移除及新包端到端运行仍需分别实机验收。受影响 UI：桌面“运行治理 → 接入与采集”、平台“客户端详情 → 插件接入”及采集诊断。人工检查：① 中英文状态及英文长文案；② 更新后自检、安装/更新与原生信任分开显示；③ 真实新问答核对输入、过程/最终回复、工具及 Hook 平台 ACK；④ 受管安装取消/批准、升级/移除，以及配置未加载时的具体错误。未新增 UI 单元测试。

**English:** Integration is checked against native interfaces, not exact Agent release allowlists. Codex uses the local App Server and negotiates the legacy CLI only on an explicit method-not-supported response. Read errors and ambiguous sources remain unknown. Logs are parsed by observed record format; unfamiliar versions do not create coverage gaps. Real format/identity failures remain visible, and existing cursors and queues are retained. Managed Codex installation checks the inspection interface before authorization and exact native managed Hooks before applying the target. Claude's independent loading/trust evidence remains limited to the existing contract. OS collection is independent of Agent releases. Upgrade the platform first, then the desktop/Go components and restart the client. Native 0.160.1 read-only probes and protocol fixtures passed; other physical versions and the updated managed install/upgrade/removal still require acceptance. Check both languages, installation/trust separation, fresh conversation delivery and managed authorization/error flows manually.

## 桌面运行治理工作台

运行治理任务会核对当前策略版本和内容，其中包括系统采集范围 `system_targets`（选择方式及产品列表）。客户端同时兼容旧策略未提供该字段或值为 `null` 的情况。版本更新导致的旧任务使用 `aidr_desktop_task_superseded`；相同版本的内容不一致使用 `aidr_desktop_policy_content_mismatch`，两者均不表示新任务已经成功生效。升级客户端后，在“策略与审批”的模式状态栏点击“重新应用当前策略”重试当前版本的失败任务，并分别核对各通道的实际模式及应用版本。此操作沿用已保存的目标及工具规则，不会重新发布策略；仅有任务执行权限的用户可操作，有任务正在执行时不可重复提交。

Runtime governance tasks compare both the current policy version and content, including `system_targets` (selection mode and products). Older policies may omit this field or set it to `null`. A superseded task and a same-version content mismatch have distinct status codes; neither confirms successful application of a newer task. After updating the client, use **Reapply current policy** in the mode status area of **Policies and approvals**, then check each channel's applied version and mode. This retries the failed task using the saved target and tool rules without publishing another policy. Task execution permission is required, and an active task prevents duplicate submissions.

人工验收：中英文界面核对上述两种错误提示；重试后确认目标版本与 Hook 应用版本一致；旧版本任务不得覆盖新版本；确认系统采集产品范围与原配置一致。本项不新增 UI 单元测试。

“接入与采集”使用双栏布局：左侧按产品选择，右侧分别显示日志策略、Hook 配置和操作。Qoder 保留一个产品入口，默认同时显示共享 Hook 的安装操作与 CLI 格式的日志来源状态；QoderWork 在详情中单独选择，状态和操作继续使用各自的产品标识。顶部集中显示共享接收器和上传回执，暂停时就近提供重试入口。安装、适用的宿主信任、平台启用、事件到达分别展示。WorkBuddy 的设置型 Hook 接入无需独立的插件授权或启用，不显示这两项；客户端启用后自动安装配置并申请平台策略，随后在 WorkBuddy 发起新操作验证。当前桌面接口没有逐产品到达回执，因此最后一步提示在平台查看，不能用共享通道运行或 ACK 代替某产品的真实事件。

“系统采集”左侧为开始/停止、已生效模式、进程/文件及独立网络状态、待上传与最近确认，右侧为最近事件。主导航、页签和左侧控制不随事件滚动。网络保持连接快照语义。连接标识、版本、权限说明与原始事件诊断按需展开；命令、路径和退出结果保持原文。

**English:** Runtime governance uses a product rail and independent details pane. Qoder entries share one brand navigation item while retaining separate capabilities and actions. The receiver and upload receipts are shared channel observations, not per-product event-delivery proof. System collection keeps controls on the left and recent events on the right; tabs and controls remain visible while events scroll. Network status remains independent and describes socket snapshots. Existing enrollment, host authorization, start/stop and durable upload behavior are retained.

OpenCode 暂不提供新的行为审计接入：客户端采集导航、平台能力列表及新增日志来源选项已隐藏。旧策略中已选择的 OpenCode 保留，修改其他设置不会自动移除它；旧策略仍在采集时，采集状态继续显示实际情况。历史记录可通过“全部 Agent”查看。Skill 目录管理和模型配置功能保持原有范围。

**English:** OpenCode is not offered for new audit collection setup. Collection navigation, capability lists and new log-source choices omit it. Existing policy selections, active-source health and historical audit records remain compatible; historical records remain available under All agents. Skill inventory and model configuration keep their existing scope.

WorkBuddy settings Hooks require no separate native plugin authorization or enablement. Its desktop view shows configuration installation, platform policy and event delivery. Verify a new host action on the platform after enabling collection. Manual checks: compare WorkBuddy with Codex, inspect both languages and a narrow viewport, and confirm that a disabled policy or a delayed report remains visible even when configuration is installed.

人工验收清单 / Manual checks（不新增 UI 单元测试）：

- [ ] 首次进入、反复切换两个页签、滚动事件与展开诊断时，页签和左栏保持稳定。
- [ ] 切换各 Agent 和 Qoder 各入口；无日志/Hook 能力时不展示可用采集操作。
- [ ] 安装、授权、策略启用、事件到达的状态分开；报告过期和未报告保持未知。
- [ ] 中英文 1080×720 和 900×620 窗口，长故障原因、路径、命令、IPv6 不覆盖相邻内容。
- [ ] 启用 Hook、安装更新、移除、宿主审阅和重试接收器的真实流程；操作中重复点击被禁用。
- [ ] 系统开始授权、取消、权限不足、启动失败、真实事件上传与停止补传；网络未采样时不显示网络采集正常。

## 桌面系统采集（2026-10-05）

**入口：运行治理 → 系统采集。** 在平台启用该设备的系统通道，并在“策略与审批 → 系统采集策略”发布有效的 Agent 可执行文件归属策略。平台服务使用 `AIDR_POLICY_SIGNING_KEY_FILE` 指定私有签名密钥；桌面通过已有设备连接取得公开验签公钥，并在 root 私有目录固定该信任。

策略有效期是设备认证租约，不要求管理员周期性手动发布。设备认证后，平台在剩余有效期进入续签窗口时自动签发内容不变的新版本；过期后重新连接也会续签。自动续签写入管理操作审计，不出现在管理员配置历史列表中。管理员修改 Agent 目标或文件规则时仍需显式发布新策略；停用系统通道、无有效 Agent 目标或签名服务不可用时不会续签。

点击“开始采集”后，macOS 请求管理员授权。首次安装或更新部署组件，普通用户桌面通过独立 root 管理进程采集和上传。缺少完整磁盘访问权限时，页面提供原因、系统设置入口和组件定位；为 aidr-enforcer 授权后重新开始。管理员授权与 FDA 分开处理。

只有实际 ES 订阅后的心跳才显示“采集中”。页面提供最近 12 条进程事件、最近上传 ACK、待上传数量和错误原因。仅审计模式采集 Agent 及其后代的 fork/exec/exit；拦截模式额外订阅文件打开授权并执行已有系统规则和进程响应。根据有效签名策略建立归属，需在策略生效或模式切换后重新启动对应 Agent。

### 仅审计与拦截模式

在“客户端管理 → 默认客户端策略”分别设置 Hook 与系统防护模式；新配置默认仅审计。单个客户端策略可覆盖，勾选继承后恢复全局配置。Agent 日志只有采集开关，不提供拦截模式。正文范围、脱敏和上报许可继续使用现有审计策略。

Hook 仅审计记录宿主事件；采集故障报告缺口并放行。拦截按“工具使用审批”的有效签名规则允许、拒绝或申请审批。明确的模式策略决定执行行为，公钥用于验签。存量没有模式字段的配置显示“保留原有模式”：客户端首次读取时保留旧审计/控制行为，管理员明确选择后不再由公钥推断。旧客户端继续保持原行为，平台提示升级，不能把旧协议报告当作新模式生效。

Hook 与系统模式可分别保留当前设置。平台下发任务和客户端策略时统一空值表示，客户端比较时也按相同语义处理；模式实际变化仍要求匹配当前策略。因旧版空值比较问题失败的任务，可在更新平台后使用现有“重试”入口重新应用，历史失败记录保留；以新任务回执及各通道的实际模式、策略版本确认生效。

**English:** Hook and System modes can independently preserve their current settings. Task and client-policy delivery normalize empty values, and client comparisons use the same meaning while still rejecting actual policy changes. After updating the platform, retry a task that failed due to the older empty-value comparison through the existing Retry action. Historical failures remain; verify the new receipt and each channel's actual mode and policy version.

系统采集由已授权的独立 root 进程每 10 秒读取模式。切换时关闭旧订阅、限时补传，再按新模式启动原生组件；只有原生健康报告确认后才展示已生效模式。切换失败显示错误，需修复后重新开始。桌面保持普通用户权限。平台“配置模式”和“客户端已生效模式”分别展示，保存成功只代表目标已更新。系统仅审计不采集文件授权结果；文件规则的实际允许/拒绝记录属于拦截通道。

**English:** Configure Hook and System protection independently in Default client policies, or override them for one client and restore global inheritance. New configurations default to Audit only; Agent logs remain collection-only. Audit scope, redaction and upload permissions stay unchanged. Hook audit failures allow normal operations with a coverage-gap report. Intercept uses signed allow/deny/ask rules. A pinned key verifies authority; explicit mode controls execution. Pre-mode configurations preserve historical behavior until explicitly changed; old clients require an update before reporting mode application. A running privileged system collector polls every 10 seconds, stops and drains the previous subscription, then starts the selected mode. Only native health confirms application. Failure is reported without claiming success; the desktop remains unprivileged. Audit records process events; file authorization and process response belong to intercept mode.

人工验收：全局仅审计 → 单机拦截覆盖 → 恢复继承；分别核对两个通道的目标、实际模式、报告时间和失败原因；临时测试文件在审计时可读、拦截命中拒绝时读取失败；Hook 拒绝和审批只在拦截模式触发；停止、离线补传、取消授权和权限不足；中英文和最小窗口布局。测试后恢复策略及运行状态，清理测试资源。

系统模式至少连续往返切换两轮，并保持签名规则版本不变，确认复用缓存时仍能启动、上传且待发记录排空。不同组件对签名信封的 JSON 排版可能不同；版本一致时按相同的 payload 和 signature 判断同一策略，签名内容变化和旧版本仍拒绝。

2026-10-06 本机开发包已完成两轮系统模式实测：三次仅审计读取成功，两次拦截读取返回 EPERM；五次探针的 exec/exit 和两条拒绝记录均上传，平台页面可见。恢复原策略后，日志、Hook 和系统通道均报告当前版本已应用，系统保持仅审计运行且待上传为 0。此前发现的签名信封排版导致误报版本冲突、旧策略空字段导致协调任务误判已过期，均已修复并回归。该结果限于 SIP 关闭、ad-hoc 签名的开发环境；本轮没有补验真实宿主中的 Hook 拦截/审批、真实 FDA 拒绝或正式发行条件。详见 [系统模式验收记录](../experiments/macos-es-poc/ACCEPTANCE.md)。

**English:** On October 6, two live system-mode round trips passed: three audit reads succeeded, two intercept reads returned EPERM, and all five probes' exec/exit events plus both denials reached the platform. Original policies were restored; all three channels acknowledged the current runtime version, with system collection running in audit mode and no pending uploads. Envelope-format and legacy-null reconciliation regressions were fixed. This verifies the SIP-disabled, ad-hoc development environment; native-host Hook interception/approval, actual FDA denial and production distribution remain outside this run.

同日 Hook 补验：当前代码构建的独立接收器已通过真实 Codex 0.160.0 的审批批准/拒绝、实际标记文件对照、终态回执及 11 条原生 Hook 的精确上传核对。Claude 模型持续服务端错误，未进入工具调用，仍未完成。该测试使用平台 API 提交审批决定和独立 CLI 控制配置；网页人工点击审批及桌面显式模式切换不由此结果替代。详见 [Hook 验收记录](../experiments/aidr-agentlog/ACCEPTANCE.md)。

**English:** The subsequent native Hook test passed Codex approval/denial, marker outcomes, terminal receipts and exact upload matching for 11 Hooks. Claude model errors prevented any tool call. API-submitted decisions and isolated CLI control do not replace manual browser approval or desktop mode-switch checks; see the Hook acceptance record.

“停止采集”先停止订阅并回收原生进程，再进行最多 5 秒补传。未确认记录持久保留，下次开始继续上传；停止与排空分别报告。关闭窗口仍继续采集，持续至主动停止或进程退出；重启机器后需要手动开始。在线设备自动续签相同配置；平台关闭系统通道或凭证被拒绝会停止采集。断网时保留待发记录，离线租约到期的控制行为按策略处理。

开发包只支持 SIP 已关闭的环境，安装/更新时将 ES entitlement 嵌入 ad-hoc 签名；未变更的组件再次启动不重新签名。客户端不会修改 SIP。正式包仍须 Developer ID、Apple ES 授权及公证。开发测试不等同正式发行验收。

本轮已通过真实桌面开始、系统订阅、Claude 进程事件、严格上传确认、平台展示、停止与 root 进程回收：首轮 22 条、第二轮 60 条进程事件，两轮桌面最近 12 条均逐项匹配平台记录，停止后待发 0 且平台收到停止健康记录。再次启动的原生 ES 组件哈希和修改时间不变；退出并重开桌面后继续显示同一采集会话。取消授权、缺失组件、完整磁盘访问设置入口及组件定位已实测；中英文界面和构建检查通过。并发操作互斥及权限错误码由自动测试覆盖；快速连点授权窗口、真实 FDA 拒绝、本次桌面流程的离线停止补传和正式发行环境仍需人工验收。详细流程与[人工验收清单](../client/macos-enforcer/README.md#人工验收清单--manual-acceptance)同步维护。

**English:** Open **Runtime governance → System collection**. Start authorizes installation/update and launches an independent root collector while the desktop remains unprivileged. Full Disk Access is a separate requirement. Only a real ES subscription heartbeat enables Collecting. Stop unsubscribes, reaps the native process and attempts a bounded final upload; remaining records are retained for the next start. Development signing occurs only on install/update with SIP already disabled. Production requires Developer ID, Apple ES approval and notarization. The local desktop-to-platform flow, 22 real process events, clean stop, cancellation and missing-component errors passed; a real FDA denial and production distribution remain separate acceptance items.



## 2026-10-04：Hook 接收故障的审计与控制语义

仅审计接入遇到本地 Hook 接收或持久化故障时不拒绝普通工具，宿主会收到稳定审计缺口提示。工具控制仍要求有效授权；模式未知、配置不可读或桥接程序缺失不能按仅审计处理。原生宿主权限仍独立生效。

包含本次修复的客户端在“Agent 运行治理”持续显示最近缺口原因和历史时间，恢复接收器不会补齐旧记录。诊断只保留本机最近一次，不是事件 ACK 或平台丢失数量。源码不会自动更新已运行二进制；本轮未替换日常客户端。

双语手验：使用独立测试设备，确认仅审计后让自有接收器不可用，在新宿主会话调用临时目录中的 /usr/bin/true；检查没有 AIDR 拒绝、宿主有缺口、客户端提示与时间持续可见。恢复后另验新事件 ACK；控制模式同样故障必须拒绝。安装、生效和详细清单见 client/aidr-plugins/README.md。

## 三通道历史验收记录（2026-10-04）

最新续验：普通Codex0.160.0的18条真实Hook、七组Pre/Post及双语网页通过，另六条真实Hook通过非空冻结积压安装包更新，24条全部严格ACK。标准测试包后台301秒的300条受控输入全部到达平台并ACK，队列采样峰值2，App/接收器RSS峰值64.73/23.23 MiB；这不是300次真实Agent调用。

本机开发签名的真实ES仅采集现已通过订阅、精确身份和平台链路：180.666秒，主监视4493条记录，加上先前拒绝未签名Codex直接根的36条记录共4529条唯一记录；暂停上报积压4423条，恢复后字段/身份匹配、待发/冻结0、报告缺口0。独立父进程预期的1000个后代全部匹配exec、exit及归属根；受控sleep与孤儿进程匹配。再次启动保留同一状态目录，新增53条后平台共4582条，中英文真实网页确认sleep及仅采集/停止时禁用终止。桌面系统采集入口及其最新验收见上节；正式产品签名/发行资格仍需独立验证。

当前内置Codex二进制实际未签名，不能作为已验证的直接根；临时签名测试根启动的新Codex任务在85秒预算内请求超时，没有工具执行记录，Codex执行sleep仍未通过。标准安装包Hook链路连续前台601.007秒（601个焦点样本、600条受控输入）及随后后台301.001秒（301个后台样本、300条受控输入）均通过；900条全部与平台唯一记录及本地durable ACK身份/序号匹配，每阶段待发/冻结0、队列采样峰值2，同一接收器持续运行。真实中英文客户端状态检查通过；这不代替runtime_watch真实relay长时验收。隔离41893设备已通过产品预览/CAS恢复继承且未配置（新版本0:4）、上报关闭，凭证8吊销；测试App/接收器/socket/基础工作者回收，测试Home原目录恢复，用户确认语言恢复。1226条平台Hook全部匹配本地durable ACK，数据库、游标、回执和事件保留。日常LaunchAgent在19:24:03改为已安装Applications客户端，区别于上午开发版基线且不是测试路径；来源尚未确认，没有覆盖或重新加载，等待用户选择保留或恢复。ES自有进程已退出，临时平台签名配置已移除，只用产品API新增允许/空根修订3，测试策略历史与事件保留，原策略不存在的状态没有被伪装恢复。日常配置和基础服务未改变。详见主仓库已有验收记录。

**English:** Ordinary native Codex 0.160.0, bilingual details and a nonempty frozen-batch package upgrade passed. Local development-signed, collection-only ES now passed real subscription, exact identities for 1000 descendants, durable backlog recovery and bilingual system-event pages. The first live round retained 4529 unique records; a same-state restart added 53. No reported source gaps or pending runtime records remained. The actual Codex executable is unsigned, and its bounded controlled task timed out before a tool result; direct Codex-root and Codex-executed sleep acceptance remain incomplete. Packaged Hook intake/upload passed 601.007 seconds foreground and 301.001 seconds background; all 900 labeled inputs matched unique platform records and durable ACKs, with zero pending/frozen queues. Actual bilingual client status views passed. This does not prove runtime-watch GUI stability. Temporary ES signing configuration was removed and empty allow-only revision 3 retained policy history. Product preview/CAS restored isolated inheritance at revision 0:4 and reporting disabled; owned processes/socket were reclaimed, credential 8 revoked and the test Home restored. All 1226 retained platform Hooks match durable ACKs, with fixture and native counts recorded separately. The daily LaunchAgent differs from the morning developer baseline and now points to the installed application; it was not overwritten or reloaded and awaits the user choice. Customer automatic authorization and formal distribution remain unverified.

以下分项保留先前执行证据；当前完成状态以本节开头和已有验收记录的最新小节为准。

本节以本轮代码和实测为准，独立于既有 P1/P2/P3 出口及普通插件接入验收。平台默认客户端策略和设备覆盖复用现有权限、继承、预览/CAS及版本；运行目标包含 Agent 日志、插件 Hook、macOS 系统事件。运行目标、审计采集许可、设备上报许可和控制策略分别生效，正文范围与脱敏仍使用既有审计配置。

日志循环已接入现有 Go 用户后台，独立于页面和桌面自有 Hook 进程，不新增服务。新客户端以协议3回报各通道自己的策略版本、观察时间、传输、待发及严格ACK时间；旧客户端的未报告通道保持未知。关闭日志目标停止新读取，已有冻结积压继续上传；重新开启采用持久化恢复边界并报告停用期间缺口。平台/设备绑定目录保持，凭证轮换加入旧工作循环后刷新传输，不重算冻结批次。

代码与自动回归已通过，本机开发版Go侧车已获批准升级，实际平台报告为协议3。独立41893设备已完成Codex0.160.0日志目标0:1的真实自动管理、持久化、严格ACK与中英文网页：两会话18事件/9操作，退出码0/7有原始结构依据。Go游标的可选call_turns[].tool与服务端严格契约不一致导致冻结批次422；已批准补齐有界可选字段并自动重载，原15条冻结批次ID/摘要保持后恢复，重启不重复。无需数据库迁移、重置队列或修改已确认事件。

这次自动读取使用现有Go基础工作者的独立安全配置，未手动启动aidr-sync或Hook接收器；由测试程序启动工作者，不代替桌面点击或安装包验收。前一日志分项结束时已用预览/CAS恢复继承且未配置（0:2）、关闭上报并吊销当时凭证；原数据保留。本轮续验状态和收尾要求见本节开头。日常目标及正文/脱敏未修改，本轮0.160私有候选未替换日常侧车。Codex0.160.0普通插件现已通过用户原生审阅/信任、七次真实工具调用的18条Hook严格ACK及中英文网页详情，精确0.160.0加入普通插件已验版本；受管Codex仍限0.159.0。另一次真实单工具任务的六条待发Hook及两条非空冻结批次通过标准安装包更新、原摘要恢复和ACK核对。桌面系统采集入口已接入独立 root 进程；系统采集与 Hook 各自验收。详见主仓库experiments/aidr-agentlog/ACCEPTANCE.md最新记录。


Hook采集gate单独持久化在既有hook_meta，关闭后拒绝新记录，已确认的重试保留原身份，旧冻结字节和摘要保持；上传不受gate关闭影响。已应用的桌面监督代码使停用中的自有接收器持续排空，确认待发为0后回收，关闭再开启不因同一配置反复启动。通道实际版本从已持久化gate和原生停止证据读取，不从待应用目标猜测。连续恢复设21次上限，到达后需显式重试；既有退避和配置/队列绑定保持。新增字段可缺省，旧队列无需重建。

自动检查另通过最终Go相关三包race、冻结失败ACK重试、停用重启及确认后事件幂等；隔离Rust12项含真实自有侧车离线停用/恢复（PID相同、待发1）、回收/轮换/上限及停止身份投影。现有桌面i18n29项和平台i18n22项通过，平台构建10.99秒。更新后的标准桌面测试包已实际启动，平台自检/安装/重复安装任务通过，跨包冻结积压及真实Hook闭环已补验；15分钟负载及真实ES继续独立验收。

系统通道新增仅采集实现：Go启动前有界核验原生能力，原生仅订阅NOTIFY_FORK/EXEC/EXIT；独立验证签名后保留Agent映像身份、版本和期限，移除控制规则与拒绝动作，使用独立采集缓存，不读取终止命令。原生采集边界及Go兼容回归通过，桌面入口的真实订阅验收见上节。服务端/页面区分“仅采集运行中”与“控制在线”的补丁已获批准并应用，后台已自动重载；真实 ES 仅采集状态已在桌面链路核对；仅采集时服务端拒绝新终止请求，不改写既有回执。桌面日志重试按钮禁用条件覆盖缺陷已随补丁修复并应用，真实桌面分支仍待验。

系统非特权条件预检新增在Go侧，检查结果不作为运行或授权证据；桌面“系统采集条件”中英文只读入口已应用，新Go侧车支持该动作，实际标准测试包双语页面已确认签名未验证、固定组件缺失及授权/订阅未知。开发版原生界面另按安装形态复验。系统采集通过 macOS 管理员授权按需启动独立 root 进程，关闭订阅与补传由该进程管理。本机可用签名身份数量为0，不能用开发签名或既有插件授权代替系统通道实机验收。

系统既有队列新增非特权有界补传函数，退出时复用5秒/8次预算；停止监视与已确认排空分别报告。离线、暂停上报、无效ACK保持冻结字节并退避，认证拒绝保留队列并返回；预算耗尽不能报已清空。受控HTTP/SQLite回归覆盖300条记录、限次、重启、冻结恢复、错误ACK、取消与错误设备。桌面停止复用这条有界补传链路；停止后剩余记录等待下次开始补传。

系统仅采集模式另补齐Go管理层异常退出的回收路径：原生控制管道断开记录既有稳定原因码，原子通知主循环停止采集并走既有收尾。非特权子进程回归直接调用生产控制读取器，真实关闭OS管道并核对断开健康JSON；没有创建ES客户端，真实取消订阅及安装包故障回收仍待验。


**已批准应用与现场核对：**两份审查补丁已应用；随后用户批准开发侧车更新及相关自有进程重启。按prepare-update、同路径原子替换、reconcile-service及既有Tauri重载流程，基础Go45612→35033、开发桌面85502→38017、自有Hook85757→38088，后台85148未再次重启。LaunchAgent程序参数和配置结构保持，设备连接配置摘要不变；未安装新服务、改平台策略或操作ES。旧二进制、连接配置及队列数据库私有备份保留，新随包二进制与候选摘要匹配。

真实channels-status/system-check均返回成功；平台实际收到协议3，中文/英文网页Hook运行、状态传输、待发及事件ACK均已核对。此前日常抽样1839条ACK身份/序号与平台一致，升级前1806条保留；此计数不是固定总量或长时证据。开发版预检package_unverified、系统授权/订阅未知，正式包/ES尚未据此通过。日常目标保持未配置、日志旧心跳10月2日17:46:42；独立41893已通过0.160.0日志自动采集和网页。0.160日志支持与插件信任、实际Hook触发及受管兼容分别计状态，升级侧车不等同全部宿主能力通过。

本轮直接使用更新后的开发侧车，Rust12项11.71秒通过；此前Python8项、既有desktop i18n29项/web i18n22项、JS/Python语法与前端构建通过，Go三包race为已通过缓存。原生桌面自动操作工具无法识别非应用包开发进程，未通过启动另一已安装客户端绕过；系统条件/日志重试等真实桌面分支需人工核对。默认未配置日志/系统保持未报告，真实双宿主、系统collecting分支、三通道实际策略与15分钟负载仍未验。

客户入口为平台 **客户端管理 → 客户端策略 → 接入与运行** 或设备详情 **策略与审批 → 客户端策略** 配置目标；桌面 **Agent运行治理** 核对收到的目标与实际观察、执行原生信任/授权及故障重试；**行为审计 → 采集状态** 查看各通道独立诊断。普通客户流程不依赖开发用aidr-sync命令；支持新自动管理的安装包仍需分项实机验收后发布。


## 当前验收状态（2026-10-02，P3 续验）

原 P3-01～04 和阶段出口在既有 macOS、Claude Code 2.1.220、Codex 0.158.0-alpha.2.1 声明范围内已有验收证据。后续客户接入补强单独计状态：普通接入、自动接收器、标准安装包生命周期、正文权限与双语详情已验；macOS 原生受管授权与完整受管链路仍未通过，不因普通接入成功宣布全部完成。

本次独立 Claude 2.1.220 新会话 `aacc08e6-e9d2-48c8-b8f5-662788802483` 只调用一次 Bash，13.137 秒完成、CLI 退出 0、临时 marker 实际生成，六条原生 Hook 持久化并严格 ACK。用户报告的模型恢复已用该任务确认，不能扩展为长期供应商健康保证。已有 Codex 会话 `01a0fa4b-514d-7942-958f-bb4dfaaec873` 六条 Hook，以及新 Claude Pre/Post，均已在真实中英文网页核对会话/call、命令、工作目录、未知结果/退出码和详情关闭；网页不会把独立 CLI 退出 0 填入缺失的 Hook 证据。

真实冻结积压安装包更新已补验：暂停隔离设备上报，旧标准包 Go `d6860b94…` 的独立 Claude 会话 `e86e0482-5563-4164-b69a-65ddaf31c080` 在 10.007 秒完成一次 Bash；六条待发，其中两条构成非空冻结批次。正常 Quit 后恢复最新标准包 Go `ba96ba5e…`，自动接收器恢复，冻结字节及 SHA-256 `26d6f4726c42b9723fc4dcbbcbea5d91ca38e1f79dbc7162b2f898fbd2d56546` 完全保持。重新允许上报后六条全部 ACK；重放原冻结批次得到相同设备/stream/digest、accepted=2、durable=true，平台未新增逻辑事件。该证据是普通接入的真实冻结积压跨包兼容，不替代系统受管升级/移除或正式发行验收。

结束核对：41891 独立设备 `amc_475de6e4066e48fde2b0dbdd` 的 182 条已 ACK event_id/seq 与认证平台集合精确相同，待发/冻结 0；平台全部 388 条，既有 370 条摘要保持。默认运行目标 6/任务 21 和审计策略 31 保持；脱敏开启、三类正文关闭、采集开启/保留 7 天。设备“允许上报”已恢复；隔离后台、数据库及签名密钥未重启或重置。最新标准包运行 App 49019、唯一自有接收器 49088，既有私有基础工作者 29882 保持；终态为本次采样，不作永久计数。

真实测试用户准备前的基线：本次已有有限授权，系统级受管测试当时因真实运行冲突暂停：日常真实 Home 的基础工作者、接收器及业务 Codex 进程仍在运行；日常 bridge 为 ordinary。产品受管入口校验操作系统真实用户 Home，不能把私有测试 Home 冒充真实 Home，也不能把日常设备/队列切成独立测试设备。该基线阶段未调用系统安装/移除、未弹管理员授权。已私有保存基线；`/etc/codex/requirements.toml`、Claude macOS managed-settings 和产品 managed 目录均仍不存在；日常 bridge 与 launchd plist 字节、权限、所有者、摘要完全不变，不需要恢复系统配置。随后使用真实aidr-test用户和独立设备完成取消、批准及三种受管生命周期；当前系统变化和恢复待验项见下文。

历史实机覆盖 Codex 0.158.0-alpha.2.1、0.159.0、0.159.2、0.160.0、0.160.1 和 Claude 2.1.220。当前兼容判断见本文“小版本兼容与接入检查”；该清单记录测试证据，不作为接入白名单。

2026-10-07 在 ChatGPT.app 内置 Codex 0.160.1 验证了本地插件查询和 12 个已启用、持久信任的 Hook。真实新 CLI 会话的 SessionStart、UserPromptSubmit、PreToolUse、PostToolUse、Stop、SessionEnd 共 6 条事件已进入平台；会话日志中的用户输入、过程回复、最终回复和一次工具调用/结果分别核对。无退出码的日志工具结果保持未知。同日续验通过平台审批拒绝/允许，以及原生权限请求、压缩、中断和子代理生命周期；25 条生命周期事件覆盖全部 12 类声明 Hook，另有 11 条审批 Hook，均精确匹配平台入库和持久 ACK。此次历史续验时受管入口被 0.159.0 白名单阻断；当前已改为接口探测，但新版实际受管安装、升级或移除仍未完成。详见 `experiments/aidr-agentlog/ACCEPTANCE.md` 的 2026-10-07 记录。

Hook 接收器异常退出后遵循平台重试次数；默认首次启动后最多重试两次。次数用尽或故障要求人工处理时，客户端明确显示“自动重试已暂停”，检查原因后使用“运行治理 → 接入与采集 → 重试接收器”恢复。操作保留队列及上传身份；历史缺口不能补齐；当前连接状态见最新心跳。验收应同时核对新事件及平台 ACK。

**English:** Ordinary Codex 0.160.1 uses the native local plugin inventory. On 2026-10-07, twelve enabled, persistently trusted hooks were observed; a real CLI session delivered six lifecycle/tool hooks and session-log input, commentary, final response, and a tool call/result to the platform. Missing shell exit evidence stays unknown. A subsequent run passed API-driven platform allow/deny (11 Hooks) and native permission, compaction, interruption and subagent lifecycle (25 Hooks covering all 12 declared types), with exact platform/durable ACK matching. Approval used invocation-scoped trust; lifecycle probes used persisted trust. The version gate observed during that run has now been replaced by interface probes; actual managed installation, upgrade and removal on 0.160.1 still require acceptance. Manual browser approval and desktop mode switching remain separate acceptance items. When receiver retries pause or exhaust the platform budget (two retries by default), inspect the cause and use Runtime Governance → Integration & Collection → Retry Receiver. Queues and upload identities are retained; recovery does not reconstruct historical gaps. Verify fresh events and platform ACKs.

本次受影响 UI 为桌面“接入与采集”的接收器摘要、诊断及 Codex 兼容状态。人工复验清单：① 中文/英文检查 0.160.1 安装、启用、信任与兼容状态；② 正常退出再启动桌面，检查接收器自动恢复及新会话上传；③ 在独立测试设备制造重试耗尽，核对暂停提示与“重试接收器”恢复。①②已实测，③的新暂停文案未做现场故障注入。真实更新后会话 `01a113da-83a8-7781-8b5b-f1b5a554fa8a` 的 6 条 Hook 回执及 6 条日志逻辑 ID 与本地持久 ACK 已核对，网页显示过程回复、最终回复和工具记录。

**English manual checklist:** Inspect Codex 0.160.1 status in both languages; quit/reopen the desktop and verify automatic receiver recovery plus fresh uploads (both passed). On an isolated device, exhaust retries and verify the new paused-state guidance and recovery button (fault injection for the new wording remains pending). The post-update session above has six acknowledged Hooks and six log records matched by logical ID to durable local ACKs; the platform shows commentary, final reply and tool activity.

网页登录中断的一项实际原因已定位：验收 API 脚本用同一管理员再次登录，会更新 current_session_id，使浏览器原会话失效。API 核对与真实网页检查顺序执行，或使用不同的已有授权测试账号，避免验收相互干扰；不修改产品单会话鉴权。本次正确账号及新验证码登录后真实双语详情已通过。此前无响应的全部历史现象不据此一概归因。

新增会话 `e86e0482-5563-4164-b69a-65ddaf31c080` 的六条 Hook 列表及 Pre/Post 详情已在简体中文、English 真实网页补验，调用身份、完整请求命令、来源、未知结果/退出码与详情关闭均通过；设备仍为182条ACK，平台388条，未新增或改写事件。

唤醒状态属于客户生命周期补强。本轮续验确认12:58:09～12:58:27实际软件深睡18秒，随后HID活动提前唤醒；150次状态文件采样、进程和182条精确回执保持。第一窗口读取晚于实际唤醒，未计瞬态通过。第二次55秒窗口观察只取得3个样本，电源日志有WebKit睡眠通知30秒超时，未取得可配对的第二次Sleep/Wake记录；不计第二次睡眠通过。后台窗口显示旧报告，置前后自动恢复到13:10:17新报告，未操作自检/重连、未重启接收器；不能由该现象判定产品死锁。两次本任务唤醒计划均精确取消，其他系统计划保留。唤醒瞬间UI及物理合盖继续待验，原P3出口范围不变。

真实标准用户 `aidr-test`（UID503、Home `/Users/aidr-test`）的共享安装包已实际运行；独立设备 `amc_c5e50dc56eef04edf285c5c2` 心跳到达41891，桌面13525、产品临时基础服务13546和唯一自有接收器13593已核实。服务plist为0600/UID503，指向共享安装包；用户已允许仅该测试用户临时注册、验收结束通过产品入口移除。新设备原先未允许AIDR上报，通过真实配置接口启用后 `aidr_hook_runtime_received`，审计策略31实际收到。为该用户准备真实Claude2.1.220，SHA与现有官方宿主一致；使用正式任务重试25后，Claude2.1.220、Codex0.159.2插件均自动安装/启用，Codex原生信任仍为needs_review。未手动启动接收器或设置AIDR连接环境变量。

新会话 `76748d73-cd9e-4050-903a-298ceea4851c` 以实际UID503/Home在独立目录运行，60秒未完成模型/工具调用，已结束自有进程；零工具调用、测试marker不存在、原生退出143/aborted_streaming。SessionStart/UserPromptSubmit/SessionEnd三条真实Hook的本地event_id/seq与平台集合精确匹配，ACK3、待发/冻结0；该证据仅证明普通生命周期审计连接，不证明工具执行成功或当前模型恢复，也未替代真实网页。旧388条保留，未重置队列。受管Codex仍需真实0.159.0；官方macOS包下载未完成，不计版本准备或兼容验收通过。

41891默认目标曾临时从6切为7，仅Claude受管；产品移除后通过冲突检查、预览和CAS恢复原配置为8:0，其余策略及实际脱敏开关保持。用户已完成真实原生取消和管理员批准：取消时配置未写入；批准后Claude配置root/admin0644，16个受管Hook各一项，系统Go二进制root/root0755且SHA与包内ba96ba5e一致；本次新增配置、二进制、所有权回执、空原配置备份/previous及安装锁均已记录，移除Hook不等于这些文件全部消失。客户端已应用目标，唯一自有接收器17405自动恢复。Claude原生信任仍unknown，不以配置存在伪造信任。

批准后的独立会话 `2b7d2d16-a7ef-42ec-b28a-193ad08269ea` 用原生setting-sources选项隔离用户/项目设置，实际初始化plugin_count=0；SessionStart原生回执退出0，SessionStart/UserPromptSubmit/SessionEnd三种受管事件触发并严格ACK。设备共6条本地回执与平台event_id/source_seq集合精确一致，待发/冻结0，批准后的系统文件及日常基础服务摘要保持。四次Write/Read/Edit/Read任务在120秒未完成，零工具调用、文件未创建，退出143/aborted_streaming；只确认生命周期链路，未通过工具链路或模型恢复。另一次非推理models探测返回502，不将其视为推理超时的已确认根因。当前窗口工具无法操作另一OS用户GUI，原生交互由用户完成。41891真实中英文网页已逐条核对三种受管生命周期详情及关闭，投影event_id/序号4～6与本地和平台精确一致，结果/退出码/OS关系保持未知。包内aidr-managed-install重复安装退出0，16项Hook、配置与二进制摘要以及6条ACK保持，待发/冻结0；binary-ownership、claude-ownership、claude-previous按安装器契约更新最新预备份及回执，原配置备份保留。首轮核对误以为仅两份回执会变更，断言失败发生在产品命令成功后；更正测试预期后第二轮产品命令及核对通过，未据此改产品代码。用户随后在真实客户端执行产品移除并批准；root回执phase=removed、16项系统Hook均移除，socket消失，接收器停止，本地6ACK与平台身份精确一致、待发/冻结0，日常服务不变。产品保留7个系统文件（空managed-settings.json、二进制、两份所有权回执、original/previous备份、锁），因此没有完全恢复原始文件存在性。隔离默认策略已经预览/CAS从7:0恢复原普通接入配置为8:0，其他策略和脱敏开关保持；实际客户端应用8并回到普通接入。22:34用户正常Quit后实测桌面及接收器退出、socket消失，以真实UID503/Home通过产品uninstall-service移除临时基础服务和注册文件；6条ACK、待发/冻结0及日常服务7574/plist保持，后台11484未重启。22:35仅本次测试设备恢复暂停上报，并通过平台产品接口吊销测试凭证5，认证请求返回403；平台6条事件身份保持，默认策略8:0及脱敏31未变。测试连接配置、数据库、用户插件、共享验收包及前述7个系统保留文件继续保留，不宣称全部文件基线恢复；再次接入需新的测试凭证。GUI重复授权、真实系统版本更新、完整受管工具链路仍待验；原P3出口与客户补强继续分别计状态。

移除状态刷新补强：真实21:17平台报告中接收器已停止，但宿主字段仍沿用21:13:54移除前的已安装观察；21:23:54定时检查才更新缺失。原因是managed-removed原先只更新偏好/连接，没有更新observed-host文件。现在确认系统Hook缺失后立即记录未安装/未启用、检查时间、缺失码和未知信任，清除旧配置摘要与漂移；普通插件观察不被系统Hook移除覆盖，未知或无法读取仍按实际契约处理。不修改事件、冻结批次、数据库、ACK或历史应用时间。新增两项非UI Go回归覆盖报告、另一宿主/状态保持、重复移除、普通模式及无观察/读取异常；真实用户的验收包内产品命令验证状态刷新和6条ACK保持。该补丁的GUI原生移除尚未重跑，不把产品命令测试充作GUI证明。原运行包未替换；带修复的独立验收副本Removal State Acceptance.app仅用于包内Go命令和签名/资源验证，未发布。

**人工复验 / Manual checks：**在 41891 → 客户端管理 → 上述独立设备 → 插件审计，翻到第二页，分别核对上述 Codex 和 Claude 会话的六条 Hook 及 Pre/Post 详情；简体中文、English 均查看命令、长路径、相同 call、未知结果/退出码并关闭。不要同时用该网页账号发起第二次 API 登录。受管后续须先排除业务进程冲突，真实测试用户绑定独立设备并使用受支持宿主；通过平台受管策略及桌面系统授权入口先取消再批准，继而核对原生加载、四次独立文件工具、ACK、双语网页与产品更新/移除，最后按基线检查冲突并恢复。物理合盖和连续唤醒瞬态另验。

**English:** Original P3 exit evidence remains distinct from customer onboarding. A fresh Claude 2.1.220 task confirmed model recovery with one real Bash call and six native acknowledged Hooks. The previously pending Codex session and the new Claude Pre/Post passed actual bilingual browser details. A real paused, nonempty frozen batch survived an older-to-latest standard package replacement byte-for-byte; resumed upload and replay preserved strict ACKs without duplicate events. The device now has 182 exact acknowledged identities, no pending/frozen data, and reporting restored. In the real aidr-test OS account, native macOS cancellation and approval, three managed lifecycle Hooks, strict ACKs, and bilingual web details passed. The packaged product CLI repeat install preserved configuration, binaries and six ACKs while refreshing preimage receipts. GUI repeat authorization, a real managed version update and the complete managed tool chain remain unverified. The managed tool task timed out without tool calls; this does not reconfirm model recovery. Product removal has now removed all Claude managed Hooks, stopped the receiver and retained all six ACKs. Seven system files remain by product design, so original file absence is not fully restored. Conflict-checked preview/CAS restored the original ordinary target as revision 8, preserving other policies. Normal app Quit and receiver/socket cleanup passed. The packaged product uninstalled only the UID503 temporary base service and registration. Test reporting was restored to disabled and credential 5 revoked; a device-authenticated request was denied with HTTP 403. All six exact ACK/platform identities, the daily service and isolated backend were preserved. The connection, databases, user plugins, acceptance bundles and seven retained system files remain; reconnecting needs a new test credential. Evidence: test-user-exit-service-cleanup.json and test-user-platform-cleanup.json. The removal-report refresh fix passed Go/protocol and packaged product-command checks, but its native GUI action has not been rerun. API login with the browser's same account invalidates its session; acceptance now separates those flows. Wake UI freshness and physical lid closure remain separate unverified items. No commit, push, deployment or release.


## Claude Linux 受管加载补验（2026-10-02）

官方Claude Code 2.1.220 LinuxARM64包经发布SRI校验，在OrbStack上的自有隔离容器读取真实 `/etc/claude-code/managed-settings.json`。产品安装器生成16种事件声明；原生输出证实SessionStart及SessionEnd实际执行，并非全部16种事件均触发。第二个OS用户设置用户级disableAllHooks仍执行系统Hook；安装幂等、普通用户不能写系统配置、跨用户不能读私有连接、其他管理员Hook/权限及Codex配置保留均已核对。移除后仅本产品条目消失。

网络为none，无宿主目录挂载、真实模型凭证、接收器或平台上传。私有桥接暂停时原生Hook返回0；启用但socket不存在时原生SessionStart退出1、报告 `aidr_hook_receiver_unavailable`。模型连接被隔离并按期限结束，不计任务成功或审计闭环。容器已停止、数据和诊断保留。产品在线Claude信任报告仍未知；macOS原生授权、受管工具审计/网页闭环仍待验。

**English:** Official Claude 2.1.220 loaded the real Linux system managed file in an isolated container. Native SessionStart/SessionEnd execution, per-user isolation, idempotent installation, foreign configuration preservation and owned removal passed. Sixteen events are declared, not all triggered. An unavailable receiver produced exit 1 and a stable error. No model inference, collection/upload, macOS authorization or full managed integration was validated; runtime trust remains unknown.


## Claude Read 原生正文适配（2026-10-02）

Claude Code 2.1.220的真实文本Read Hook提供 `tool_response.type=text` 与 `tool_response.file.content`，规范化为已有 `file_body / result.file.text` 契约。仅在来源明确绑定Read/read_file且文件正文范围开启时处理，沿用脱敏、每片段1024 UTF-8字节、总计2048字节和4片段上限。图片、未分类对象及其他工具不能通过该适配上传正文，不读取业务文件补齐。Write的input.content及Edit的old_string/new_string继续支持；本次不采集Edit结构化结果的originalFile或structuredPatch，结果格式未支持时明确显示unsupported。

真实独立任务四次工具、十二Hook已逐条核对本地ACK、平台存储和正文权限API，两次Read分别是ONE/TWO及遮蔽值。Hook未明确提供成功/退出码，结果和进程关系继续未知。已确认的旧unsupported记录不补写，冻结批次和身份摘要不改，升级无需重建数据库。隔离审计配置及客户端实际恢复31（脱敏开启、正文关闭、采集开启/7天）；标准.app资源升级保留149条旧回执，新任务后161条、待发/冻结0。新增正文中文8条、英文8条均已在真实页面逐项补验；最新标准包正常关闭、Cmd-Q和重开自动恢复已验。原生macOS受管授权仍待验，本次有限授权及业务冲突条件见当前验收状态。

**Manual UI checks / 人工复验：**在41891测试设备的插件审计按上述fb16e0e8会话定位；查看Write Pre、两次Read Post（平台361/365）及Edit Pre的按需正文，核对来源、脱敏、ONE/TWO、未知退出/进程、长路径和关闭清除。用简体中文与English分别检查，不重采旧记录。macOS受管授权按当前有限授权与业务冲突检查执行；OrbStack的Linux证据不能替代原生macOS授权验收。

**English:** Native Claude 2.1.220 Read text responses map file.content into the existing bounded result.file.text file-body contract. Scope and redaction apply before persistence. Confirmed old records and frozen bytes remain intact. Write/Edit inputs are supported; structured Edit results remain explicitly unsupported. Real native tools, local receipts and authenticated content APIs passed. All eight Chinese and eight English content details passed in the actual browser. Latest standard-package close, Cmd-Q and automatic reopening passed; native macOS authorization remains pending.

## Codex受管原生状态适配（2026-10-01）

真实官方Codex0.159.0 LinuxARM64在独立、无宿主目录挂载且不联网的容器中读取实际 `/etc/codex/requirements.toml`，12个Hook均报告isManaged/managed。实测暴露并修复原生状态适配：sourcePath是受管目录（对应managed_dir），不是requirements文件路径；Source须为system。SessionEnd/Interrupt的原生预算为3秒，安装器按3秒生成，其余保持60秒；不隐藏其他原生加载警告。

已有本产品拥有的精确60秒配置通过所有权回执和原子安装流程迁移为3秒；其他管理员改变过的条目仍按冲突处理。保留原配置备份和现有用户设置；不修改事件、冻结批次、摘要或ACK。官方宿主复验无警告、两个独立OS用户的产品NativeCodexManagedTrust均managed；重复安装摘要不变、移除只删除本产品条目并保留随后添加的管理员Hook；用户私有连接不可跨用户读取。该容器只验证原生配置/安装器/用户连接，不包含模型调用、真实受管Hook事件上传或macOS授权弹窗。macOS受管授权取消/批准、原生系统加载与升级/回滚仍待验，当前Mac须先满足业务冲突检查与真实用户Home契约；Claude的macOS受管加载及工具上传闭环仍未实机验证；Linux原生系统配置加载证据见上节。

最新标准macOS.app已重新构建并更新本任务安装副本。此次使用精确自有进程SIGTERM替换，父管道EOF回收原接收器/socket；109条ACK、设备和stream保留，自动恢复本地运行。监督器保留中断证据，累计尝试2、最近原因aidr_desktop_receiver_interrupted，未清零掩盖中断。此退出/恢复是进程回收证据，不代替最新标准包的GUI正常Quit与双语窗口验收。旧标准包的一次真实工具/6条Hook闭环按其构建保存；本次受管状态补丁后的普通接入已用最新标准包复验：Codex0.159.2独立会话 `01a0f7f1-8620-7d92-b851-2307a10b2068` 一次touch工具、6条原生Hook，26.204秒、CLI退出0；117条本地ACK与平台及认证API身份/序号完全一致，待发/冻结0，原297条摘要不变。启动只使用隔离Home和既有网络代理，无AIDR变量或手工接收器。首次不保留网络代理的对照在100秒超时，只有2条生命周期事件；失败记录保留，不计工具验收通过。新会话的网页展示仍待验。

**UI复验 / Manual checks:** 在专用macOS测试用户/设备，平台选择Codex0.159.0受管目标→桌面等待系统授权→先取消、再明确批准；新会话原生库存应有12个受管Hook且无加载警告。分别核对安装、实际加载/信任、接收器、ACK；升级旧60秒安装并保留其他管理员Hook，移除后其他策略不变。普通接入另保持用户原生审阅。新标准包双语切页、后台、正常退出和重开保留117条ACK；不要由窗口自动定位启动未带私有Home的源码包。

## 标准安装包补验（2026-10-01）

标准 `npm run build:mac` 生成的Tauri `.app` 已复制安装并实际运行，保留原Info.plist和产品标识，测试副本仅ad-hoc签名，私有Home由启动环境隔离。其包内Go、插件资源和自动接收器完成独立Codex0.159.2新会话 `01a0f7d1-19ad-72f3-872f-465bb1082d8e`：一个受控touch调用、6条原生Hook，全部获得严格ACK；本设备109条身份/序号与认证查询及平台集合一致、待发/冻结0、原297条平台摘要不变。该次包升级前无待发冻结批次，不称真实积压升级验证。该阶段窗口工具曾识别旧测试bundle ID；2026-10-02同一标准包资源的新安装副本已完成双语窗口、关闭和重开验收，证据分阶段保存。正式发行签名、公证与远程分发属于发布验收，不作为本次明确禁止发布的实现目标新增前置条件；macOS受管授权取消/批准与原生管理加载仍是本次真实待验项。

## Codex 原生补丁字段 / Native patch field（2026-10-01）

普通接入的Codex0.159.2原生 `apply_patch` Hook提供 `tool_input.command` 补丁正文，按 `file_body / input.command` 记录；其补丁头用于展示请求目标，不证明OS执行。该字段仅接受明确apply_patch/patch绑定，Bash命令不转换为文件正文。范围、脱敏、字节预算及截断继续由原策略控制；服务端须支持该来源白名单后才更新采集端。此次无需数据库重建或事件身份升级，既有未提供正文的已确认记录不补写，冻结字节、摘要及ACK不变。

两轮真实独立任务各四工具、十二Hook，第二轮会话 `01a0f7c4-1019-7aa1-94cd-4c177d33567c` 的创建与修改补丁、两次读取输出均已逐条核对持久存储与正文权限接口，虚构秘密在SQLite及WAL/SHM不出现。原生CLI两次读取退出0，Hook未提供退出码，网页契约中的结果与进程关系保持未知。平台原297条摘要不变；配置经22/24两次临时开启后恢复为25（脱敏开启、三类正文关闭、采集开启/7天），客户端实际应用已核对。新正文双语网页尚待此次验证码登录。

**Manual check:** In the isolated 41891 device's Hook audit, find the exact session above. Open the two apply_patch PreToolUse details and the two Bash PostToolUse details, request content explicitly, and verify patch source, requested target, ONE/TWO content, masking, unknown result/exit/process status, and clearing on close in Chinese and English. Do not use native CLI exit 0 to fill missing Hook results. Fresh Claude tools and file-body persistence have passed; new-content pages, whole-system sleep and managed macOS authorization remain separate checks. Signed distribution is later release work.


## 审计采集与统一保留 / Audit collection and retention（2026-10-01）

审计策略默认继承全局。关闭继承后，采集开关、Prompt/工具输出/文件正文、脱敏和保留天数作为一组单独配置，仅作用于该客户端；后续全局更新不覆盖单机配置。重新开启继承并保存后跟随全局更新。平台策略下发、日志通道状态、Hook 接入验收和历史清理均读取该设备的有效策略。保留天数适用于该设备已有历史，缩短后会淘汰超期内容；已淘汰内容不会恢复。全局和单机保存使用共享递增版本，恢复继承也产生新版本，既有凭据与待发积压仍遵循应用回执边界。

**English:** Audit policy is inherited by default. A client override covers collection, content scope, redaction and retention together and remains unchanged by global updates. Restore inheritance to follow the global policy again. Delivery, channel status, Hook onboarding and history expiry use the effective client policy. Retention changes also affect existing history. Verify the client-reported applied version separately from the saved target.


沿用系统概览的审计设置，增加唯一权威的 `lifecycle.enabled`（默认开启）和 `lifecycle.retention_days`（默认7天，1–365天）。这是审计启停与保留；脱敏、扩展内容范围、设备上报及系统防护继续由各自策略控制。修改复用管理员权限、版本冲突校验和前后值审计。旧客户端未报告生命周期契约时，页面显示实际状态未知，不能宣称已停止采集。

客户端通过 `X-AIDR-Policy-Schema: 2` 与 `X-AIDR-Audit-Lifecycle: 1` 获取绑定设备、流、序号的生命周期快照；Behavior v5 / Hook v3记录实际策略。旧客户端获取兼容响应。关闭后不新增日志/Hook审计正文，接收器和合法旧队列继续运行与补传；日志游标推进，使用 `aidr_audit_collection_disabled` 明确报告覆盖缺口。恢复边界持久化，恢复时间及之前的未读日志（包括后来才发现的来源）不自动回采；这也可能跳过此前尚未读取的旧历史，不能报告完整覆盖。重启保留该边界、来源绑定和原游标。

关闭采集时，Hook只保存有界的事件身份与HMAC去重回执，不保存Prompt、命令或结果正文，也不声明平台ACK；48小时窗口最多100万回执，超限返回稳定错误。已有工具允许/拒绝照常执行；依赖持久审计证据的审批明确拒绝，代码 `aidr_hook_audit_disabled_requires_evidence`。系统观察按独立策略运行。

保留期限作用于本地已ACK日志正文及平台日志、Hook、系统审计正文。平台按接收时间每分钟有界淘汰，每类最多500条；本地按ACK时间淘汰。未确认待发数据和冻结批次不按期限清理，身份、内容摘要和ACK继续用于严格重试。平台淘汰历史返回 `aidr_audit_history_retention`；正文已淘汰时返回HTTP410 `aidr.content_expired`，与当前采集缺口区分。迟到结果只形成缺少已淘汰调用证据的记录，不重建历史。缩短期限影响已有已确认历史；淘汰是逻辑数据保留行为，不承诺清除SQLite页、WAL或备份中的物理残留。

迁移只增加生命周期快照、淘汰时间及必要索引；旧派生操作从升级时获得完整保留窗口。已有事件、内容摘要、读取游标、批次字节和ACK不重写。配置每30秒尝试刷新；离线使用有效缓存，首次失败默认采集开启、脱敏开启、扩展内容关闭、保留7天。

客户复验：系统概览保存采集关闭，等待客户端显示实际策略版本与“采集关闭”，在独立宿主新会话执行一次临时目录测试；本地去重回执增加，审计序号和平台事件不增加。重新开启后，用新会话再执行一次，核对新审计序号、平台ACK与网页证据。勿把状态报告、去重回执或安装成功当成事件ACK。


## 可配置扩展内容 / Configurable source content（2026-10-01）

“客户端管理 → 客户端策略 → 审计采集与脱敏”管理全局默认脱敏和采集范围；进入具体客户端的“客户端策略 → 审计采集与脱敏”，可关闭“继承全局审计策略”并单独配置。该阶段支持的三个选项为 `capture.prompt`、`capture.tool_output`、`capture.file_body`。当前全局默认采集用户输入、模型回复、文件正文与命令正文，工具输出默认关闭，脱敏默认开启。选项只作用于后续来源事件，不回读业务文件或重采旧原文，也不改变行为字段白名单。版本4行为与版本2 Hook支持这些选项；旧客户端继续行为字段范围，其正文支持与实际应用保持未知。

Prompt当前明确适配 `UserPromptSubmit.prompt`；文件正文适配Write/Edit/MultiEdit的明确内容、apply_patch的原始补丁字符串、明确patch/command字段以及可靠调用绑定的Read文本结果；工具输出适配文本结果、明确stdout/stderr/output字段和文本块。未知参数不完整透传，包装调用不会据字符串推断文件正文。日志结果只在来源会话内的明确call/turn绑定下分类；有界游标保存16个调用绑定，歧义或缺失时不推测。每事件最多4片段、每片段1024 UTF-8字节、合计2048字节；先执行所选脱敏策略再截断，记录来源字段、源字节数、脱敏及截断标记。截断切中脱敏替换时缩短尾部，保持可验证且不增加预算。

客户端以`X-AIDR-Policy-Schema: 2`协商范围凭据。服务端保存设备/流/序号绑定的范围快照，不能凭客户端自行声明接受正文；新旧凭据在同一策略版本分别签发。已有策略凭据表增加可空`capture_json`和`lifecycle_json`，旧行不回填。SQLite事件、游标、逻辑身份、冻结批次字节/摘要和严格ACK保留；历史缺失正文明确显示信息不足。策略每30秒尝试刷新，离线使用有效持久缓存，首次失败默认开启脱敏且不开启正文。

列表、操作、审批详情及投影JSON只返回正文描述，正文通过设备可见性与独立`clients:read-audit-content`权限接口按需获取；响应`Cache-Control: no-store`。访问审计只记录来源、记录ID和片段数。页面关闭、设备变化或失去权限清除展示数据；不自动展开正文。脱敏关闭时，只在授权范围内保留原文，说明凭证可能进入本地与平台。

**实际证据：**隔离设备在无手动接收器、无桥接环境变量下运行Codex0.159.0，开启脱敏时Prompt与工具输出中的虚构秘密已遮蔽，关闭时虚构Token及完整git文本保留（git文本仅为printf输出，未执行提交）。该阶段3次有限模型任务新增17条真实Hook，流内54条本地/平台回执ID相等、待发与冻结批次均0，原242条平台Hook摘要不变。文件正文实机任务被原生只读沙箱拒绝，文件未生成，Hook未提供正文；该项未通过。后续真实中英文网页已核对来源描述、按需正文、脱敏Prompt/输出、关闭脱敏时的完整git文本及收起清除；接口证据与网页证据分别记录。隔离配置已恢复开启脱敏、三类正文关闭，该阶段实际应用版本4；日常后台未改。

**English:** This release introduced three independent source-content options. Current global defaults enable user input, model replies, file bodies and command bodies, with tool output off and redaction on. Behavior v4 / Hook v2 clients receive device/stream/sequence-bound scope receipts; legacy receipts and frozen bytes survive. Explicit source fragments are bounded to 4 items, 1024 UTF-8 bytes each and 2048 bytes total, with redaction before truncation. Lists contain descriptors only; content requires separate permission and an audited, no-store request. Live Codex0.159.0 proves Prompt/tool-output ON and OFF handling with fictional data. The file-write probe was rejected by the native read-only sandbox and is not a file-body acceptance pass. The original conservative test policy has been restored. Bilingual content viewing passed; Restricted-reader browser checks passed in both languages; managed system authorization remains pending.

## 平台自动接入策略进展（2026-10-01）

平台默认客户端策略新增运行治理目标：开启/暂停、目标宿主、自动/管理员安装、普通/企业受管接入、随包自动/手动更新，以及不重试/固定次数/持续重试。配置只存于默认策略，设备页继承查看；权限沿用普通管理员查看、超级管理员保存及既有影响预览。旧部署未保存该配置时保留原本地偏好。

协议2客户端通过既有心跳及每5分钟一次的有界宿主检查触发 `aidr_plugin_action` 协调任务；设备、策略、随包版本和实际宿主变化参与幂等标识，时间刷新和健康计数不生成新任务。原子领取、持久回执与手动动作共享通道和文件锁。执行前重新认证核对当前策略，旧目标不能覆盖新目标。平台目标、策略收到/检查/应用时间、宿主信任和事件ACK独立显示。普通模式已有后台安装/更新差异协调；macOS受管模式新增原生系统授权入口和固定动作安装组件，部署Codex requirements.toml或Claude managed-settings.json，原子合并并保留有界恢复依据。受保护的版本回执和二进制摘要证明安装版本；Codex原生hooks/list另外核实受管加载与信任。系统级安装、取消/批准及原生受管加载尚未实机验收，不能称受管接入通过。

主后台服务持久保存平台/设备绑定的启动次数、最近故障、暂停原因及下一次重试时间；初次启动与重试分开计数，退避封顶。重开桌面不重置故障耗尽，主服务健康正常退出后允许下一次初始启动。单实例锁覆盖停止和退避期间；切页和后台不依赖展示计时器。授权取消、失败或中断结果绑定策略版本持久记录，不自动重复弹窗；中断安装需检查真实文件及恢复依据。宿主检查时间变化不重启健康接收器。隔离默认策略已通过真实后台自动安装全新Claude配置（未点接入）；Codex0.159新会话及暂停补传测试共新增12条真实Hook全部ACK，Claude新会话因模型HTTP502只收到3条生命周期事件，工具操作未验。此前记录ID及摘要保留，该阶段54条本地/平台集合相等、待发0；后续真实中英文已按精确会话核对事件、详情及来源正文。三种重试及准备锁竞争已有本任务自有进程实测，双语保存失败/重试和409冲突已验；低权限正文页面已通过中英文实测；成功文件正文后续已由真实Codex/Claude新任务及持久查询补验；新增正文网页与专用macOS受管授权仍需分项验收。详见主仓库 experiments/aidr-agentlog/ACCEPTANCE.md，不等同目标完成。

设备“暂停上报”只拒绝新事件批次，继续允许绑定正确且权限有效的凭证获取审计策略、报告状态和获取控制快照。本地日志/Hook继续按容量限制持久化。上传返回稳定码 `aidr_upload_reporting_paused`，按1/2/4/8/16/32/60秒封顶退避；实际轮询周期可能延后下一次尝试。认证或权限失败停止上传并保留待发数据，需修正配置。冻结批次在暂停、策略刷新及新增采集期间保持原字节，恢复后严格匹配ACK。桌面和平台分别展示最后状态报告、上传原因/下次尝试及最后事件ACK。ACK时间在客户端匹配成功后持久保存；旧客户端未报告时保持未知。

**English:** The default platform policy owns runtime targets and retries. Protocol-2 clients reconcile through existing atomic tasks and durable receipts. Ordinary automatic installation and real Codex 0.159.0 audit delivery have isolated-device evidence; native macOS managed authorization and new-content browser checks remain pending; real Codex/Claude file-body persistence passed; restricted-reader browser acceptance passed in both languages; bounded optional source content is implemented. Pausing device reporting retains local intake and frozen batches, with bounded upload backoff; it does not invalidate device authentication. Status-report success and the client's durable event-batch ACK time are shown separately. Older reports without ACK telemetry remain unknown. Fifty-four local/platform Hook receipt IDs match after pause/resume and source-content tests; Bilingual event review passed; restricted-reader content access passed in both languages with metadata-only projections and no content-view action.


## AIDR 桌面插件接入

Codex 0.159.0 和 0.159.2 的自检走原生 App Server 本地库存与有效配置，不等待远端目录；来源缺失或冲突保持未知，实际插件版本取自原生包。该诊断适配与真实工具验收分开。**English:** Codex 0.159.0 and 0.159.2 inspection uses native local inventory and effective configuration, avoiding remote catalog waits. Missing or ambiguous sources stay unknown; native package versions remain authoritative. Diagnostics do not imply successful tool execution.

平台安装/更新依据客户端报告的原生接口兼容性与安装能力；未知、过期或不支持的报告需先自检。客户端执行时再次检查接口，版本字符串只作诊断标签。**English:** Installation and updates depend on reported native interface compatibility and installation capabilities. Reinspect unknown, stale or unsupported reports. The Client checks interfaces again when executing; version strings are diagnostic labels.

macOS 客户端完成现有设备认证、管理员确认设备凭证具有 `aidr:heartbeat` / `aidr:report-events` 权限且平台允许设备 AIDR 上报后，按平台默认客户端策略自动接入所选宿主；客户无需逐台点击接入。若管理员选择显式安装方式，则从平台下发安装任务。本地 **Agent 运行治理** 查看实际应用、宿主安装/启用/信任和接收器状态。客户端使用随包 Go 程序和插件资源，原生安装当前用户插件，写入不含凭证的稳定连接路径，并自动管理接收器。客户不需要启动命令行接收器、设置桥接环境变量或复制设备 Token。配置只对新的宿主会话生效。

当前普通插件与受管接入按原生接口探测判断兼容性，完整规则见[Agent 小版本兼容与接入检查](#agent-小版本兼容与接入检查)。普通 Codex 信任由用户在原生 `/hooks` 审阅，客户端不代写信任记录；只读信任查询只是当前查询范围的快照。Claude 原生确认若出现，也需用户处理。受管安装还需确认原生授权与实际加载结果。

历史验收记录：普通插件曾验证 Claude Code 2.1.220，以及 Codex 0.158.0-alpha.2.1、0.159.0、0.159.2。0.159.0 已核实原生首装/重复安装、用户审阅后的12项持久信任、新独立会话8条真实 Hook、本地/平台精确 ACK 及中英文详情，覆盖6种审计事件。0.159.2 已验原生接口、含空格路径首装/重复安装、既有信任读取及自动任务，真实工具因401未完成。这些记录证明对应验收范围，当前安装条件以接口探测和设备报告为准。

**English:** Current ordinary and managed integration uses native interface probes to determine compatibility. Complete native trust and required managed authorization, then verify actual loading and event delivery. Historical version-specific acceptance records establish only the scenarios tested; current installation readiness comes from interface checks and device reports.

本地接收器、插件安装/启用/信任、平台报告 ACK 和事件上传错误分别展示。Hook 接收器与日志采集运行在 `agent-manager-client run` 主后台服务内，共用一个进程。桌面只读取健康状态和提交操作请求；切页、关闭窗口、完全退出或重启桌面均不停止工具审核和事件上传。托盘“退出应用”仅退出界面。接入 TeleAgent 时另有独立模型代理，总计 2 个常驻后台进程；按需系统采集器另计。接收器遵循平台重试策略，保留暂停原因、重试额度、队列及 ACK。主后台服务本身重启会短暂重建接收器，不等同于界面重启。

**English:** The Hook receiver and log collector run inside the main `agent-manager-client run` background process. The desktop reads health and submits actions. Navigation, window closure, app quit and desktop restart leave tool review and event upload running. With the separate TeleAgent model proxy, there are two persistent background processes, plus any optional system collector. Receiver retries, suspension reasons, queues and ACKs remain durable. Restarting the background service itself briefly recreates the receiver; restarting the GUI does not.

TeleAgent 模型代理由独立 macOS 用户级 LaunchAgent 运行。关闭、退出、重启或更新客户端均保留代理及现有流式响应；登录时自动运行，崩溃后由 launchd 恢复。工具审核通过 Hook 接收器完成；接收器退出后，模型转发继续运行，工具审核按接收器不可用策略处理。首次迁移需要释放旧接收器持有的端口；安装与程序更新说明见 [外部 Agent 接入](external-agent-integration.md)。

**English:** TeleAgent model forwarding uses an independent per-user macOS LaunchAgent. Window closure, app quit, desktop restart and client updates preserve the proxy and active streams. It starts at login and launchd recovers crashes. Hook review still needs the receiver; model availability does not imply tool authorization. Initial migration releases the old receiver's listener before the independent service takes ownership.

人工验收 Todo（简体中文 / English）：关闭窗口、托盘退出和重开客户端前后核对接收器 PID 与主后台服务 PID 一致，实例标识不变；退出期间执行允许的 Agent 工具操作，核对事件及 ACK；检查托盘菜单、运行治理说明、重试入口、窄窗口布局。Manual UI checks: close, tray quit and reopen; confirm receiver PID equals the daemon PID and instance identity is unchanged. Run an allowed tool while the GUI is absent and inspect its event/ACK. Check tray labels, governance help, retry controls and narrow layouts in both languages.

2026-10-13 本机开发构建验证：Hook IPC 对端与主服务 PID 同为 `91099`，独立 `aidr-hook-serve` 子进程已移除。向桌面进程发送 SIGTERM 后确认桌面进程不存在，连续 10 次健康检查成功，接收器 PID 和实例标识保持不变。桌面退出期间，TeleAgent 的“模型连通性验收”会话执行 `printf 'HOOK_BACKGROUND_OK\n'`，原生工具详情显示该命令及输出 `HOOK_BACKGROUND_OK`。共享 Hook 序号由 `25502` 推进至 `25524`，ACK 时间推进且待发为 0；这是共享通道回执证据，不将所有新增 Hook 归因于该单次 TeleAgent 操作。恢复开发客户端后仍为同一接收器实例，主服务与代理共 2 个后台进程。此次覆盖真实进程退出及重新启动；托盘原生 Quit、双语菜单布局和正式签名发行包继续按上述 Todo 验收。

**English:** On October 13, 2026, the development build served Hook IPC from main-daemon PID `91099`, with no separate `aidr-hook-serve` child. After SIGTERM terminated the desktop, ten health checks passed with unchanged receiver PID and instance. TeleAgent's native tool details showed the actual `printf` command and `HOOK_BACKGROUND_OK` output while the GUI was absent. Shared Hook sequence advanced from `25502` to `25524`, ACK progressed and pending uploads returned to zero; this shared evidence is not attributed entirely to that one TeleAgent call. Reopening the development client preserved the receiver instance. Native tray Quit, bilingual menu layout and signed release packages remain manual checks.

验证范围：5 项 Go 后台接收器回归（含 race 检查）、客户端命令与 Hook 包测试、23 项 Rust 测试（另 3 项条件测试跳过）、桌面/平台 i18n 检查与平台构建通过。发送节流与单轮等待预算问题已在后续修复，现有间隔断言保持不变，最新完整回归结果见本文开头。

**Validation:** Five managed-receiver Go regressions including race checks, client-command/Hook package tests, 23 Rust tests (three conditional tests skipped), desktop/platform i18n checks and the platform build passed. The existing `TestOrdinaryPacingFairnessAndRoundBound` failed its send-interval assertion in broader daemon testing; the remaining daemon tests passed when that case was excluded. Its pacing implementation and assertion were not modified.


设备凭证仍来自既有私有配置，不进入插件、接收器参数或 renderer。连接文件只含 socket；运行程序缓存位于用户 `~/.agent-manager/aidr/runtime/`，正式安装不依赖源码目录或临时路径。队列按平台与稳定设备身份分目录保存，凭证轮换沿用同一队列；平台切换保留旧目录，不把积压投给新平台。socket 或队列锁冲突不会被删除、接管或当成健康。旧手动插件连接显示迁移提示：先用旧绑定恢复传输、排空并保存其状态，由原进程管理者停止旧接收器，再按宿主原生流程移除旧 AIDR 插件，由平台当前接入目标协调安装；其他插件与设置保留。旧队列没有被转换、清空或自动拷贝。

默认接入为仅审计。已有工具控制需要原来已核实的 P-256 公钥；受管私有偏好的 `public_key` 指向该公钥时沿用现有控制与审批契约，不能从未验证远程响应自动取信。当前桌面入口尚无公钥配置交互，手动控制实例不能被自动迁移为已验证控制实例。后台生命周期复用既有主服务注册；ES 阻断仍由独立系统采集配置控制。

主后台服务持有用户级监督锁，接收器在内部任务中运行并响应服务退出信号。桌面退出不关闭 socket。服务崩溃后仅在监督锁和队列写锁已获取、记录的 socket device/inode 一致且连接明确拒绝时回收自身遗留 socket，未知端点保留并报告冲突。没有有效实时健康证据时，上传状态保持未知。独立测试 Home 不自动修改真实用户后台服务注册。

真实 macOS `.app` 验收已覆盖 Claude 按钮首次/重复安装、自检、启停、重试、切页、最小化、关闭和菜单退出/重开。四个独立 Claude 会话共26条 Hook 均已本地 ACK，平台精确 ID 集合一致，包括6条断网补传；中文/英文网页核对命令、session/call、明确错误与未知结果。当前客户流程设备另新增 Codex 0.159.0 的8条真实 Hook，22条记录全部ACK、待发0，包更新后保留原队列与信任。原生 CLI 的退出0/7与没有明确结果依据的 Hook 分别记录，不能靠命令或时间强行关联。十分钟低负载后台及独立设备205条合成协议事件的真实双语分页已验；合成事件不计入原生Agent验收。正式签名升级、其他平台及长期/高负载仍待验。完整报告见 `experiments/aidr-agentlog/ACCEPTANCE.md`。

**English:** After device authentication, the client applies the platform's automatic installation target without a per-device Connect click; administrator-only installation uses explicit platform tasks. The client installs native plugins and runs its receiver inside the main background service without bridge environment variables, customer-managed terminals or copied device tokens. Ordinary plugins require native user review. Managed access uses host-recognized system configuration and a scoped native authorization action; actual system loading remains separately unverified. Start a new host session after configuration changes. Collection survives navigation, minimization and background execution; closing the window or quitting the desktop leaves the background receiver running. Crash recovery follows the platform retry policy: no retries, fixed retries (two after initial launch by default), or continuous bounded backoff. Offline data retains immutable batches and strict ACKs. Private queues remain bound to platform/device; manual installations require explicit migration and are not adopted. Default access is audit-only; existing tool control still requires an independently verified pinned public key. Codex 0.159.0 is an installation target after native installation, persistent trust, eight real hooks and bilingual browser acceptance. This covers six audit event types; missing Hook result evidence and OS process attribution remain unknown.

当前自动回归、安装包后台联动、Claude 真会话、离线补传、平台任务、中英文界面与窗口生命周期证据，以及未验版本和正式分发范围，见 [已有验收记录](../experiments/aidr-agentlog/ACCEPTANCE.md)。插件协议与开发 CLI 见 [插件使用说明](../client/aidr-plugins/README.md)。

## Agent 运行治理的平台操作

概览区分**工具调用次数、终端工具调用次数、命令出现次数**。一次调用的执行前后事件按可靠身份合并，只算一次工具调用；命令排行按静态解析后的程序名出现次数累计。例如三行 `sed ...`、`rg ...`、`rg ...` 算一次调用、三次命令出现，排行为 `rg × 2`、`sed × 1`。`uv run pytest > test.log 2>&1` 计一次 `uv`；`ps ...; tail ...` 分别计一次 `ps` 和 `tail`。

详情保留已采集原始命令，按顺序展示子命令、程序名和行号。解析支持 Bash / POSIX 换行、分号、条件连接、管道、后台执行、重定向、子 Shell 和命令替换；引号及 heredoc 的普通正文不拆成命令。循环、条件分支与函数体按文本出现次数统计；`bash -c`、`python -c` 等参数中的代码不递归解释。动态程序名保留文本，仅确定的程序名计入排行。语法不完整、正文截断或超出解析上限时显示原因并保留调用计数。完整正文及其解析结果沿用审计正文权限，原有脱敏与保留期不变。旧版动作中的命令摘要及包装工具提取的终端动作同样属于审计正文，列表与下钻只返回内容描述；需要 `clients:read-audit-content` 权限才能按记录读取命令与子命令文本。程序名和出现次数仍作为统计元数据展示。

点击排行查看包含该程序的调用，每条记录可以包含多次命令出现。对应操作弹框使用标准分页，显示当前筛选范围内的总条数；默认每页 30 条，可选择 10、20、30、50、100 条并跳转页码。切换每页条数回到第一页，保留当前筛选范围；点击“查看记录”直接展开详情。日志与 Hook 按来源独立统计，宿主报告结果属于整个调用。“查看记录”按设备、上报流和原生调用标识定位候选事件，再核对用户、产品、会话、轮次、工具与子 Agent 身份。关联索引由数据库升级自动创建，缺少或冲突的证据仍按原有状态展示。

**English:** The matching-operations dialog uses standard pagination and displays the total number of matching records. Choose 10, 20, 30 (default), 50 or 100 records per page, or jump to a page number. Changing page size returns to page 1 and retains the current filters. View record opens the details immediately. Overview distinguishes tool calls, terminal tool calls and command occurrences. Reliable pre/post identities merge into one call. Rankings count statically parsed program occurrences: three lines containing `sed`, `rg`, `rg` produce one call and three occurrences (`rg × 2`, `sed × 1`). `uv run pytest > test.log 2>&1` contributes one `uv`; `ps ...; tail ...` contributes one each of `ps` and `tail`.

Details retain captured original commands and show subcommands, program names and line numbers in source order. Bash / POSIX parsing supports newlines, semicolons, conditional chains, pipelines, background execution, redirection, subshells and command substitution. Ordinary quoted/heredoc text is not split into commands. Loops, branches and function bodies count textual occurrences, not executions; code inside `bash -c` or `python -c` arguments is not recursively interpreted. Dynamic program names keep their text but only resolved names enter rankings. Incomplete syntax, truncation or parsing limits show their reason and retain call counts. Full content and its analysis retain existing permissions, redaction and retention. Legacy command summaries and terminal actions extracted from wrappers are also protected audit content. Lists and drilldowns return descriptors only; command and subcommand text requires `clients:read-audit-content` through the record content endpoint. Program names and occurrence counts remain statistical metadata.

Rankings open calls containing the selected program; one row may contain multiple occurrences. Logs and Hooks remain separate sources, and host outcomes apply to the whole call. View record uses an indexed device/stream/native-call lookup and then verifies user, product, session, turn, tool and subagent identity. Database upgrades create the index; missing and conflicting evidence retain their original interpretation.

客户端发现智能体的详情页在基础资产返回后即可浏览；运行治理、会话和策略分别补齐，会话尚未返回时显示加载状态。`GET /api/v1/clients/{client_id}/runtime-governance` 按产品索引读取最后一次有效 Hook 到达时间，并按客户端、流和记录顺序查找上传回执。历史到达时间仍保留，过期事件不参与统计。数据库升级会自动创建对应索引。

**English:** Discovered Agent details become available when the base inventory loads; runtime governance, sessions and policy load independently, with a loading indicator for pending sessions. The runtime-governance endpoint uses indexed latest-event lookups per product and indexed receipt lookups per client and stream. Historical arrival timestamps remain available and expired events are excluded. Database upgrades create the required indexes automatically.

最近会话按当前产品在日志、Hook 和消息来源内筛选，再合并各会话的计数和最近时间。分页快照、产品筛选与问题预览使用对应索引，普通列表聚合无需加载整段工具或消息正文；问题预览仍需要审计内容权限并记录查看审计。首屏并行读取工作区、运行治理、日志状态、最近会话和 Hook 策略。日志状态使用 `include_retention=false`，详情不重复统计历史过期数量。实际点击至渲染耗时与测量范围见 [性能测试记录](performance-benchmark.md#客户端发现的智能体详情首屏2026-10-14)。

**English:** Recent sessions filter the selected product within log, Hook and message sources before merging session counts and latest timestamps. Indexed snapshot and prompt lookups keep ordinary aggregation independent of full tool/message bodies. Question previews still require audit-content permission and produce access-audit records. The overview concurrently loads the workspace, runtime governance, log status, recent sessions and Hook policy. Log status uses `include_retention=false` to skip unused historical expiry totals. Actual click-to-render measurements and their scope are documented in the performance benchmark.

人工复验 / Manual checks：① 从客户端发现的 Codex / Claude Code / Qoder 进入详情，基础内容和最近会话正常加载；② “查看全部”后翻页、按会话或问题搜索，产品范围与计数正确；③ 无审计内容权限时不显示问题正文；④ 中英文详情、刷新及切换安装入口正常。/ Open discovered Codex, Claude Code and Qoder details; verify base content, recent sessions, full-list pagination/search, restricted prompt visibility, both languages, refresh and installation switching.

在客户端“Agent 与资产”以及客户端发现智能体的“能力与配置”中，Skill、插件和 MCP 服务的名称列表头提供搜索图标。点击后输入名称关键词，停顿 300 毫秒自动筛选，也可按回车或点击“搜索”立即查询；匹配忽略大小写。搜索覆盖当前清单全部记录后再分页，清除搜索恢复清单。各表格的搜索条件独立，资产页签的数量仍表示完整清单数量。

**English:** Skill, plugin and MCP name columns provide a search icon in the client's Agent and assets view and the discovered Agent's Capabilities view. Enter a name keyword to filter after a 300 ms pause, or press Enter / Search to apply immediately. Matching is case-insensitive and covers the entire current inventory before pagination. Clear search restores the list. Each table has independent filters; asset tab counts still describe the full inventory.

客户端列表的 **Agent** 列分别显示“已发现”和“可治理”；可治理表示支持 Skill 管理。**Skill** 列显示各 Agent 与共享来源上报的记录总数，未跨来源去重；共享来源数量单独显示，不计入 Agent 数量。两列表头的信息图标提供分项说明，支持悬浮、键盘聚焦和点击查看；点击图标不会改变排序。窄屏可横向滚动表格查看。

**English:** In the client list, **Agent** shows discovered Agents and the subset supporting Skill management. Governable counts do not indicate active runtimes or applied governance. **Skill** shows reported records across Agents and shared sources, without cross-source deduplication. Shared sources are listed separately and excluded from Agent counts. Hover, focus or click the header information icons to read each metric's definition without changing the sort order. The table scrolls horizontally on narrow screens.

点击客户端、系统、Agent、Skill、凭据创建人、状态或最后心跳列名，可依次切换升序、降序和默认顺序。排序作用于当前客户端列表的全部数据，再进行分页。Agent 按已发现数量排序，Skill 按记录数排序；系统先按操作系统再按架构排序，状态升序为离线在前，最后心跳按时间排序，未上报时间的记录在升序时排在前面。

**English:** Click Client, System, Agent, Skill, Credential Creator, Status or Last Heartbeat to cycle through ascending, descending and default order. Sorting applies to the full loaded client list before pagination. Agent uses discovered count; Skill uses record count. System sorts by OS then architecture. Status sorts offline first in ascending order. Heartbeats sort chronologically, with missing timestamps first in ascending order.

客户端策略中的审计配置保存前展示当前目标与本次目标；关闭脱敏、扩大正文范围或缩短保留期限须确认影响，取消返回编辑且不发送请求。保存后，在设备页核对客户端应用的版本、范围及报告时间。本轮中英文真实页面已验预览、确认、取消、扩大采集发布、409版本冲突、503保存失败保留草稿及恢复重试；双击保存只有一次持久发布。隔离设置已恢复，细节见验收记录。**English:** Audit settings require review and acknowledgement for sensitive changes. Cancellation sends no request. Bilingual browser checks passed actual scope publication, persistent 409/503 feedback with draft preservation, retry and one durable publication on double-click. Verify the client-reported version and scope separately; the isolated capture policy was restored.

客户端侧边栏 **Agent 运行治理** 独立于设置页。平台入口为 **客户端管理 → 设备详情 → 插件接入**，可执行安装、更新、自检和接收器启停；现有审计脱敏、插件工具控制、系统防护策略仍在各自平台入口维护。权限和设备可见性沿用现有客户端管理。

平台任务具有幂等标识、24 小时执行期限和独立回执；每设备最多一个活动接入任务。安装/更新只使用客户端随包插件，保留宿主和接收器的停用状态。平台管理后本地安装/启停按钮禁用，自检及故障重试继续可用。桌面关闭时，主后台服务仍可执行安装任务，并按有效策略运行 Hook 接收器和日志采集。旧客户端不报告管理能力时不能下发本类型任务。

实际状态显示接收器配置、运行、平台传输、队列、实际策略版本、宿主安装/启用/信任和检查时间。平台刷新只取最后报告，不触发原生扫描；自检在客户端运行。页面超过30秒未收到报告标为历史。冻结队列和旧回执不因配置动作删除或改写。

**English:** Device details provide installation, native update, inspection and receiver enable/disable tasks using existing device permissions. Tasks have idempotent identities, 24-hour validity and durable receipts. Bundled plugin installation preserves disabled native plugins, receiver preferences and queued data. Managed local installation/enablement is disabled; inspection and fault recovery remain available. Refresh reads observations, inspection runs on the client, and stale reports retain their age. The main background service can install components and run the Hook receiver and log collector according to effective policy while the desktop is closed.

## AIDR macOS 系统防护（P2）

设备详情新增 **macOS 系统防护 / macOS system protection**：管理员发布签名文件打开策略、载入历史内容发布新版本、撤销规则，并对确认的精确进程实例发起 SIGTERM。策略租约由已认证设备自动续签；续签产生的内部版本记录在操作审计中，不污染管理员配置历史。平台目标版本、执行器报告版本及命令下发/执行/退出核实分别展示。设备凭证和访问权限沿用现有机制，无需部门 ID。

原生执行器由独立 `aidr-enforce` 前台命令启动，需 root、ES entitlement 和可信公钥，不与只读观察 relay 或 P1 日志状态目录共用。策略每 10 秒刷新，断网继续使用缓存，期限/未知身份采用显式策略。停止执行器后系统授权控制消失；停止系统防护需停止执行器。签名密钥、构建、参数、资源边界、故障行为与验收见 [macOS 执行器使用说明](../client/macos-enforcer/README.md)。

当前已完成受控原生 ES 与隔离平台 API 实测；正式签名分发、真实 Agent 保护场景和本轮中英文网页交互有待验项，详见 [已有验收记录](../experiments/macos-es-poc/ACCEPTANCE.md)。Agent 日志结果、ES 授权决定和独立操作结果是不同证据，不合并推断为系统操作成功。

Agent Manager Client 用于统一发现、接管和巡检本机 Agent 的 Skill 目录。它直接管控文件入口，不依赖 Agent 是否遵循提示词、Skill 指令或 Hook。

客户端支持两种 Skill 授权方式：

- 客户端安全治理（默认）：Skill 已在平台批准且本地内容签名一致即可使用。
- Agent 强授权：除批准状态和签名外，还校验本机 Agent 自动登记身份所配置的 Skill 允许范围。

客户端发现本机 Agent 后会自动在平台登记稳定身份，供策略、模型凭证和审计使用。该过程不需要用户创建或选择另一个平台智能体。

“智能体列表 → 客户端发现”按客户端 ID 和本机 Agent ID 展示独立发现记录及当前 Skill 清单。已有平台运行身份绑定的客户端也会登记本机发现身份；清单更新保留原运行绑定、凭证和模型配置。平台创建页仍展示该平台身份关联的实例，客户端发现页按本机身份统计，两个来源页的数量不能相加作为去重设备数。Claude Code 与 Claude Desktop 是独立类型。历史发现记录在当前完整清单中没有实例时显示“当前未发现”，Skill 数量显示不可用；仍有实例但客户端心跳过期时显示“离线”，保留最近上报清单。升级时由服务端启动补登记，后续清单上报幂等维护。

Client discovery lists each local Agent by Client ID and local Agent ID, including Agents with an existing platform runtime binding. Inventory updates preserve that binding, credentials and model configuration. Platform and discovery views can reference the same local instance and are not additive device counts. Claude Code and Claude Desktop remain separate types. Historical entries absent from current inventory show “Not currently detected” with an unavailable Skill count; offline Clients retain their last reported inventory. Server startup backfills missing discovery identities and subsequent reports maintain them idempotently.

**发现详情工作区：**点击“详情”进入完整页面，顶部选择安装入口，使用以下五个标签：

- **概览**：最近会话、当前配置模型、Skill 数量、工具策略来源以及 Hook、日志、系统采集和共享接收器的独立状态；发现证据可展开查看原始内容。
- **能力与配置**：根据该安装入口上报的 Skill 根目录展示清单、认证信息和恢复副本；支持提交扫描、隔离、移除及恢复。受支持的模型适配器提供切换、校验、恢复与变更预览，按配置修订号校验并等待客户端执行。插件接入按 Agent 类型展示安装、启用、授权和操作任务。
- **行为审计**：会话日志和 Hook 事件按客户端与 Agent 类型查询，系统事件按选中的程序路径筛选；macOS `.app` 入口包含包内程序归属的事件。采集诊断保留时间、新鲜度和具体失败原因。
- **策略与审批**：展示适用工具规则、发布版本、配置模式、客户端报告模式及该 Agent 类型的工具审批。编辑客户端策略通过“管理客户端策略”进入共享入口。
- **执行记录**：按安装入口筛选任务，再进行游标分页；产品级插件任务也包含在内并标明范围。支持查看原始任务、取消待执行任务和重试可重试任务，执行期间短时自动刷新，超时后可手动刷新。

会话、插件和审批尚未归属到单个安装入口；同一设备的同类安装共享这些记录。Skill 目录若被多个入口共同读取，其文件处置也会影响其他读取者，操作确认中显示共享影响。日志重试通过桌面客户端 **Agent 运行治理 → 接入与采集** 操作，影响本客户端日志采集。设备信息、共享接收器及跨 Agent 策略通过“查看客户端”管理；客户端 Agent 清单也可跳回对应发现详情。只有智能体查看权限时保留发现信息，运行数据和任务分别要求客户端查看、执行权限。

English: The discovery workspace provides Overview, Capabilities, Activity, Policy & approvals and Execution history. Select an installation before managing its skills or model configuration. Sessions, plugins and approvals are scoped to the client and agent type. System events use the executable or app-bundle path. File actions disclose shared readers; model changes use revision checks. Task creation, policy publication and runtime success are separate states. Retry log collection from the desktop client; manage shared services and cross-agent policies through client details.

采集诊断按通道列出需检查状态及最近状态上报时间，“状态长时间未更新”表示平台暂时无法确认采集器是否仍在运行；选择异常通道可查看依据和处理指引。诊断抽屉仅内容区滚动，连续滚动时暂缓自动刷新，技术详情随正文滚动。智能体详情页头与标签固定，正文使用剩余窗口空间；宽窗口下行为审计的会话列表与日志阅读区分别滚动，窄窗口下审计内容统一滚动，长日志不再嵌套纵向滚动；直接点击“行为审计”或“查看全部”清除先前从最近会话带入的会话 ID，保留当前 Agent 范围。English: Collection diagnostics lists channel issues and report times, with evidence and next steps. The workspace header stays fixed. Audit columns scroll separately in wide windows; narrow windows use one scrolling content area. Long log blocks scroll with the reader. Diagnostics defer auto-refresh while scrolling. Opening Activity or View all clears the previous session link while retaining the agent scope.

**人工验收清单（无 UI 单元测试）：**① 中英文及窄窗口下五个标签、长路径和按钮可用；② 切换安装入口后 Skill、模型和任务范围正确，审批/系统事件翻页不混入其他 Agent；③ 从客户端跳转发现详情及返回策略入口；④ 在测试客户端分别核对 Skill 处置、模型切换/校验/恢复、插件任务和工具审批的服务端校验、重复点击及最终客户端回执；⑤ 检查无权限、离线、报告过期、读取失败和未发现安装入口的提示；⑥ 连续滚动长日志、系统事件及诊断原始报告，确认页头固定、无内外滚动交接，窄窗口底部操作可达。

客户端当前内置支持以下 Agent：

- Claude Code
- Codex
- Gemini CLI
- OpenCode
- OpenClaw
- Hermes
- TRAE CN
- TRAE
- Cursor
- CodeBuddy
- WorkBuddy
- TeleAgent
- Qoder、Qoder CN、QoderWork、ZCode

客户端还识别可由 OpenCode、Cursor 等读取的共用 `.agents/skills` 目录，并在界面中单独标明共享边界。以上 Agent 和目录支持 Skill 发现、接管、安装和巡检。其他工具可在桌面端点击“添加 Agent”，填写名称并选择或输入 Skill 根目录；自定义 Agent 会复用同一套治理流程。

## 平台发现配置与桌面入口

平台“客户端管理 → 全局客户端配置 → Agent 发现”（Client Management → Global client settings → Agent discovery）统一编辑全局发现配置，可按名称或标识搜索 Agent，设置启用状态、适用系统和
一个或多个 Skill 根目录。相对路径从客户端用户主目录解析，每行一个目录；动态用户目录可使用单独的 `*` 路径段。本机单独设置
的目录优先；没有配置缓存时使用客户端内置定义。目录不存在时不会因保存配置而自动创建。

Qoder、Qoder CN、QoderWork、ZCode 的预置目录分别为 `.qoder/skills`、`.qoder-cn/skills`、
`.qoderwork/skills`、`.zcode/skills`。TeleAgent 使用 `.config/TeleAgent/users/*/skills`，客户端会把动态用户目录展开为实际 Skill 根目录，不依赖固定用户 ID。Claude Desktop、Kimi Work、Doubao Work 的预置条目
默认关闭且没有目录，确认实际路径后再配置启用。

客户端详情的“客户端配置 → Agent 发现”默认逐项跟随全局；关闭某个 Agent 的“跟随全局”后，可为该客户端单独设置。允许添加客户端专属 Agent 定义；恢复单项继承清除该覆盖，全部恢复同时移除专属定义。本页独立保存，切换标签保留未保存草稿。

服务端按 Agent 标识合并全局与客户端定义，通过原有 `agent_discovery` 策略字段下发有效配置。只有有效发现配置变化的客户端才创建 `sync_policy` 任务；保存时校验全局与本客户端配置是否已变更，冲突时保留草稿并提示重新打开。

**Agent discovery** is a tab in **Client settings**, before **Skill governance**. Global definitions apply unless overridden per Agent for a client. Client-only definitions are supported. Restore individual inheritance to clear an override, or restore all to also remove client-only definitions. This tab saves independently and retains drafts across tab changes. The server merges definitions by Agent identifier and delivers the effective catalog using the existing policy and `sync_policy` mechanism, targeting only clients whose effective catalog changed.

在线客户端通过长轮询接收任务、读取最新配置并重新发现。
离线客户端继续使用已缓存配置。排查时分别核对“配置已同步”和“目录已发现”，不要只凭
平台心跳判断目录是否生效。

客户端以目录状态判断可管理 Agent：任一配置的 Skill 根目录存在时扫描其中的 Skill；
固定 Skill 根目录尚不存在、但其直接父目录存在时，仍显示并计入该 Agent，Skill 数量为 0，
同时保留预期的 Skill 根目录供后续安装创建。可执行文件或应用路径只作为补充信息，不参与
Agent 可见性判断。动态目录模式只使用已经存在的匹配目录，不会创建包含 `*` 的目录；没有用户 profile 时，已安装的 TeleAgent 仍可见，但不能作为 Skill 安装目标。客户端概览与 Agent 管理使用同一发现结果；共用 Skills 目录单独显示，
不计入 Agent 数量。

**English:** The client derives manageable Agent visibility from configured directory state. If a
configured Skills root exists, the client scans it. If the Skills root is absent but its direct parent
directory exists, the Agent is still shown and counted with zero Skills, while the expected Skills path
is retained for a later installation. Executable and application paths are supplemental signals only.
Dynamic root patterns expand existing directories only and never create a literal `*` directory. TeleAgent
therefore uses `.config/TeleAgent/users/*/skills` without depending on a fixed user ID; an installed app
without a user profile remains visible but is not offered as a managed-Skill installation target.
Client Overview and Agent Management use the same discovery result; shared Skills directories remain
visible but are excluded from the Agent count.

桌面“客户端概览”包含总览、运行与同步、检测策略、扫描能力和客户端信息。
本地 Skills 支持多选和当前页全选。翻页保留选择，切换 Agent 或修改搜索、认证筛选时清空选择。批量检测逐项调用真实提交逻辑，跳过当前内容签名匹配的已认证 Skill 和正在检测的项目；已认证行的检测按钮不可点击。Go 提交入口在重新发现及内容校验后再次核对认证状态。提交成功表示已提交快照，不表示检测通过。

批量卸载复用本地处置逻辑，确认框列出目标路径、共用目录影响及保留恢复副本选项。批量操作串行执行，逐项显示成功、跳过或失败及原因；一项失败不阻断后续项。成功和跳过项取消选择，失败项保持选中供重试；内容变化时需要重新选择。列表刷新失败单独提示，不覆盖已完成操作的结果。

English: Local Skills supports multi-selection and select-all on the current page. Selection persists across pages and clears when changing Agent, search or certification filters. Batch scanning skips certified content with a matching signature and skills already being scanned. Certified rows disable submission; Go rechecks certification after discovering and validating current content. Submission does not imply a passing scan. Batch uninstall confirms target paths, shared-directory impact and recovery-copy retention. Operations run sequentially with per-item results. Failures do not stop subsequent items; failed items remain selected for retry, while successful and skipped items are deselected. Changed content must be selected again. Refresh failures are reported separately from operation results.

#### 本地文件并发与上传 / Local file concurrency and uploads

上传打包只锁本次快照；同名副本的指纹补齐逐个尝试，忙碌副本留待自身提交时计算。AIDR 配置检查和安装使用独立配置锁。前台在创建快照之前取得提交记录锁，与后台复用同一提交结果；等待期间后台完成的检测不会被当成重新检测请求。文件冲突诊断记录实际冲突资源 `lock_resource` 和申请模式 `lock_requested_mode`；无法可靠获取持锁进程时记录 `lock_owner_status=unknown`，不把锁文件残留 PID 当成当前持锁者。

English: Packaging locks only the requested snapshot. Peer fingerprint discovery tries each same-name snapshot separately and leaves busy peers to their own submission. AIDR configuration uses a separate lock. Foreground submission takes the pending-record lock before creating a snapshot and reuses background results, including scans completed while waiting. Conflict diagnostics record the actual resource and requested lock mode; owner identity remains unknown rather than inferred from a stale PID in a lock file.

批量提交弹窗随后台状态刷新：若某项曾返回锁忙，但本次操作开始后同一内容快照已取得平台提交记录，则更新为提交成功并提示“该内容已提交”。不使用旧版本记录或仅在本地排队的快照判定成功；内容变化、权限或网络失败仍保留原结果。

English: The batch dialog reconciles lock-busy results when a background refresh confirms a platform submission of the same snapshot after the batch began. Historical submissions and local queues are not treated as new successes; content changes, permission failures and network failures retain their own results.

同一客户端状态目录下，桌面命令和后台巡检共用跨进程资源锁。锁同时识别目录入口和软链接解析后的物理目录；同一资源、父子目录及共享内容互斥，不同 Skill 可以独立执行。安装、接管、隔离、卸载、恢复、快照与副本清理均在修改前取得资源锁。多资源按路径排序申请；普通冲突最多等待 5 秒，嵌套清理遇到冲突立即返回 `skill_action_busy`，避免持有其他锁继续等待。共享隔离需一次登记多个恢复目标，登记期间锁定隔离存储目录。旧客户端和连接配置切换继续通过全局屏障与这些操作互斥。

提交先在文件锁内校验当前内容并创建完整 ZIP，随后释放文件锁再上传。独立的待处理记录锁及内容指纹锁协调前后台重复提交；上传期间不允许删除该待处理副本。进程异常退出后操作系统释放锁，完整快照保留供重试；服务端复用相同内容版本处理响应丢失后的重传。锁文件保留原 inode，不通过删除锁文件解除占用。文件锁约束遵守此协议的客户端进程；用户或外部 Agent 直接修改目录仍由内容签名复核检测。

Scanner 接口先按上传原始文件集重算 manifest 指纹，再在分析目录展开内嵌 ZIP。这样模板 ZIP 不会因为分析展开增加文件而触发传输指纹错误；内嵌内容继续参与分析，并沿用解包路径与容量校验。此修复同时需要新版客户端和服务端；仅替换客户端不能修复旧服务端的内嵌 ZIP 校验顺序。

English: Desktop commands and background patrol share cross-process resource locks within one client state directory. Locks cover both directory entries and resolved symlink targets, including parent/child conflicts. Unrelated Skills can proceed independently. Installation, takeover, quarantine, uninstall, restore, snapshots and copy cleanup acquire resource locks before mutation. Resources are sorted; ordinary contention waits up to five seconds, while nested cleanup fails with `skill_action_busy` instead of waiting with other locks held. Shared quarantine locks its storage directory while registering multiple recovery destinations. A global barrier coordinates legacy clients and connection changes.

Submission validates and packages content under file locks, then releases them before uploading. Separate pending-record and content-fingerprint locks deduplicate foreground/background submissions; an uploading snapshot cannot be discarded. Process exit releases OS locks and leaves completed snapshots retryable. The server reuses the same content version when a response was lost. Lock files retain their inode. External editors do not participate in this protocol; content signatures are checked again. Scanner imports verify the original uploaded manifest before expanding nested ZIPs for analysis, retaining extraction safety limits. The nested-ZIP fix requires the updated server as well as the client.

“Agent 管理”按 Agent 切换本地 Skills、检测记录和隔离副本。“执行记录”分为巡检与处置、
平台任务。巡检与处置支持按关键词、Agent、事件类别、处理情况和时间筛选及分页；列表展示
Skill / Agent、事件与原因、处理情况、发生时间。具体标题区分加载、文件读取、巡检发现和
文件处置。“仅记录”保留本地文件；告警状态与隔离、卸载、恢复等操作结果分别呈现，缺少
处置结果时保持未确认。点击记录可查看原因、系统处理、证据时间线和技术标识。

使用审计的发生时间取精确关联证据的最早行为时间；缺少行为时间时标为“记录到达”。
巡检记录显示最近发现时间及累计发现次数。“最近核对”单独展示，定期核对不改变旧行为
的列表排序和时间筛选。时间以北京时间显示。桌面证据时间线展示来源、阶段和发生/到达时间；
平台相同列表另有“查看行为证据”入口，进入已有行为详情及重新采集流程。
切换到执行记录会重新加载第一页，页面打开期间收到新的治理通知也会自动刷新第一页。
右上角齿轮进入设置，铃铛进入安全通知。

**English:** Activity Records separates inspection/remediation events from platform tasks. Event lists
show Skill/Agent, specific event and reason, handling and event time. Search, Agent, category, handling,
time range and pagination use the same semantics on desktop and platform. Record-only findings retain
local files; alert conditions and file action outcomes are separate. Unrecorded outcomes remain unknown.
Details show the reason, system handling, evidence timeline and technical identifiers. Usage audit time
is the earliest explicit occurrence time in exactly linked evidence, falling back to a labeled record
receipt time. Inspections show the latest finding time and count. Check time is separate; periodic checks
do not change old activity ordering or date filtering. Times are displayed in Beijing time. The platform
also links to full Skill activity evidence and recollection. Page entry and new governance notifications
refresh the first page.

平台任务按实际动作显示，例如“安装 Hook 插件”“检查 Hook 插件接入”“自动应用接入与采集策略”，并显示目标 Agent、任务编号、策略和插件版本。策略任务可展开查看当次保存的通道、模式及自动安装/更新目标；这些是任务目标，执行结果以该行状态和错误为准。类型筛选可直接选择具体 Hook 操作，Agent 筛选包含策略任务中的多个目标。历史记录无需迁移，缺少字段时保留未知，不使用当前策略补写旧任务。

**English:** Platform tasks show their specific action, target Agents, task ID and policy/plugin versions. Expand a policy task to inspect its saved channel, mode and installation/update targets; task status and errors report its outcome. Type filters distinguish Hook operations, and Agent filters include all policy targets. Historical records are read as stored; missing details are not reconstructed from today's policy.

人工验收 / Manual checks：① 安装、更新、自检、接收器启停及策略任务名称可区分；② 展开策略任务并核对历史版本和目标；③ 按 Codex / Claude Code、具体动作、状态及时间组合筛选并翻页；④ 老记录缺少目标时正常展示；⑤ 中英文及客户端最小窗口下任务、错误详情与筛选可读。未新增 UI 单元测试。

2026-10-07 已用开发包检查中英文真实历史任务、策略目标展开和错误文案，自检类型筛选返回两条对应历史记录。历史 API 回归 3 项、桌面 i18n 检查 29 项和开发包构建通过；完整筛选组合及其他操作类型仍按上述清单人工验收。

## 模块化治理的边界

客户端的治理单元是“本机 Agent 身份 + 实际 Skill 根目录 + 具体 Skill”，而不是把整台
主机视为一个不可拆分的可信单元：

- 一个本机 Agent 可以配置一个或多个实际 Skill 根目录；客户端会解析符号链接，避免同一
  物理目录仅因路径别名被重复识别。
- Agent 强授权模式下，每个支持 Skill 管理的本机 Agent 使用客户端上报后自动登记的身份，
  并按该身份的 Skill 允许范围过滤安装和巡检结论。
- 修改、修复、移除和隔离以具体 Skill 安装记录为目标。执行后仍应核对目标 Agent、路径、
  版本、任务状态和事件，不能只依赖按钮提示。
- 共用 `.agents/skills` 目录单独显示可能的读取者，但目录本身不能证明实际调用者身份，
  因此不作为某个本机 Agent 的强授权身份。
- 启用会修改文件的动作前，先使用“仅记录”或“记录且告警”核对根目录、共享边界和事件归属。

帮助中心“场景实践 → 客户端模块化治理”提供一台 Codex 与 Claude Code 共存工作站的
完整演练和下载清单。

## 客户端设置

右上角“设置”集中管理当前设备的偏好：

- 平台连接：保存多个 Agent Manager 地址及各自的客户端名称、接入凭证；凭证仅保存在当前用户可读的 `~/.agent-manager/config.json`（权限 `0600`）中，不会返回桌面渲染进程。新增连接会先验证再保存；切换已保存连接时使用该连接自己的凭证重新注册，成功后才设为当前连接并重启后台服务。
- 显示语言：简体中文或英文。
- 默认打开页面：客户端读取状态后优先进入的页面。
- 系统通知：控制是否把安全事件和新版本发送到操作系统通知中心；本地通知记录不受影响。
- 最低提醒级别：低于所选级别的事件只保留在客户端通知中心。
- 同一内容签名、风险结论、处置动作和策略版本对应一个持续告警；后续巡检只累计观察次数，不重复发送系统通知。上述结论或处置结果发生变化，以及已隔离或卸载后同一内容重新出现时，会生成新的通知。客户端升级时会折叠旧版本产生的同类重复告警，避免历史待发送记录继续弹出。
- 后台运行：连接后自动启动用户级后台服务；查看状态并在失败时重试启动。
- 自动检查更新：控制接入平台后的静默更新检查。
- 更新通道：正式通道或测试通道；测试通道尚未发布版本时按“已是最新版”处理。
- 诊断：选择日志保留时间与导出最近天数，打开日志或数据目录，导出不含接入凭证明文、原始数据库和 Skill 源文件的报告。诊断包中的 `runtime.jsonl` 会记录客户端命令、后台治理动作及文件锁竞争；锁竞争失败还包含持锁进程 PID、锁更新时间和锁龄，可用于关联前后操作。发送前仍应检查主机、路径和运行信息。

客户端不提供通知提示音设置。

点击 Agent/Skill 路径、打开日志或数据目录时，Windows 客户端通过系统 Shell API 打开目录；文件路径会打开所在目录并选中文件。客户端按 Shell API 的请求结果返回状态。诊断包的 `runtime.jsonl` 中，`path_open_finished` 记录目标路径、耗时、`accepted`（系统已接受请求）或 `failed`、稳定错误码和原始系统错误信息；`accepted` 不表示已经观察到目录窗口显示。

**English:** On Windows, Agent/Skill paths and the log/data directory actions use the system Shell API. File paths reveal and select the file in its parent folder. The `path_open_finished` diagnostic event records the target path, duration, request outcome (`accepted` or `failed`), stable error code and original system error details. `accepted` means the Shell accepted the request; it does not confirm that a folder window was observed.

同一时刻只有一个连接处于活动状态。切换平台会沿用既有安全边界：旧平台的认证、策略、任务和安装关联会从本地运行状态中清理，再同步目标平台；本地 Skill、恢复副本、扫描目录设置和已保存连接不会删除。目标平台不可达或凭证无效时不会改变当前连接。

**English:** Settings can save multiple Agent Manager addresses, each with its own client name and credential. Credentials remain in the current user's `~/.agent-manager/config.json` with `0600` permissions and are never returned to the desktop renderer. The Client validates a new or saved target before making it active. Only one connection is active at a time; a successful switch clears previous platform certification, policy, task, and installation associations before resyncing, while retaining local Skills, recovery copies, discovery settings, and saved connections. A failed validation leaves the current connection unchanged.

客户端内部语言与 macOS Finder 中的应用名称相互独立。Finder 会按照 macOS
系统首选语言读取安装包内的 `InfoPlist.strings`：中文显示“智能体生命周期管理系统客户端”，
英文显示“Agent Manager Client”。切换客户端内部语言不会立即重命名 Finder 中的应用。
各语言共用同一安装包，不需要重复打包。

## Agent 日志只读读取（P1-01）

`agent-manager-client agent-log-read --agent claude` 或 `--agent codex` 发现当前用户日志并输出有界的工具调用/结果元数据。可用 `--root`、`--file` 限定绝对路径，`--cursor` 读取上一次输出的游标对象进行增量续读；命令不覆盖游标，不启动 Agent，不联系平台。

默认回溯 24 小时，单轮总预算 4 MiB / 500 事件 / 5 秒，单条记录上限 2 MiB。半行等待追加；未知格式停留坏记录起点；超限记录按块跳过并明确保留覆盖缺口、范围和跳过字节，后续正常事件可以继续读取。命令、工作目录、明确目标和结果依据按白名单脱敏投影；完整 Prompt、文件正文、完整结果及未知参数不输出；进程关联保持 `unknown`。

当前读取器实机样例范围为 macOS 上 Claude Code 2.1.220、Codex 0.155.0-alpha.9.2；其他版本及 Windows/Linux 真实日志尚未认证。持久化和平台接入见下文；样例读取验证不等于全链路验收完成。
参数、游标及稳定原因码见 [读取器说明](../scanner/internal/aidr/agentlog/README.md)，测试范围见 [P1-01 验收记录](../experiments/aidr-agentlog/ACCEPTANCE.md)。

## Agent 日志本地持久化（P1-02）

使用 `agent-manager-client agent-log-collect --state-dir <绝对私有目录> --agent claude|codex --root <日志根> --file <日志文件>` 将一次有界读取的脱敏事件、证据、覆盖和游标原子落库。重复运行从数据库游标继续；不启动常驻服务，不连接平台。

`agent-log-state --state-dir <目录>` 查看本地状态；`--action events` 分页查询，`--action prepare` 准备并持久化待上传批次，`--action prune` 清理已确认且过期的历史正文。`aidr-sync` 负责上传已准备的批次并验证回执。

容量不足时暂停落库并保留游标。正文过期清理与采集缺口分别记录，不能把历史淘汰显示成归属失效。参数、错误码、配额和恢复边界见 [本地存储说明](../scanner/internal/aidr/localstore/README.md)，证据见 [P1-02 验收记录](../experiments/aidr-agentlog/STORE_ACCEPTANCE.md)。

## Agent 日志平台接入（P1-03～05）

设备详情提供“Agent 日志观察”，首先显示合并调用与结果的可读操作，支持 Agent、会话、工具、结果和时间筛选。详情展示脱敏命令、目标、结果依据及来源证据，JSON 放在次级区域。来源覆盖、能力和计数可展开，当前缺口仍醒目提示。进程关联保持未知；离线统计取自最后一次心跳。

管理员配置的采集策略启用后默认允许上报；显式暂停的设备需恢复上报。签发绑定该设备的 client 凭证，授予 `aidr:heartbeat`、`aidr:report-events`。服务端校验设备身份，管理查询和启停复用设备可见性及角色权限。`aidr-sync` 显式运行并通过已验证的持久化 ACK 清理待发队列，不安装常驻服务。命令、批量限制、退避和容量语义见 [上传说明](../scanner/internal/aidr/upload/README.md)。全链路验收状态见 [P1 平台验收记录](../experiments/aidr-agentlog/PLATFORM_ACCEPTANCE.md)。

## macOS 运行时只读连接（开发阶段）

`agent-manager-client runtime-watch --socket <绝对路径>` 提供本地运行时事件流入口。
该命令独立于平台连接，不读取平台 Token、不初始化客户端数据库；以普通用户运行。
ES 采集器由管理员单独启动，通过受保护的 Unix socket 向管理员指定的用户发送事件。
桌面“Agent 运行治理”包含“接入与采集”和“系统采集”。系统采集的最近事件直接展示 Agent 根进程 PID、直接匹配或后代归属；事件诊断中查看进程身份、会话、序号和原始记录。日常操作使用这一入口，无需填写 Socket。页签支持方向键、Home 和 End。

以下 `runtime-watch` 是独立开发命令，其输出不参与桌面系统采集的运行状态。

输出为逐行 JSON，包含协议版本、连接状态、采集器健康、监控会话和原始事件。
每次连接或重连都会输出 `reset=true`，消费者应清空连接内缓存的归属；
服务端 `hello` 的 `stream_start=late_join`、`attribution_baseline=unknown`
表示从当前时刻订阅，不能假定已经取得完整进程树。
传输连接正常、采集器心跳正常与事件覆盖完整是分别判断的状态。

授权范围是指定本地用户读取采集器提供的全机进程元数据，当前未按进程 UID 过滤。
本地 socket 双向校验对端身份；采集器不接受客户端提供的执行命令或策略变更。
事件流不自动上传平台，也不写入普通客户端诊断日志。
macOS 以外的平台目前返回 `runtime_observation_unsupported_platform`。

开发部署、构建与实机验证见
[`experiments/macos-es-poc/`](../experiments/macos-es-poc/README.md)。
正式使用仍需要完成签名、权限授予和系统服务部署验证。

**English:** `runtime-watch --socket <absolute path>` is a development-stage,
unprivileged CLI subscription to a separately started privileged macOS observer.
It does not require platform credentials or initialize the client database.
Every connection emits a reset; a late-join subscription has no complete process-tree
baseline. Transport, observer heartbeat and coverage are distinct states. The
administrator authorizes the selected user to receive system-wide process metadata;
process-UID filtering is not implemented. Other platforms show an unsupported state.
For everyday desktop use, open Agent Runtime Governance → System collection.
Recent events show the Agent root PID and direct or descendant attribution;
event diagnostics contain exact process identity, monitor, sequence and raw records.
This desktop flow uses the managed system collector and requires no socket input.

## 1. 构建

桌面版（推荐）：

```bash
cd client/desktop
npm install
npm run build
```

macOS 安装包输出到 `client/desktop/src-tauri/target/release/bundle/macos/`。CI 会按 macOS、Windows、Linux 分别生成桌面安装包。

只构建后台单二进制：

```bash
cd scanner
./scripts/package.sh v0.1.0
```

输出文件位于 `scanner/releases/`：

```text
agent-manager-client-darwin-arm64
agent-manager-client-darwin-amd64
agent-manager-client-linux-amd64
agent-manager-client-linux-arm64
```

## 2. 创建客户端凭证

管理台进入：

```text
智能体管理 -> 统一凭证中心 -> 创建凭证
```

在统一凭证中心选择“给客户端使用”。如果希望在桌面客户端里切换本机 Agent 使用的网关模型，同时勾选“允许客户端为本机 Agent 自动创建运行凭证”。该选项默认关闭；客户端凭证明文仍只展示一次。开启后还可以设置“允许客户端配置的模型”：留空表示所有已启用模型，选择具体模型则形成客户端的委派上限。这个允许列表不代表客户端凭证本身可以调用模型。

## 3. 注册客户端

```bash
export AGENT_MANAGER_CLIENT_SERVER="http://127.0.0.1"
export AGENT_MANAGER_CLIENT_TOKEN="amat_xxx"

./agent-manager-client-darwin-arm64 register
```

客户端自动发现本机 Agent 和用户级 Skill，并上报平台。管理台进入：

```text
智能体管理 -> 客户端管理
```

默认使用“客户端安全治理”。切换为“Agent 强授权”后，平台按本机 Agent 自动登记的身份校验 Skill 范围，无需额外关联。

### 在桌面客户端切换网关模型

桌面客户端的“模型切换”页以本机实际配置为入口，而不是以平台 Agent 表单为入口：

1. 先选择本机发现并报告模型配置能力的 Agent。配置适配覆盖 Claude Code、Claude Desktop、Codex、Gemini CLI、Grok Build、OpenCode、OpenClaw、Hermes 和 Pi；各版本实测结果见 [验证矩阵](acceptance/model-switching-2026-09-13/README.md)。
2. 页面直接读取本机配置文件，显示当前模型、网关地址和配置路径。
3. 模型列表只显示当前客户端凭证委派范围内、且模型与供应商都已启用的网关模型。
4. 点击“切换”，检查参数表单和配置差异。“未设置”保留原配置；填写值才显式修改。如果该本机 Agent 尚无运行身份且客户端获准委派凭证，平台会自动补全归属当前客户端的运行身份。
5. 客户端保存备份、写入并重新读取配置，显示待重启状态。有调用验证能力的 Agent 可执行“验证调用”，用隔离配置和最小提示核对真实响应与网关审计。现有会话仍需重启。
6. “恢复配置”恢复最近备份，执行前核对当前文件版本；出现后续编辑时报告冲突。失败任务可查看原因并重试，原版本条件仍然有效。

**English:** Select a discovered Agent with model configuration capability, choose an authorized model, and review Agent-specific parameters and the configuration preview. Unset fields preserve existing values. The client backs up, writes and reads back the configuration. Existing sessions need restarting. Where available, “Verify call” checks an isolated native response against gateway audit evidence. Recovery restores the latest backup only if the current files still match. See the [matrix](acceptance/model-switching-2026-09-13/README.md) for actual native coverage.

![桌面客户端模型切换页面](../web/public/docs/screenshots/zh-CN/client-app-models.png)

> 截图使用脱敏示例数据。页面中的“网关地址”和“配置文件”来自本机实际配置。

#### 网关地址从哪里来

桌面客户端不提供单独的“模型网关地址”输入框。首次接入或在“客户端概览 -> 修改连接”中填写的 **Agent Manager 地址**，同时作为自动写入模型配置时的网关根地址：

- Claude Code 直接把该地址写入 `ANTHROPIC_BASE_URL`，调用 `POST /v1/messages`。
- Codex 和 Hermes 会把该地址规范化为以 `/v1` 结尾的 Base URL，分别调用 `POST /v1/responses` 和 `POST /v1/chat/completions`。
- 如果接入地址本身已经以 `/v1` 结尾，客户端不会重复追加。

这里的 Agent Manager 地址不是上游模型供应商地址。管理员仍需在“模型网关 -> 供应商 / 模型”中配置 OpenAI、Anthropic、DeepSeek 等上游地址和密钥；桌面客户端只把本机 Agent 指向 Agent Manager 网关。部署时应确保客户端所在主机能够访问该地址，并且反向代理已经转发上述模型协议路径。

客户端接入凭证本身不能调用模型或 MCP。切换时，sidecar 通过具体任务一次性领取绑定目标 Agent 的独立运行凭证，凭证明文不进入任务载荷、客户端状态接口或桌面渲染进程。自动创建的托管 Agent 只是运行身份和审计载体，不表示模型需要与 Agent 类型匹配；模型范围仍由客户端凭证委派范围和网关启用状态决定。生成的凭证固定包含 `runtime:verify-signature`、`runtime:can-load`、`runtime:check-tool` 和 `model:chat`，且只允许本次选择的模型；不包含 `runtime:govern`。如果该平台 Agent 已有允许的 MCP 网关，生成凭证还会带上 `mcp:connect`、`mcp:list-tools`、`mcp:call-tools`，并保留相同网关允许列表；MCP 服务器配置仍由单独的 MCP 功能管理。

当前写入范围：

| Agent | 实际配置 | 网关协议 |
|---|---|---|
| Claude Code | 合并 `~/.claude/settings.json` 中的 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_AUTH_TOKEN` | `POST /v1/messages` |
| Codex | 合并 `~/.codex/config.toml`，创建 `agent_manager` model provider，写入 `wire_api = "responses"` 和 Agent 独立 bearer token | `POST /v1/responses` |
| Hermes | 合并 `~/.hermes/config.yaml` 的 `model.default/provider/base_url/api_mode`，并把 Agent 独立凭证写入权限为 `0600` 的 `~/.hermes/.env` | `POST /v1/chat/completions` |

修改前的配置会备份到 `~/.agent-manager/config-backups/`。写入只替换模型路由相关字段，并保留其他设置；包含凭证的配置文件使用当前用户私有权限。命令行也可以执行相同流程：

```bash
./agent-manager-client-darwin-arm64 switch-model \
  --agent-type codex \
  --model gpt-5-codex
```

不在内置列表中的 Agent，无需开发新适配器。进入“Agent 管理 → 添加 Agent”，填写便于识别的名称，并选择包含多个 Skill 子目录的绝对路径。移除自定义 Agent 只取消登记，不会删除该目录中的文件。客户端上报后，本地 Agent 会自动出现在平台“智能体列表”，来源标记为“客户端发现”，详情保留客户端实例、Skill 目录和扫描证据。

## 4. 命令行接管已有目录

先预览，不修改文件：

```bash
./agent-manager-client-darwin-arm64 takeover \
  --skill /Users/example/.codex/skills/code-review
```

确认预览后执行：

```bash
./agent-manager-client-darwin-arm64 takeover \
  --skill /Users/example/.codex/skills/code-review \
  --confirm
```

Agent 强授权使用客户端上报后自动登记的本机 Agent 身份，无需额外传入平台 Agent 映射。上述预览和确认属于命令行接管流程；桌面日常操作入口为“Agent 管理”，按本地 Skill、检测记录和隔离副本分别处理。

接管规则：

- 客户端安全治理：Skill 为 `APPROVED` 且签名一致时进入 `~/.river-security/agent-manager/skills/`。
- Agent 强授权：还必须通过智能体允许范围校验。
- 其他 Skill：备份后移入 `~/.river-security/agent-manager/pending/`。
- 用户在选择性接管中明确未勾选的路径保留原状，并记为当前治理范围外；接管完成后新出现的未知 Skill 仍会按策略检测。
- 原始内容备份到 `~/.river-security/agent-manager/backups/`。
- 接管失败时恢复原目录。
- 已接管的 Skill 在刷新预览时显示“已接管”，不会再次复制、备份或替换。

`~/.agent-manager/` 只保存配置、数据库、日志、锁和运行触发文件。升级时，客户端会把旧版 `skills`、`pending`、`quarantine`、`backups` 内容迁入 `~/.river-security/agent-manager/`，并保留旧路径兼容入口，现有 Agent 软链接无需重新接管。

## 5. 启动后台巡检

执行一次心跳、任务和完整性检查：

```bash
./agent-manager-client-darwin-arm64 run-once
```

持续运行：

```bash
./agent-manager-client-darwin-arm64 run --interval 30s
```

本地状态保存在：

```text
~/.agent-manager/client.db
```

默认常规巡检周期为 5 分钟，完整巡检周期为 30 分钟；文件变化也会触发检查。文件事件会先在本地按最近一次成功同步的分类策略处理，不能等待平台比对完成；平台不可达、502、连接失败或 `/compare` 超时时，不会把已有可信 Skill 改成“待确认”。平台比对成功但只返回部分结果时，仅更新有明确结果的 Skill，其余保留原认证状态。新发现且没有本地可信基线的 Skill 才会进入“待确认”。
新 Skill 被发现并写入本地清单后，后台服务发送清单变化事件，桌面端据此刷新，不等待平台清单上传或巡检结论；动态用户目录和本机配置的 Agent Skill 目录下新增的 Skill 也会触发文件监听。
心跳最长约每 10 秒一次。平台任务通过独立长轮询获取，分类策略和发现配置的同步任务
无需等待下一次心跳。网络重连、执行队列和平台不可用仍可能造成延迟。

手动巡检入口为“设置 → 后台运行 → 查看运行诊断 → 立即执行巡检”，按当前有效策略执行。
平台不可达时继续使用最近成功同步的策略，事件持久化后等待补报；平台验证或下载失败
需要在恢复连接后重试。

### Token 压缩 / Token compression

管理台“客户端策略 → Token 压缩”设置模型切换自动签发凭据的压缩开关和级别（均衡、保守、激进），支持平台默认与单客户端覆盖。默认关闭。保存更新已有自动运行凭据；新建和轮换凭据继承当前值。长轮询同步桌面端配置及版本，网关在后续请求中读取凭据配置。实际节省量取决于内容，可在模型网关调用记录中查看。

**Client policies → Token compression** configures compression and its balanced, conservative, or aggressive level for runtime credentials issued by model switching. It defaults to off and supports platform defaults and per-client overrides. Saving updates existing automatic credentials; new and rotated credentials inherit the current values. Long polling synchronizes desktop settings and versions, while subsequent gateway requests use the saved credential settings. Savings depend on content and can be inspected in gateway request records.

### Prompt 防护 / Prompt Guard

管理台“客户端管理 → 客户端策略 → 接入与运行”配置公共 Prompt 防护；客户端详情的“客户端策略”可继承默认或单独覆盖。默认仅记录，支持关闭、仅记录、告警并放行、阻断风险请求。阻断模式拦截高风险及不可信来源的中风险命中。LLM 复核开关目前仅保存，网关尚未执行 LLM 复核。

保存前预览展示各客户端的新旧配置和将更新的自动运行凭证数量。保存后更新模型切换自动创建的有效运行凭证，后续新建与轮换凭证继承当前策略。模型网关在后续请求中执行新配置，无需重新切换模型。现有长轮询下发策略同步任务，桌面“检测策略”展示已缓存的防护模式、复核开关及同步状态；离线缓存不代表网关仍使用旧策略。

Configure shared Prompt Guard settings under **Client Management → Default Client policies**. Individual **Client policies** can inherit or override them. The default is log only. Modes are off, log only, warn and allow, and block risky requests. Block mode stops high-risk findings and medium-risk findings from untrusted sources. The LLM review flag is currently stored without executing an LLM review.

The preview shows each client's current and proposed settings and affected automatic credential count. Saving updates active runtime credentials created by model switching; newly issued and rotated credentials inherit the current policy. Subsequent gateway requests use the saved settings without another model switch. Existing long polling delivers policy synchronization tasks. Desktop policy details show cached settings and synchronization status; offline cache does not indicate the gateway still uses that policy.

![客户端默认策略：Prompt 仅记录、Token 压缩关闭；示例数据](../web/public/docs/screenshots/zh-CN/client-policy.png)

![Default client policy: log-only Prompt Guard, Token compression off; example data](../web/public/docs/screenshots/en-US/client-policy.png)

### 分类处置策略

平台默认策略提供公共规则；客户端详情可逐项继承默认或单独设置。单台客户端覆盖项不随
默认值变化。客户端“检测策略”显示本机已同步的有效规则。

| 触发情况 | 可用动作 |
| --- | --- |
| 未经平台认证、未认证 Skill 内容变化 | 仅记录、记录且告警、提交平台检测、隔离 |
| 已认证 Skill 内容变化 | 仅记录、记录且告警、提交平台检测、隔离、恢复可信版本 |
| 平台确认恶意 | 仅记录、记录且告警、隔离、卸载（保留恢复副本） |
| 变化内容检测不通过（有可信版本） | 仅记录、记录且告警、隔离、恢复可信版本 |
| 内容检测不通过（无可信版本） | 仅记录、记录且告警、隔离 |

“仅记录”和“记录且告警”均保留本地文件，后者还产生安全告警。尚未批准的当前内容被平台
确认恶意时，按恶意内容规则处置；`APPROVED`/`DEPLOYED` 是最终认证结论，内容签名一致时
客户端显示“已认证”，扫描阶段的风险仍保留在平台报告中但不覆盖审批结论。上传失败、超时
和扫描错误不等于检测不通过，不触发拒绝处置规则。

保存前预览按客户端汇总 Agent 数、Skill 数和预计动作，逐层展开查看 Agent、Skill 与目录。
“暂无法预估”表示资料不足，实际执行仍会重新校验。策略同步成功表示配置已应用，具体
Skill 是否处置完成需在事件和执行记录中确认。平台客户端详情最近事件每页 10 条，支持
翻看更早记录。

## 6. 平台安装和卸载

在“客户端管理”中：

1. 打开客户端详情。
2. 点击目标 Agent 的“下发 Skill”。
3. 选择 `APPROVED` Skill。

Agent 强授权模式下，列表只显示该本机 Agent 自动登记身份允许使用的 Skill。

客户端通过长轮询获取任务后，会验证 Ed25519 发布签名和逐文件 SHA-256。签名或文件哈希不一致时拒绝安装。
Windows 普通用户即使没有创建目录符号链接的权限，也会在验签成功后自动改用原子目录副本完成安装，
不要求开启开发者模式或以管理员身份运行。失败过程中不会把未复制完整的目录暴露给 Agent；升级后的后台巡检会继续重试此前保留的待安装记录。
桌面端同一次选择多个 Agent 安装时，客户端会先逐个确认目标 Agent 的使用权限，再只下载、验签和
解压一次安装包，随后将同一份受管 release 逐个绑定到目标 Agent。进度弹窗分别显示共享内容准备阶段、
已完成目标数和每个 Agent 的成功或失败；单个目标失败不会阻断其余目标，失败项可以单独重试。
即使历史内容变化导致第一个成功目标安装到 `copy-*` 安全副本，其他目标也会链接到该副本，不会重复
创建内容相同的独立副本。升级前已经产生的重复副本会在后台核验完全一致后统一入口链接，旧物理目录
继续保留，不在迁移时删除。

卸载和普通隔离属于快速本地处置：客户端先重新校验当前内容签名并取得互斥锁，立即完成文件移动、安装记录更新和恢复副本收据写入，再异步补报平台事件；断网时事件进入本地队列，联网后自动补报。手动卸载确认时可选择保留恢复副本；只有手动卸载且选择保留的副本允许恢复，策略隔离、自动隔离和未保留副本不可手动恢复。恢复请求仍须先取得平台授权任务，但客户端收到任务后使用本地副本和缓存状态立即恢复原目录，完成文件与收据校验后刷新界面，平台结果在后台静默补报。只有本地文件、安装记录和恢复副本一致性校验通过才显示成功。桌面端“从平台安装”直接执行本地批量安装，完成后上报安装事件并重新发现本地目录；由平台下发的安装和跨 Agent 部署任务仍持续跟踪，任务成功后客户端主动刷新列表。
任务失败时保留当前列表项并显示最终失败原因。重启桌面端后，尚未完成的处置任务会继续跟踪，
不需要重复提交。

## 7. 备份恢复

隔离、接管备份及安装前备份会保留目录结构、普通文件和符号链接原文（包括悬空链接），不沿内部符号链接复制外部内容。删除或替换原目录前，核对源目录与副本的文件内容、目录结构、权限模式和链接文本；`.git` 等扫描忽略目录也参与恢复校验。单次目录复制最多 1 GiB 普通文件内容、100,000 个条目（含根目录），超限或遇到不支持的文件类型则失败并保留源目录。隔离复制、校验或入库失败时清理本次未登记副本；已登记副本在源目录删除失败时仍保留用于恢复。

分类策略的自动隔离、卸载和恢复可信版本失败后，重试间隔从 30 秒倍增至最多 30 分钟，并持久化到本地观察记录。内容、处置动作或策略版本变化会重新开始处理，手动操作可立即重试。已有历史备份和恢复记录按原生命周期保留。

**English:** Quarantine and recovery backups preserve regular files, directory structure and symlink text, including dangling links, without traversing internal links. Source and copy are checked before replacement or removal, including scan-ignored directories. Copies are bounded to 1 GiB of regular-file contents and 100,000 entries including the root. Copy, verification or database failures remove the new unregistered quarantine copy; a registered copy remains available when source deletion fails. Failed classification-policy file actions use persisted exponential retry delays from 30 seconds to 30 minutes. Content, action or policy changes reset the delay; manual actions can retry immediately. Existing recovery records retain their lifecycle.

桌面客户端在“设置 → 高级恢复”中可以查看历史备份并发起按 Skill 的恢复任务。执行时仍需平台授权和内容校验。命令行也可以操作：

```bash
./agent-manager-client-darwin-arm64 backups
./agent-manager-client-darwin-arm64 restore --backup 20260716T120000Z --confirm
```

恢复前会再次备份当前同名 Skill。备份目录只接受 `~/.river-security/agent-manager/backups/` 下的真实目录；升级后的客户端仍可读取旧版 `~/.agent-manager/backups/`。备份不跟随外部软链接，内置和自定义 Agent 均按当前登记的 Skill 根目录恢复。

隔离副本位于对应 Agent 的“隔离副本”页，可提交当前内容检测。提交时按行显示状态；进入待人工审核后，本地 Skill、检测记录和隔离副本会在状态旁显示平台版本号，避免审核或处置时混淆同名 Skill 的不同版本。已有提交批次运行时，点击其他 Skill 的“提交检测”会提示等待当前提交完成。如果恰逢后台自动恢复等文件操作，客户端会在保持文件互斥保护的前提下等待最多 5 秒，锁释放后继续提交，超时才提示稍后重试。
检测提交归属绑定客户端 ID，而不是某一条客户端凭证。给同一客户端轮换或新建凭证后，只要凭证仍绑定该客户端并包含 `client:submit-skill`，就可以继续读取该客户端此前提交或重扫的结果；不同客户端之间仍隔离。普通 Scanner 凭证继续按具体凭证隔离。
通过平台批准后，后台按提交对应的版本、原 Agent 和原路径尝试安装或恢复。
精确匹配平台已有批准版本的隔离内容也可进入自动恢复检查，不要求重复提交。

自动恢复需要当前内容、策略和授权均通过校验。原路径已有内容、目录无法确定、源文件
失效或权限错误会阻止恢复；不会仅凭同名覆盖当前文件。手动隔离不会因后台匹配自动解除。
“检测通过”仅是检测结论，不能当作恢复已完成。未恢复时查看安全通知、行详情和执行记录。

本地 Skill 认证需要实际内容与平台批准版本匹配。
“认证状态待确认”应展开查看具体原因，路径损坏或指纹校验失败不会靠等待自行修复。

客户端提交默认允许总内容 100 MiB、单文件 20 MiB、最多 20000 文件。
客户端凭证默认请求体为 102400 KB，旧凭证保持原配置；服务端限制另行校验。
指纹不一致属于内容校验问题，不应通过扩大上传额度处理。

命令行可只读查看隔离记录：

```bash
./agent-manager-client-darwin-arm64 quarantine
```

## 8. 后台服务

桌面客户端连接后自动配置当前用户级后台服务：macOS 使用 LaunchAgent，Linux 使用 systemd user service，Windows 使用登录计划任务。Windows 计划任务直接保存后台 EXE 和启动参数，不经过批处理文件，因此中文用户名和中文安装目录不会受 `cmd.exe` 代码页影响；创建、修复或删除任务需要系统授权时仅对任务注册操作请求 UAC，后台进程仍以当前登录用户的受限权限运行。旧版本生成的 `~/.agent-manager/agent-manager-client.cmd` 会在新任务成功启动后移除。可在“设置 → 后台运行 → 查看运行诊断”核对服务状态并立即执行巡检。停止后台服务会同时停止平台任务同步。

Windows 正式安装包将桌面主程序和内置后台程序构建为 GUI 子系统：桌面调用仍通过管道读取命令结果，登录计划任务在后台静默运行，不显示额外控制台窗口。后台任务查询、校准和启停使用的 PowerShell 子进程，以及 Agent/Skill 发现和模型验证期间执行的 Agent CLI，均以无窗口方式启动；需要系统授权时仍正常显示 UAC，不显示额外 PowerShell 控制台。开发调试构建保留桌面控制台，便于排查启动日志。

```bash
./agent-manager-client-darwin-arm64 install-service
./agent-manager-client-darwin-arm64 service-status
./agent-manager-client-darwin-arm64 uninstall-service
```

后台定时任务使用轻量巡检，并按策略周期执行完整文件校验；桌面端“立即执行巡检”和命令行 `run-once` 会强制执行一次完整文件校验。

后台文件监听会把编辑器一次保存产生的连续事件合并为约 300ms 的稳定窗口，并保留具体变化路径。
对已有签名安装记录且本地策略要求隔离或卸载的可信 Skill 内容变化，后台只重新计算受影响的
物理 Skill，使用本地可信签名和已同步策略立即处置，不等待全量 Agent 发现、平台 Compare 或
事件上传；提交平台检测的动作也先在本地生成不可变快照和 pending 收据，再由后台静默上传，
不把平台响应等待暴露给页面。处置后先增量保存本地清单并原子更新 UI revision，桌面端通过操作系统文件事件读取
不访问平台的本地快照；完整发现、平台确认和事件补报随后在后台完成。后台会短暂忽略本次处置
自身产生的对应目录文件事件，避免再启动一轮重复巡检。无法建立可信本地基线、文件已损坏、
新增或未受管 Skill，以及需要平台参与的动作仍进入完整治理流程。桌面端不再用固定的业务轮询
刷新清单；revision 用于过滤重复界面事件，客户端收到本地事件、切换到页面或从后台回到前台时
读取一次本地快照作为补偿刷新。后台保留低频巡检和平台长轮询作为服务级漏报兜底，不影响页面
交互响应。文件事件队列满时会持久化合并后的路径，重启后继续处理，不丢弃为一次同步全量巡检。
客户端只有在快照及当前页面所需分区读取成功后才确认 applied revision；读取失败时
会合并为一个有限次数的退避重试，并始终优先处理最新 revision。平台扫描事件按 revision 顺序
消费；本地 pending 已不存在的事件会记录 `pending_not_found` 并推进游标，可重试的存储错误则
暂停当前批次，避免跳过失败事件。

桌面客户端启动时会校准后台服务身份与状态：服务未运行、后台二进制 SHA256 已变化，或者同名服务实际指向其他用户目录或旧安装位置时会重新注册并启动。因服务恢复或二进制升级而发生的重启会请求一次完整巡检；后台服务身份正确、运行正常且二进制未变化时不会重启，也不会中断正在执行的巡检。`reconcile-service --force-restart` 仅用于明确的人工修复，不属于日常桌面启动流程。

## 9. 客户端自动更新

正式桌面安装包提供“检查更新”。客户端使用本地客户端凭证访问 Agent Manager，并由 Tauri Updater 校验 Ed25519 更新签名；无签名、签名错误或平台不匹配的更新包不会安装。确认更新后，界面会显示下载进度，安装前暂停后台服务，安装完成后自动重启桌面客户端；新版本启动时会校准并恢复后台服务。若下载或安装失败，客户端会恢复原后台服务并显示失败原因。正式通道读取 `latest.json`，测试通道读取 `preview.json`；未发布测试清单时服务端返回 `204 No Content`，客户端不会将其显示为连接错误。

后台客户端复用任务长轮询接收正式通道和测试通道的最新版本信号。桌面端发现所选通道版本变化后，仍通过 Tauri Updater 重新获取并验证签名更新清单，然后弹出更新提示；长轮询信号本身不携带安装包或签名。选择“1 小时后提醒”会只推迟当前版本，到期后再次弹出提示；如果期间发布了更高版本，则立即按新版本提示。原有六小时检查保留为旧服务端或长轮询版本信号不可用时的兼容兜底。

管理台“安装客户端”会先签发仅对所选安装包有效的短时下载票据，再交给浏览器原生下载；实际进度可在浏览器下载列表中查看。票据保存在 HttpOnly Cookie 中，不会把登录凭证或下载票据暴露在 URL；浏览器可以使用原生 Range 分段下载和续传。Tauri 自动更新使用独立的签名更新端点。

生成更新签名密钥：

```bash
cd client/desktop
npx tauri signer generate -w ~/.tauri/agent-manager-client.key
```

在 GitHub 仓库“Settings → Secrets and variables → Actions”中配置以下 Repository secrets：

```text
AGENT_MANAGER_UPDATER_PUBLIC_KEY
AGENT_MANAGER_UPDATER_PRIVATE_KEY
AGENT_MANAGER_UPDATER_PRIVATE_KEY_PASSWORD
```

macOS 构建支持两种模式。仓库未配置变量时默认为 `adhoc`，用于内部测试；Tauri 会对完整 App Bundle 执行 ad-hoc 签名，流水线上仍会执行严格签名校验。浏览器下载的测试包首次运行时需要在 Finder 中右键应用并选择“打开”，或由测试人员自行移除该文件的 quarantine 属性，不能作为正式客户发行版。

正式发行时，在 GitHub 仓库的 Repository variables 中设置：

```text
AGENT_MANAGER_MACOS_SIGNING_MODE=developer-id
```

同时使用 Apple Developer Program 账号申请 `Developer ID Application` 证书，并配置以下 Repository secrets：

```text
APPLE_CERTIFICATE
APPLE_CERTIFICATE_PASSWORD
APPLE_ID
APPLE_PASSWORD
APPLE_TEAM_ID
```

`APPLE_CERTIFICATE` 是包含私钥的 `.p12` 证书经 `openssl base64 -A` 编码后的完整内容；`APPLE_CERTIFICATE_PASSWORD` 是导出 `.p12` 时设置的密码；`APPLE_PASSWORD` 必须使用 Apple ID 的 App 专用密码。Updater 的 Ed25519 密钥与 Apple 代码签名是两套独立机制，正式发行时缺少任意一套都不能形成可交付的 macOS 自动更新版本。

如果 Actions 报错 `SecKeychainItemImport` 或 `failed to import keychain certificate`，优先检查 `APPLE_CERTIFICATE` 是否误填成 `.cer`、文件路径或文件名，以及 `APPLE_CERTIFICATE_PASSWORD` 是否与 `.p12` 的导出密码一致。正式流水线会在构建前验证 Base64、`.p12` 密码、Developer ID Application 证书类型和私钥是否存在。

版本使用 `YY.MM.DD.N`，最后一段是当天发布序号，从 `1` 开始递增。例如 2026 年 3 月 15 日第一次和第二次发布：

```bash
git tag client-v26.03.15.1
git push github client-v26.03.15.1

git tag client-v26.03.15.2
git push github client-v26.03.15.2
```

客户端界面、安装包文件名和发布目录保留四段显示版本。构建脚本会将其转换成 Tauri 使用的三段内部版本，例如 `26.03.15.2` 转换为 `26.3.1502`，用于可靠比较同日多次发布。序号允许 `1`–`99`；不要使用 SemVer 构建元数据 `+N`，因为它不参与版本新旧比较。

推送 `client-v*` 标签后，[GitHub Actions 工作流](../.github/workflows/agent-manager-client.yml) 会使用 GitHub 托管的 macOS ARM、macOS Intel、Windows x64 和 Linux x64 Runner 构建安装包。macOS 测试模式会校验完整 ad-hoc 签名和 DMG 完整性；`developer-id` 模式还会强制检查 Developer ID、Hardened Runtime、DMG 公证票据和 Gatekeeper 评估。任何一项失败都会终止整个发布，不会同步到管理台。最终的 `agent-manager-client-update-feed` Artifact 包含安装包、自动更新包和 `latest.json`；也可以在 Actions 页面手动运行工作流，先验证四个平台的普通构建。

生产发布由标签为 `agent-manager-release` 的 GitHub self-hosted runner 自动同步到内部发布环境：版本文件保存到 `/home/ubuntu/releases/client-YY.MM.DD.N`。流水线比较候选 `latest.json` 与当前内部版本，只有候选版本不低于当前版本时才更新 `/home/ubuntu/skill-manager/scanner/releases` 和 `client-latest`；较旧构建只归档，不会覆盖最新版。企业微信通知地址通过 Repository Secret `WECHAT_WEBHOOK_URL` 配置，不写入仓库。

每次客户端发布任务完成同步或归档后，流水线会按客户端版本号清理内部发布目录，仅保留最新 5 个 `client-YY.MM.DD.N` 版本；`client-latest` 软链接和其他非客户端发布文件不会被清理。

下载并解压最终 Artifact 后，将其中的文件放入服务端：

```text
scanner/releases/
  latest.json
  agent-manager-client-26.03.15.2-darwin-aarch64.dmg
  agent-manager-client-26.03.15.2-darwin-x86_64.dmg
  agent-manager-client-26.03.15.2-windows-x86_64.exe
  agent-manager-client-26.03.15.2-linux-x86_64.AppImage
  agent-manager-client-26.03.15.2-darwin-aarch64.app.tar.gz
  agent-manager-client-26.03.15.2-darwin-x86_64.app.tar.gz
```

管理台“客户端管理 → 安装客户端”按四段版本比较，只展示最新版本的 `.dmg`、`.exe` 和 `.AppImage`，历史版本即使仍保存在发布目录中也不会出现在下载列表。Windows 和 Linux 复用安装包执行更新，macOS 的更新压缩包不会出现在手动下载列表。正式构建左下角显示完整版本，例如 `版本 26.03.15.2`；本地 `npm run dev` 或普通 `npm run build` 显示 `版本 dev`。

正式客户端在成功接入平台后会静默检查一次更新，运行期间每 6 小时再次检查，重新回到前台时也会在超过检查间隔后补查。发现新版本后会发送一次系统通知，并将“检查更新”按钮改为“可更新 版本号”；客户端不会在启动时强制弹出更新窗口，也不会对同一版本重复发送系统通知。用户点击“可更新”后可查看说明并确认安装。

更新检查和文件下载均要求有效的客户端接入凭证。内网 HTTP 可以使用，但更新包仍必须通过内置公钥验签；生产环境优先使用 HTTPS。

## 10. 操作系统代码签名

Updater 签名只证明更新包来自 Agent Manager 发布流程，不能替代操作系统代码签名。正式交付前还需要：

- macOS：Apple Developer ID Application 证书签名，并完成 notarization；正式标签流水线已强制执行签名与公证门禁。
- Windows：使用企业代码签名证书或 Azure Artifact Signing 对安装程序签名。
- Linux：按客户软件源要求对 AppImage 或仓库包执行 GPG 签名。

证书、私钥和密码只能保存在 CI Secret 或专用签名服务中，不写入仓库。没有平台证书时仍可生成内部测试安装包，但不应作为正式客户发行版。
### 可读 Agent 行为审计（P1 补强）

打开“客户端管理 → 设备详情 → 行为审计 → 工具操作”。保持现有绑定设备的 client 凭证、AIDR scopes、平台地址和私有状态目录；在设备上允许上报后运行 `aidr-sync`。用独立临时目录让 Claude/Codex 读取、编辑测试文件并分别执行 `/usr/bin/true`、`/bin/sh -c 'exit 7'`，在页面按会话 ID 筛选并查看详情。不要使用业务文件测试。

列表把一次调用与结果合并；详情显示脱敏命令、工作目录、明确目标、日志结果依据、来源位置与解析版本。Claude 的 `is_error=false` 表示日志未标记错误；明确 exit_code 才显示退出码。包装器仅显示静态识别的字面量调用，不把每个子操作视为已成功。日志时间差不是系统执行耗时。

升级先更新平台，再升级客户端并沿用原状态目录。旧记录没有可读参数时显示信息不足；不自动回读补写。旧冻结正文、摘要、ACK 匹配及读取游标保留。新事件是 schema 2，批次信封仍为 1、ACK 为 2。已支持的工具、字段上限、隐私规则和验收证据见 [P1 可读审计验收](../experiments/aidr-agentlog/READABLE_ACCEPTANCE.md)。

#### 自动发现、诊断与升级

不传 `--codex-file` / `--claude-file` 时，持续自动发现默认日志根；显式文件模式用于限定来源。自动发现每轮有预算，后续轮次推进目录前沿，读取不会局限前 64 个文件。近期活动和历史回溯分配独立预算；旧日期会话追加也会被检查。默认最多保存 4,096 个来源、8,192 个目录，超限报告稳定错误码。

“传输心跳在线”只说明上报通道活跃。分别查看来源发现计数、待检查（含复检）来源、解析能力和来源覆盖；aidr_log_discovery_budget/pending 表示仍有扫描工作，capacity 表示触及总容量，schema_unsupported/record_too_large 表示解析覆盖不足。诊断区可按来源查看具体代码。

升级沿用原私有状态目录，先停止它的原同步进程，再启动新版；不要并发启动两个采集器竞争同一状态。新增目录表不修改已存在的事件、游标和冻结批次。策略感知采集端对新逻辑事件使用投影 3；已有逻辑事件重读复用原投影，旧记录不会自动补填或改变摘要。事件 schema 2、信封 1、严格 ACK 2 保持兼容；平台需先支持新投影和可选发现进度字段。

本机开发验证命令（凭证从已有私有配置读入环境，不回显；需先停止正在使用同一状态目录的采集器）：

```bash
cd /path/to/skill-manager/scanner
go build -o /tmp/aidr-discovery-check-client ./cmd/agent-manager-client
python3 - <<'PYTHON'
import json, os, pathlib
home = pathlib.Path.home()
env = os.environ.copy()
env['AGENT_MANAGER_AIDR_TOKEN'] = json.loads((home / '.agent-manager/config.json').read_text())['token']
args = ['/tmp/aidr-discovery-check-client', 'aidr-sync',
        '--state-dir', str(home / '.agent-manager/aidr-readable-recheck-20260924T130119'),
        '--server', 'http://127.0.0.1:8001',
        '--client-id', 'amc_911abfcfe720cc52f3c4ffe6']
os.execve(args[0], args, env)
PYTHON
```

打开本机 `http://localhost:5173/clients`，选择对应设备 → 行为审计 → 工具操作，按新会话 ID 筛选。临时测试中的 printf 正文应遮蔽；cat 路径是请求意图；日志没有退出码时保持未知。该命令使用当前本机设备配置，不是其他环境的通用设备 ID。


### P1 补强：平台统一 AIDR 审计脱敏

入口：**客户端管理 → 客户端策略 → 审计采集与脱敏**（英文 Client Management → Client policies → Audit collection and redaction）。客户端策略分为“接入与运行”和“审计采集与脱敏”，列表页入口编辑全局默认策略，设备入口编辑该客户端的审计策略；系统总览仅展示目标摘要及跳转入口。设备“策略与审批”和“采集状态”可进入本客户端审计编辑入口；采集状态保留客户端报告的范围、版本与刷新时间。UserPromptSubmit 正文未开启时，事件详情解释采集时策略并提供本客户端策略入口。进入客户端管理需 `clients:view`，审计策略需 `settings:view`；管理员且具有 `settings:update` 权限可修改全局默认策略，单机配置还需 `clients:update` 和设备可见权限；脱敏默认开启；修改人、时间、前后开关与版本进入管理审计，不记录命令内容。设备详情同时展示平台目标策略、客户端报告的版本/开关及最后刷新时间；没有支持报告的旧客户端显示未知/旧版本继续脱敏，不宣称已应用关闭状态。

`aidr-sync` 启动后先读取缓存并尝试认证获取策略，以后每 30 秒重试，下一轮有界采集生效。网络往返及当前采集轮次会增加延迟，这不是硬实时 SLA。离线/获取失败使用已持久化缓存，首次失败默认开启（版本 0）；状态码为 `aidr_policy_applied`、`aidr_policy_cached`、`aidr_policy_response_invalid`。本地 `agent-log-collect` 使用同一状态目录的缓存，无平台连接时不主动刷新。

脱敏关闭时按已授权采集范围保存原文；真实凭证可能进入本地数据库及后台。白名单、UTF-8 字节上限、截断和控制字符处理保持。未配置策略时默认采集用户输入、模型回复、文件正文和命令正文，工具输出默认关闭，各项可独立配置，仅采集来源明确提供的有界片段；未知参数不完整透传。明确的内联正文/脚本参数及 heredoc 仍省略，标记 `body_omitted`，不冒充凭证脱敏。普通 `git commit -m "fix scanner ownership across client credential rotation" && git status --short --branch` 在两种策略下均完整保留。明确 `--password`、秘密环境变量赋值、Authorization/Bearer、Cookie 和受支持令牌格式在开启时遮蔽其值，保持引号与操作符。

升级不删除或重建本地数据。平台新增策略下发记录表；本地 metadata 增加策略缓存及应用序列边界。事件 `behavior.policy` 保存 `version/enabled/receipt`，`redacted` 表示发生替换，`body_omitted` 单独说明正文排除。服务端以绑定设备/stream 的真实下发记录授权，开启策略再次检查敏感模式，未下发版本或错误设备/序列拒绝（`aidr.redaction_policy_invalid`）。客户端持久化应用新策略后，在下次刷新确认上报旧数据序列上界；只有确认后才关闭旧策略范围，响应丢失仍可重试。冻结批次不修改、不重算摘要；旧队列按采集策略补传，即使当前目标已开启，合法 OFF 积压仍可接收。离线采集时间无法由服务端独立证明，策略依赖认证客户端正确报告应用边界，不提供终端可信执行证明。

切换只影响后续新逻辑事件，不恢复、重采或清洗历史。版本 1/2 事件、既有内容哈希、覆盖游标及 ACK 契约保留；重读通过既有身份复用原始投影并保留新位置的来源证据；已淘汰正文的墓碑保持淘汰，避免恢复历史或重复逻辑事件。旧客户端继续固定脱敏，需升级才支持开关。版本 3 不支持向旧平台降级上报，部署顺序为先平台后采集端。

### AIDR 网页状态与策略加载

客户端策略弹窗分别读取治理策略和外部网关选项。读取失败显示持续错误码和“重新加载”；网关失败时仍可查看策略，但暂停编辑和保存，防止把未加载的选项作为空配置写回。平台默认策略仍由普通管理员查看、超级管理员修改，设备策略继续使用设备权限与继承契约。

macOS 系统防护中的终止入口使用服务端返回的 `can_terminate` / `termination_reason`，同时检查当前在线状态及 boot/monitor。服务端创建命令时再次校验健康报告和精确进程身份；进程证据按来源 sequence 判断先后，迟到的 exec 不覆盖 exit。已停止、报告过期、旧 monitor、退出或归属未知时不创建新命令。幂等重试仍返回原请求结果，不重复发送信号。

回执 `state` 保留原证据，`display_state` 将有效期结束但只有 queued/dispatched 的记录显示为“有效期已结束，未确认执行”。executed 仍为信号已发送，verified 仍为退出已验证；`expired`、`expires_at` 在详情中说明命令有效期，不把已完成结果改成失败。

日志解析器支持和来源覆盖独立报告：新版心跳的 `capabilities[].parser_status` / `parser_version` 来自当前客户端解析器对已观察日志版本的支持表；原 `status` 保留来源覆盖汇总语义。页面按最后心跳展示已报告能力；旧客户端缺少新字段时显示未知。来源历史缺口、事件、调用结果、冻结批次和 ACK 不因能力标签变化而重写或清除。

### AIDR Hook 接收器状态（P3）

`aidr-hook-serve` 约每 30 秒通过既有设备凭证上报控制模式、策略版本及健康状态；在设备详情“行为审计 → 采集状态”展开“接收器来源与上传诊断”。此信息与策略发布状态独立，90 秒未更新标为过期，无报告保持未知；不作为插件信任或 OS 执行证明。临时状态容量为每设备 256 个实例，写入时清理 7 天前状态，审计记录不受影响。新路由失败不会清空队列或阻止已有审计上传。

`aidr-plugin-doctor` 新增只读 `--previous-report` 来源漂移比较：比较同一宿主配置的原生列表与产品三份文件摘要。查看 `source_kind`、`files_code`、`files_comparable` 及 `drift`，源读取失败保持未知。接收器另以独立线程约每 60 秒自动检查并上传来源状态，平台来源面板保留可读基线与最近已知变化；该证据与接收器心跳分开。使用示例见 `client/aidr-plugins/README.md`。

## 插件接入与采集页面

桌面侧边栏 **Agent 运行治理 → 插件接入与采集** 首先展示本地接收器、平台传输、待发记录和最近事件上传确认。Claude/Codex 各自的卡片显示实际版本、兼容性、安装、启用、原生信任和检查时间，接入/更新操作位于对应宿主卡片内。未连接设备时使用“前往客户端概览”完成现有认证；平台管理的安装和启停仍在平台执行。路径与来源、采集范围、策略应用、重试及状态报告时间可展开查看；宿主路径使用整行左对齐等宽文本。状态报告成功与事件 ACK 分开，缺失信息保持未知。

平台 **客户端管理 → 设备详情** 使用五个标签：**概览、Agent 与资产、插件接入、行为审计、策略与审批**。概览只显示可跳转摘要、各自报告时间及最近需关注任务；待审批数字仅统计最近读取的最多50条申请，不是全量计数。Agent 与资产集中库存、模型配置、治理、恢复副本及相关任务/记录，其他标签不重复显示。

插件接入展示Claude/Codex的版本、安装/启用/信任、接入方式和安装/更新/自检；来源漂移按需展开，接入任务保留独立回执。接收器、上传及覆盖诊断统一通过“采集状态”跳转查看。配置接入策略链接到策略与审批的唯一客户端策略入口。

行为审计使用“会话活动”“系统事件”“采集状态”三个视图。“会话活动”按产品和会话选择“会话日志”“Hook 事件”或“Skill 行为”；会话日志与 Hook 可继续按轮次查看。数据来自当前设备已启用且已适配的产品；空列表需要检查对应通道与筛选条件。日志调用/结果仍按可靠身份合并，Hook原生事件独立分页，系统证据不由日志替代；日志空列表提供Hook入口。采集状态分别展示Hook接收器与日志读取器，各自保留报告时间、未知值、脱敏/范围、ACK和覆盖原因。来源覆盖明细与来源报告展开时读取，不默认请求全部诊断。

策略与审批提供“工具规则”“审批记录”“系统策略”三个入口；顶部“采集与治理配置”打开“采集与接入 / 模型与请求 / Skill 处置”，“内容与脱敏”打开审计配置。“刷新实际状态”只重新读取客户端报告，不发布策略。English: Policies and approvals separates Tool rules, Approval requests and System policy. Collection & governance opens Collection & setup, Models & requests and Skill actions; Content & redaction opens audit settings. Refresh actual status only reloads client reports.

本次布局人工复核清单：中英文切换工具规则、审批记录、系统策略及两个配置入口；窄屏检查刷新按钮和状态换行；使用只读账号确认权限。Manual UI checklist: check all three policy categories and both configuration entries in both languages, narrow-screen wrapping and read-only permissions.

策略与审批默认进入工具规则；审批记录和系统策略通过分类入口切换，历史与响应回执在对应系统视图查看。进程终止仍在系统事件行，保持完整身份、执行器/monitor新鲜度及服务端独立校验。客户端分类/安装目标等既有配置通过此标签的客户端策略入口编辑；Skill治理方式仍在Agent 与资产中操作。

非活动标签及审计/策略视图卸载组件，清理其计时器；返回重新读取，未提交筛选和展开状态可能重置。概览无定时轮询，插件页只按需刷新；系统事件视图不读取策略/历史/回执，系统策略视图不读取完整事件列表。读取失败持续提示，不作为空配置；已有日志快照保留并明确可能过时。正文、设备可见性和操作权限沿用既有接口，不更改采集、身份、队列或ACK协议。

**English:** Device details provide Overview, Agents and Assets, Plugin access, Behavior audit, and Policies and approvals. Inventory/model/Skill actions and records belong to Agents and Assets; host installation/trust/actions and access receipts belong to Plugin access. Behavior audit separates log operations, native lifecycle/Hooks, system events, and collection status. Collection diagnostics distinguish Hook intake from log reading, including separate report times, unknowns and coverage. Approvals/rules and system policies/responses live under Policies and approvals; exact-process termination remains in system event rows. The overview fetches bounded summaries once; detailed diagnostics load when expanded, and inactive views dispose their timers. Existing access/content permissions and all evidence/ACK contracts remain unchanged.


2026-10-03新版平台标签、历史/未知状态、Hook分页与Codex详情，以及最终900宽桌面长路径已通过中英文实测。日志操作有数据的列表、低权限、网络故障及隐藏面板请求计数仍按已有验收记录检查；本次测试后台日志操作为空，不作替代证明。Bilingual real-page checks passed the new tabs and Hook evidence; populated log operations and permission/network branches remain listed in experiments/aidr-agentlog/ACCEPTANCE.md.

## 普通治理事件队列与补传

此节适用于 `POST /api/v1/clients/{id}/events`。持续观察 `skill_governance_recorded`、`skill_governance_detected` 先进入本地 SQLite 队列。新观察携带产出时的 API 平台绑定，设置并发切换不改变归属；没有产出绑定的新事件保持未知。身份包含原平台、设备、事件类型、Agent、Skill 名称、路径、内容签名、触发条件、策略版本、动作、处置状态、错误及其他原始证据字段；只有时间和累计计数不参与身份。缺少路径、签名、策略、触发条件、动作或有效累计计数的记录保留为独立事件。处置动作和任务结果也保留独立投递身份。

计数沿用治理端持久化计数器的**累计快照**，合并及服务端更新取最大值；重复或乱序快照不增加次数。现有计数域由路径、内容、触发条件、动作和策略确定，处置状态或共享目录的不同 Agent 可能引用同一计数域，不能把这些行或旧、新计数分段的累计值直接相加当作全局唯一观察数。`observation_epoch` 保留该计数分段，平台切换清理原计数关联后使用新的分段；凭证轮换不改变设备或既有分段。

`first_seen_at` 是队列中有证据支持的最早时间，`last_seen_at` 是最近观察时间。`first_seen_source=queued_observation` 表示来自保存的观察时间；旧记录没有有效观察时间时使用原 `created_at`，来源标为 `queue_created_at`。两者均不证明 Skill 历史首次出现时间；已有累计计数也不能倒推出此前观察日期。旧记录没有报告处置状态时保持未知，不补造状态。

每个身份最多保留一条可聚合待发记录和一条已封存投递记录。发送前持久化 `delivery_id` 和不可变载荷，上传期间新增观察写入另一条待发记录。平台在同一事务保存事件与 `(client_id, delivery_id)` 回执；相同身份和载荷重试返回相同记录，不重新累加。同一投递身份携带不同内容返回稳定错误码 `client.events_delivery_conflict`。客户端收到匹配投递身份、有效事件编号及 `durable=true` 后才删除该条封存记录；只有 HTTP 200 不会清理队列。服务端回执保留用于后续重放识别，当前没有自动过期策略，会占用持续增长的磁盘空间。

所有普通事件发送入口共用节奏：每次发送取得回执或失败结束后至少等待 **300 毫秒**再开始下一次（最高约 3.33 次/秒，慢响应会进一步降速），突发 **1**。同服务器发送从请求到回执使用跨进程文件锁串行化，网络等待不持有 SQLite 事务，调度延迟不补发突发流量；一轮最多 **20 条、6 秒**，逐条读取，新增载荷上限为 **256 KiB 加传输元数据**。SQLite 持久化发送节奏、退避及 30 秒发送者租约，同状态目录的多个新版进程不会竞争发送同一条记录。发送超时上限 10 秒，并受单轮期限约束；单轮 6 秒预算在节流等待期间耗尽时，未发送记录保留到下一轮，不记录网络故障或增加退避；网络、超时或 HTTP 错误后按 2、4、8、16、32、60 秒退避，结合 `Retry-After`，上限 60 秒。确认成功后清除退避。等待退避、租约或没有可发送记录不会冒充网络恢复或成功投递。

守护进程独立的普通事件工作器每秒尝试补传；旧记录与最近 30 秒内的新记录按轮次交替 FIFO 处理。负载低于发送能力时，新独立事件通常在下次工作轮次或前台的两条发送预算内发送。持续超过发送能力的独立事实仍可能积压；不会为了容量丢弃它们。持续观察的聚合边界只限制每个身份，不限制历史上不同内容、策略或独立事实的总数。

### 升级与既有数据

先升级服务端，使心跳/策略返回 `ordinary_events_protocol=1`，再由服务所有者停止使用同一状态目录的旧版本进程并切换客户端。新版遇到未声明能力的旧服务端会保留队列，不对普通事件接口试探性投递；旧客户端仍可使用新版服务端的既有请求与响应。升级后的绑定、封存投递及回执语义需要新版发送器；带待发记录的状态目录不能交由旧发送器并发处理或直接降级，因为旧发送器不识别平台绑定和投递身份。

升级在原队列表上增加字段和索引，逐条读取旧记录，在事务内仅合并完整身份一致的持续观察。其余独立事实、原创建时间及平台历史保留；迁移失败回滚。旧队列没有平台字段，旧实现的连接切换会清空事件队列，因此升级按当时的有效私有配置绑定现存积压；配置缺失时绑定保持未知并暂停发送，不在未来切换时猜测归属。人工改写过旧配置、绕过旧连接切换流程的数据库不能由现存字段独立证明其原平台，切换前需先核对来源。

平台切换保留原平台积压，发送时只选择当前平台绑定的记录，仍使用原设备 ID；返回原平台并取得该设备的有效凭证后可继续补传。超过单条边界、无法解析或缺少有效原创建时间的旧载荷保留原文并暂停发送，不影响其他可发送记录。当前没有自动处理这些记录的界面，需由状态目录所有者核对。旧协议中已经保存但响应丢失的独立事件没有稳定投递身份，无法可靠追认或自动删除；新投递身份建立后的重试具有幂等性。

普通事件的上述回执与计数不会改写 AIDR Hook、日志事件、既有冻结批次、摘要、严格 ACK、游标或调用结果关联。

Ordinary governance observations coalesce locally by platform, device, content, policy, action and reported state. Counts are cumulative snapshots, never retry deltas. Delivery identities survive restarts and credential rotation. Upgrade the server before the client; retain unbound or unsupported legacy evidence for owner review. AIDR delivery contracts retain their existing behavior.

## 系统采集对象选择

平台入口为 **客户端详情 → 策略与审批 → 系统采集策略**，客户端入口为 **运行治理 → 系统采集**。系统事件采集当前适用于 macOS Endpoint Security；Windows、Linux 显示不支持此系统通道。

1. 管理员开启“允许系统采集”，选择“客户端选择”或“平台指定”，勾选允许的 Agent 后保存。前者允许用户选择部分产品；后者要求为每个指定产品选择至少一个安装入口。运行治理总开关关闭时，先在客户端策略中开启总开关。
2. 客户端扫描常见安装位置和运行中的程序，支持 Codex、Claude Code、WorkBuddy。列表按 Agent 分组；Codex 的内置 CLI、非原生入口与独立 CLI 在同一分组内标明来源和路径，同一路径去重。路径、安装类型和不可用原因可在详情查看；只发现脚本入口时不能将其当作原生系统采集根。
3. 用户勾选程序后点击“开始采集”。客户端再次核对程序身份，平台校验当前配置版本和五分钟内的发现报告，签发所选路径的策略，再沿用原有 macOS 授权及采集启动流程。发现过程只读取程序及签名，不执行 Agent 程序。
4. 运行中改变勾选项后点击“应用修改”。配置应用和运行状态以执行器报告为准。新增发现的程序不自动加入客户端自选范围；已选入口根据设备记录恢复。程序更新导致身份变化后，需要重新检查并选择。
5. “添加自定义程序”接受完整可执行文件路径并进行同样检查；自定义类型必须由平台明确允许。采集 WorkBuddy 桌面入口时，归属范围包含应用自身及可关联的子进程，事件不一定都来自用户发起的任务。

系统采集页将运行状态、重新发现和停止采集合并到程序列表标题栏，列表按紧凑的 Agent 分组展示。内容区统一纵向滚动，底部选择摘要和开始 / 应用按钮固定显示；程序列表与展开的诊断内容随同一内容区滚动。

The collection page places collection status, rediscovery and stop controls in the list header, with compact Agent groups for bundled, standalone and non-native installations. One content area scrolls vertically; the selection summary and action buttons remain fixed below it.

平台“刷新发现”由运行中的新版桌面客户端约每 30 秒检查请求并上报。断网或客户端退出时页面保留上次报告时间；启动或修改采集范围需要平台连接。接入后通过新会话核对事件到达。停止采集仍使用原有独立采集器的“停止采集”操作。

升级时先更新平台，再更新桌面客户端。原有手填路径策略继续有效；首次采用选择式配置前先在客户端完成发现，再在平台保存允许范围。高级签名规则和历史配置仍通过平台高级区域管理。

English: Administrators set the allowed products and choose client-selected or platform-specified targets. The desktop discovers actual native executables in common installation locations and running processes, verifies code signatures, and lists separate installations. Selection is revalidated locally and authorized by the platform before a signed executable policy is issued. Starting collection still requires the existing macOS authorization flow. Changes during collection await collector application; discovering a program or issuing a policy does not prove observed activity. Custom programs require explicit platform scope. Discovery requests are checked approximately every 30 seconds while the new desktop client runs; offline views retain the last report time. Upgrade the platform before the desktop, and discover existing installations before adopting selection-based scope.

人工验收 Todo（中英文均检查，不新增 UI 单元测试）：

- 多个 Codex 入口集中于同一分组，内置程序、非原生入口与独立 CLI 能区分；详情保留完整路径。
- 内容区仅一条纵向滚动条；展开程序详情、诊断、最近事件后仍随同一内容区滚动，底部操作不遮挡内容。
- 默认窗口与最小窗口下，核对标题栏的停止操作、中英文长状态、程序路径换行及底部开始 / 应用按钮；切换停止、采集中和失败状态后布局不溢出。

- 平台允许范围保存、并发修改冲突、发现请求及报告时间；只读用户不能修改。
- 客户端自动发现、多安装入口、不可用原因、手动添加、首次未选择、记忆选择和程序更新后重新选择。
- 客户端自选与平台指定；发现结果过期、断网、范围收窄、关闭通道及切换设备连接。
- 开始采集的管理员授权、完整磁盘访问权限、真实运行报告、修改后执行器版本及停止采集。
- 窄窗口长英文、键盘勾选、详情展开和轮询期间焦点保持。

## AIDR 状态接口升级与两条采集通道

平台启动的 `upgrade_aidr_schema` 会在原事务内补齐旧 `client_runtime_governance.supports_tasks`。默认值为 false；只有保存的报告通过当前严格契约校验且明确声明任务协议 1 或 2，才恢复支持标记。未报告、无效报告及协议 0 不作为支持依据。原报告内容、报告时间和任务不改写；失败回滚，可在下次启动重试。已有列不重复回填，正常心跳继续更新真实能力。ORM `create_all` 本身不会升级已有表。

设备详情的“插件接入”和“行为审计 → 采集状态 → Hook 接收与上传”读取运行治理报告。它们与“工具操作”的日志读取心跳独立。日志循环与插件 Hook 接收器均由 Go 主后台服务管理，桌面读取状态并提交操作请求；尚未升级的基础后台仍需按其版本诊断，不能把新增平台配置当成已自动应用。设备“允许上报”是服务端接收许可，不是通道运行目标。Hook 有 Pre/Post 而工具操作为空时，先检查两个通道的报告时间和读取器进程，不要自动认定 Hook 丢失。

恢复日志读取时，先检查既有 Go 后台服务及日志策略；新版后台自动协调日志读取，不需要额外手动启动 `aidr-sync`。仅在排查旧版或独立命令行部署时沿用原平台、设备和私有状态目录，并避免两个读取器占用同一目录；凭证不得复制到命令参数或页面。旧游标沿用原范围，待发批次和 ACK 保持原契约。版本标记 `aidr_log_version_unverified` 表示尚未认证该日志版本，即使部分调用能正确解析，也不表示完整支持。

`[BODY OMITTED]` 表示采集策略未选择正文，与秘密脱敏不同。Hook 没有明确结果或退出码时继续显示未知；不能将另一条日志的退出码按时间接近填入 Hook。

**English:** Startup upgrades the runtime observation table transactionally. Task support is recovered only from a valid stored report declaring protocol 1 or 2; report contents/timestamps and tasks remain intact, and failed upgrades roll back. Plugin access and Hook intake show runtime reports, while readable operations use the separate log channel. The desktop manages Hook intake, while the updated Go background service coordinates log reading automatically. Explicit aidr-sync is relevant to older or standalone CLI deployments and must retain the original private state and device/platform binding without duplicating a reader. Reporting permission does not start that reader. Preserve version warnings, body omission and unknown Hook results; a partially parsed unverified version is not full compatibility.


### 行为审计的通道、Hook 含义与自动刷新

设备详情的三个证据列表来自独立通道：“工具操作（Agent 日志）”来自日志读取与上传，新版由既有Go基础后台按日志目标管理；“宿主事件（Hook）”来自主后台服务按策略管理的插件接收器；“系统事件”来自独立macOS原生系统通道。接收器运行只说明Hook组件状态；应分别核对基础后台版本及日志目标应用报告，也不证明系统通道已接入。日志健康按有效运行策略判断：继承默认策略或设备覆盖中未启用 Agent Logs 时，显示“按策略未启用”，无日志心跳属于预期状态；不因 Hook 在线或日志历史列表而推断正在采集。策略未知显示未知，新目标与通道报告版本不同显示等待应用，已启用目标但没有通道报告显示未报告。目标关闭而新鲜旧版本仍报告运行时显示“等待客户端停止”；新鲜报告版本匹配关闭目标但仍声明启用或运行时，明确警告“关闭目标未生效”。只有匹配当前目标的通道观测才用于当前运行判断；超过 30 秒的通道报告标记过期，通道报告运行中但 90 秒内没有日志传输心跳则提示传输失联。设备上报许可关闭或该设备有效审计生命周期暂停分别显示暂停原因。目标状态、客户端原始通道报告、报告版本和最后传输心跳分别展示；历史来源覆盖缺口仍保留为历史事实。桌面依据本机已收到的目标判断，不宣称尚未收到的平台新目标已经应用。没有系统报告时，系统事件明确提示未报告，默认查询全部事件类型。

English: Log health uses the effective channel policy. A disabled Agent Logs target is expected to have no log heartbeat. Unknown policy, a target awaiting application, a missing channel report, an expired channel report, and an expected channel with no recent transport heartbeat are distinct states. Target and reported policy versions remain separate; an old report cannot prove the new target is applied. Check the log channel report for current collection status. Desktop status uses its received policy, not an unseen platform update.

接入前先在设备“插件接入”核对“客户端能力与升级”：能力来自客户端上报的运行治理协议及基础后台任务支持报告，版本字符串仅作标签。协议缺失或报告过期显示未知；旧协议、独立通道能力与任务能力分别展示。客户端更新使用已有桌面入口：运行治理 → 客户端更新（定位设置中的“立即检查”按钮）→ 按批准更新包安装并重启；不会点击导航按钮就自动安装或重启。安装后等待基础后台新报告，在宿主原生配置中完成启用/信任，重启宿主并打开新会话，再逐项核对接收器、事件和严格 ACK。更新入口不可用时可使用管理平台客户端页已有客户端下载入口。不存在按某个版本数字自动认定能力或把配置成功视为接入完成的判定。

English: Inspect reported protocol and task support in Plugin access → Client capabilities and upgrade. Version labels do not establish support. The desktop Runtime governance → Client update button locates the existing Settings → Check now control; it does not install or restart automatically. After an approved update and restart, wait for a fresh background report, complete native host enablement/trust, restart the host and open a new session, then verify receiver, event arrival and strict ACK separately.


宿主事件（Hook）列表保留原生名称，并显示记录的活动含义及白名单内的命令请求、明确目标。SessionStart 是宿主报告的会话开始；UserPromptSubmit 是宿主报告用户输入提交，不是执行命令。会话下方仅在记录存在工具调用 ID 时显示该 ID。具体输入只有在授权采集且用户有查看权限时可见；未选择正文不会事后恢复。PreToolUse 命令仅表示请求意图，PostToolUse 的结果和退出码继续依据实际记录，没有依据时保持未知。

工具操作的 Agent、结果、时间选择改变后自动查询，会话和工具文本输入停顿 250 ms 后查询；改变筛选返回第一页。请求进行中再次改变筛选会合并为下一次最新查询，旧查询结果不覆盖新条件。清除筛选自动恢复未筛选列表，无需点击筛选按钮。

“采集状态”使用近期实际报告禁用已经启用/停止的同状态操作，并显示最近接收器任务及完成/错误状态。提交接入任务后，页面每 5 秒读取任务和报告，最多自动查询 2 分钟；页面隐藏时不发起自动请求，切页销毁计时器。启停任务完成后还需确认客户端报告的 managed_task 已应用该任务，不以任务创建成功代替状态已更新。等待超时显示持续说明，用户可刷新继续核对；不会自动重发任务。没有待完成任务或过渡状态时不增加周期查询。

**English:** Tool operations, native Hooks and OS events are separate evidence channels. An active desktop Hook receiver does not start `aidr-sync` or establish OS collection. The page shows the last log heartbeat and missing system reports explicitly. Lifecycle rows explain the native event and distinguish a missing tool call ID from an unknown result. Allowed commands and targets describe requested intent; input/body content remains subject to collection scope and viewing permissions. Select/time filters apply immediately, text after 250 ms, and changed filters reset pagination without allowing an older response to overwrite newer criteria. Receiver controls disable already-applied states and show the latest task. Pending tasks or transitional reports refresh every 5 seconds for at most 2 minutes; hidden pages skip requests, unmount stops the timer, and timeout offers manual refresh without resubmitting. Completed receiver tasks require an applied client report before controls unlock.

### Hook 最新记录、历史快照与调用证据

设备详情“行为审计 → 宿主事件（Hook）”默认按平台记录 ID 降序显示最新 100 条；这是平台接收顺序，原生发生时间仍以证据字段为准。“更早批次”沿固定快照和严格小于游标读取，“较新批次”返回已访问的上一个批次；期间到达的新事件不会插入当前历史快照。点击“最新记录”重新建立快照并读取新记录。历史保留策略仍可能淘汰快照内的证据。

Agent、原生 Hook、会话 ID、工具原名、调用 ID 和事件 ID 支持精确过滤；身份元数据关键词只搜索这些身份字段，不搜索 prompt、正文、命令输出或证据全文。默认展示 Agent、Hook 事件和关键词；Hook 事件支持建议列表和自定义原生名称，工具原名、会话 ID、调用 ID、事件 ID 位于“更多筛选”，收起时仍显示已启用的精确条件数。选择 Agent 或建议事件后立即查询，文本输入停顿 250 ms 后自动查询，Enter 可立即查询。筛选变化和清除筛选均回到新快照首批；清除会一并移除收起的条件。查询期间显示加载状态；从条件变化开始，旧响应不能替换当前列表，客户端或视图变化也会取消待查询计时。分页入口集中在列表顶部，查询与滚动说明位于“证据范围与判读说明”。读取失败提供重试，不把错误当作空列表。

列表区分工具调用前请求、调用后结果及生命周期/权限事件。详情突出事件、工具、来源、时间及请求/结果，正文按权限点击读取；工具调用事件通过折叠区提供“相关 Hook 记录”：关联要求同一设备、来源流、系统用户、Agent、会话、原生调用和工具；回合及子代理命名空间必须一致，Codex 调用需要回合身份。Claude 的可选回合/子代理字段双方都为空时不阻止关联。只有恰好一条调用前请求和一条调用后结果才显示唯一关联；关联说明放在折叠区；生命周期事件不查询工具调用关联。关联不会按时间接近补齐，不证明 OS 进程关系或工具成功；未知结果、记录中的退出码及结果依据分别保留。

**English:** Behavior audit → Lifecycle and Hooks shows the latest 100 records by descending platform record ID, reflecting platform receipt order rather than native occurrence time. Older batches use a fixed snapshot ceiling and an exclusive ID cursor; Newer returns to a previously visited batch. Incoming records do not enter that historical snapshot. Latest creates a new snapshot; retention can still expire historical evidence. Exact filters cover Agent, native Hook, session, tool, call and event IDs. Keywords search identity metadata only, never prompt/body/output content. Apply or Clear starts a new snapshot, and stale responses cannot replace changed filters, clients or views. Failed reads offer retry.

Call evidence remains separate from result evidence. Details prioritize event, tool, source, time, request and outcome; source content is loaded on demand with permission checks. Related tool Hooks appear in a collapsed section. Related Hooks require the same device, source stream, OS user, Agent, session, native call and tool, with matching turn/subagent namespaces; Codex needs turn identity, while absent optional Claude fields may match when absent on both sides. Exactly one request and one result establish a unique native-identity link. Association diagnostics stay in the collapsed section; lifecycle events do not query tool associations. No time-based pairing, OS process attribution or success inference is added; unknown result markers, explicit exit codes and recorded result bases remain distinct.

审批和 Hook 列表使用限高的表格滚动区，固定日期与详情列；分页入口放在列表顶部，较旧审批批次出现新请求时显示最新入口。会话与调用 ID 在列表中缩略，鼠标悬停或键盘聚焦可查看完整值，详情保留原文。Hook 活动摘要仅展示首项命令和活动数量，全部活动与目标仍在详情。Hook 结果使用“宿主报告”文案，日志工具操作保持日志来源文案；没有记录退出码时不拼接第二个“未知”，结果依据及记录中的不确定性收在“记录信息”，空值省略。

**English:** Approval and Hook tables have a bounded internal scroll area with fixed date and Details columns. Navigation appears above the list, and historical approval batches expose a Latest entry when new requests arrive. Session/call IDs are shortened only in list presentation; hover or keyboard focus shows the full value, also retained in Details. Activity summaries show the first command and count, while Details retains all activities and targets. Hook outcome labels identify the host source; log operation labels retain their log source. Absent exit codes do not append another unknown marker; recorded result bases and uncertainty appear under Record information, with empty fields omitted.


### 审计详情的信息层次

工具操作和 Hook 详情采用“事件摘要 → 请求/输入/输出 → 记录信息”结构。命令、工作目录和目标保留原文；多项工具请求逐项展示。工具操作中的脚本包装调用明确标注结果属于整次脚本调用。详情不再展示整块 JSON，原始采集记录仍由后端保存。正文读取保留权限检查、按次访问审计、重试以及关闭/切换记录后清除的行为。

| Hook | 首要内容 |
| --- | --- |
| SessionStart / SessionEnd | 会话开始/结束、会话 ID、来源与接收时间 |
| UserPromptSubmit | 用户输入；未采集时说明原因并提供策略入口 |
| PreToolUse | 工具、命令、工作目录、目标；这些字段表示调用请求 |
| PostToolUse / PostToolUseFailure | 宿主报告的结果、明确退出码、可读取输出 |
| PermissionRequest / PermissionDenied | 权限请求/拒绝及对应工具请求 |
| SubagentStart / SubagentStop | 子代理 ID、会话及阶段 |
| PreCompact / PostCompact | 上下文压缩前/后、会话 |
| Stop / Interrupt | 本轮停止/中断、会话 |
| Notification / TaskCompleted / TeammateIdle | 宿主报告的通知/任务完成/队友空闲、会话 |

回合 ID、调用 ID、记录 ID、采集策略版本和结果来源收在“记录信息”。仅在有明确退出码时展示退出码；已在结果标签中显示的退出码 0 不重复展示。PostToolUse 没有结构化结果时显示“已返回，未报告执行状态”。Notification、TaskCompleted 和 TeammateIdle 当前采集契约保留生命周期及身份字段，未保存的通知正文、任务摘要不能从这些记录恢复。

**English:** Audit details show the event summary, request/input/output, then collapsible record information. Commands, paths and body fragments remain in their original language. Multi-action wrappers identify that the outcome applies to the whole script. Full JSON is removed from these detail views; backend records remain retained. Content is fetched on demand with existing permissions and access auditing, and is cleared when hidden or the record changes. Lifecycle, permission, subagent and compaction events show applicable fields only. Result-less PostToolUse records read “Returned; outcome not reported”. Notification/task/idle projections currently retain lifecycle identity, not notification text or task summaries.

### Hook 接入逐项验收

设备详情 → 插件接入提供简短步骤与当前待确认项：目标策略、协议能力、安装、原生启用/信任、宿主加载、接收器、事件到达、同流平台持久化批次、客户端 ACK。每项证据时间和原始元数据折叠查看。目标关闭时显示按策略无需接入；配置入口不会自动启用采集。客户端报告以蓝色展示，平台已保存事实以绿色展示；安装任务成功不替代事件证据。原生宿主加载暂无独立回执，保持未知；事件已到达时明确标注已观察 Hook，下一步优先处理其余可行动的缺失项，不永久要求重开会话。

事件证据限于当前策略更新时间之后且最近 15 分钟的未过期事件，查询最多 100 条；宿主配置报告限 180 秒且整体报告未过期，接收器报告需匹配当前目标版本。持久化批次是同一设备与流的独立平台记录，现有模型没有事件与批次精确关联。客户端 ACK 仅在最近 90 秒的报告与所示事件同流、同接收器实例，且 ACK 时间不早于平台事件到达、不过度超前时标已报告；平台保存批次不证明客户端收到 ACK。旧记录、缺少接收器实例或时钟差异造成证据不足时保持未知。

**English:** Device details → Plugin access presents separate onboarding steps and the next actionable missing evidence. Expand each step for its source and timestamp. A disabled target needs no onboarding; opening configuration does not enable collection. Client reports and platform-stored facts remain distinct. No independent native host-loading receipt exists; that step stays unknown even when Hook arrival is observed, without trapping the next action on restarting sessions. Events must be unexpired, received after the policy update and within 15 minutes (up to 100 records). A same-stream durable batch is independent evidence, without an exact event-to-batch association. Client ACK requires a fresh report from the same stream and receiver instance, with a suitable timestamp; platform persistence does not prove client receipt. Missing identity or clock evidence remains unknown.

系统事件已补充原文命令参数（8 KiB / 256 项）、工作目录、退出码/信号与文件创建、修改、重命名和删除通知；平台详情显示同一进程的活动与归属链。自检通过单独标记筛选，历史缺失字段不补造。已有 Agent 在下一次 ES 事件验证身份；未配置程序或未建立父子关系的已有子进程不等同于已覆盖。双语操作说明与本次人工验收见 [操作内容与覆盖范围](../client/macos-enforcer/README.md#操作内容与覆盖范围)。

**English:** System events include verbatim bounded arguments, cwd, exit code/signal and file-change notifications. Details correlate the exact process identity. Client checks can be filtered, historical fields are not reconstructed, and existing Agent roots are verified on their next ES event. Online lease renewal no longer conflicts with an unchanged configuration draft; collection continues until stopped or exited.

### 接收器重试与任务记录

Hook 与日志批次上传遇到网络失败、HTTP 404（接口暂不可用）、408、429 或 5xx 时，在现有采集工作循环内退避重试，间隔从 1 秒递增、上限 60 秒，并受循环调度间隔约束。冻结批次、采集游标及本地接收器保持；网络重试不消耗接收器进程的重启额度。只有收到匹配设备、流、批次摘要、记录数和 durable 标记的 ACK 后才确认出队。401/403 鉴权拒绝、409 冲突、413 大小限制和 422 契约错误仍需排查，不能作为临时路由故障处理。

主后台的 Hook/日志 HTTP 诊断写入 `~/.agent-manager/logs/diagnostics/`：模块为 `aidr_http:<method>:<resource>`，记录 HTTP 状态、客户端错误码、符合格式的服务端 `aidr.*` 错误码及可重试标志。相同错误合并计数，每分钟汇总，恢复记录 `sync_recovered`；请求、响应正文和凭据不写入该诊断。404 本身只能证明接口当时不可用，确定热重载、路由或代理原因还需对照后端访问与启动日志。后端发布应在路由及就绪检查通过后接入流量，开发热重载期间应保留访问日志。

旧版已耗尽重试的暂停状态需在升级后分别执行“重试接收器”和“重试日志采集”（CLI：`agent-manager-client aidr-desktop --action retry` / `--action retry-logs`）。核对两条通道恢复、原待发记录的 ACK 和平台持久化记录；保留原队列、策略与凭据，不靠清空状态解除暂停。

**English:** Hook and log uploads back off inside their collection loops for network failures, HTTP 404/408/429 and 5xx, from one second up to 60 seconds subject to loop scheduling. These retries preserve intake and frozen bytes without consuming receiver restart attempts. Only an exact durable ACK removes records. Authentication, conflict, size and contract failures retain their existing handling. Managed HTTP diagnostics record only method/resource, status, stable codes and retryability, aggregate repeated failures and report recovery. Correlate 404s with backend access/startup logs; route traffic only after readiness checks. Previously suspended installations require separate receiver and log retry actions after upgrade, followed by queue/ACK and server persistence verification.

Hook 接收器的固定重试次数针对一轮连续故障：只有连续收到有效健康报告满 60 秒，才恢复下一轮的重试额度；单次启动、短暂运行或恢复调度不重置额度。失败立即循环的进程仍会按策略暂停，需修正原因后点击“重试接收器”。新版本保留原有暂停记录，不通过升级删除重试状态或队列。诊断区保留最近失败及时间；系统强制终止、终止信号和正常结束分别显示，不能仅凭 SIGKILL 判断是谁终止了进程。

同一用户的多个桌面窗口均观察主后台服务中的同一个 Hook 接收器；窗口之间不争夺接收器管理权。桌面退出不改变后台 PID、队列或接收器实例。旧版本迁移时，主服务等待旧桌面释放监督锁，随后继续使用原队列；外部身份或绑定不符的 socket 保持冲突，不自动接管。

Hook IPC 将响应超时（`aidr_hook_response_timeout`）、连接中断（`aidr_hook_transport_failed`）、超长帧和无效 JSON/版本分开记录。接收器处理预算为 1 秒，等待存储互斥锁也计入预算；SQLite 单次锁等待为 250 毫秒，避免超过 2 秒的连接时限。存储竞争或并发饱和返回 `aidr_hook_receiver_busy`，保留当前审计/拦截模式；释放占用后可继续服务，无需重启。拦截请求失败不作为放行，也不自动重放结果不明的已发送请求。

桥接失败写入本机诊断日志的 `hook_ipc` 模块，包括稳定错误码、`stage`、`cause`、`duration_ms` 和 `event_id`；不记录原始 Hook 参数、命令正文或响应内容。旧日志只有 `aidr_hook_protocol_invalid` 时不能据此区分超时、断连和格式错误。

English: Hook IPC distinguishes response timeouts, transport interruption, oversized frames and invalid JSON/protocol versions. The one-second work budget includes storage mutex waits; SQLite waits at most 250 ms per lock attempt within the two-second connection deadline. Contention returns receiver-busy while preserving the active control mode, and service resumes after contention clears without restarting. Failed interception is not authorization; ambiguous sent requests are not automatically replayed. Local hook_ipc diagnostics retain only stable codes, stage, cause, elapsed time and event ID, excluding raw payloads and responses. Historical protocol-invalid codes alone cannot identify the underlying failure.

**Multiple windows:** Every desktop observes the same receiver in the main background service. Closing or quitting a window does not change the receiver PID, instance or queue. During migration, the daemon waits for the old desktop supervisor to release its lock, then resumes the existing queue. Unknown or mismatched external endpoints remain conflicts.

平台客户端概览展示最近 5 条任务（包括成功任务），列出具体动作、目标产品、创建时间、策略版本和结果。展开“执行信息”查看通道目标、结束时间和错误码；这些是该次任务的信息，当前采集状态仍以各通道的健康报告为准。“已被新任务替代”表示旧任务已失效；历史失败不因后续成功而被改写。

**English:** Fixed Hook receiver retries apply to consecutive failures. A full minute of valid health reports restores the retry budget; a spawn or brief recovery does not. Existing paused state and queues survive upgrades. Diagnostics distinguish force-kill, termination and normal exit without guessing who caused them. The platform overview shows the latest five tasks, including successful tasks, with concrete actions, products, timestamps, policy versions and expandable execution details. Task history is separate from current channel health.

人工验收：固定重试策略下验证连续失败耗尽额度、手动重试、稳定运行一分钟后恢复额度；检查系统信号退出原因。平台中英文核对成功/失败任务、长产品名称、窄屏换行和执行信息展开，不把历史任务失败当作当前采集失败。

多窗口 UI 验收：同时打开两个新版桌面，确认两者显示同一后台 PID、实例和 ACK；退出任一或全部桌面后接收器继续工作。中英文检查状态及重试文案。

临时后端故障 UI 验收 Todo（中文/英文）：在隔离测试后端模拟 404、503，核对桌面“运行治理 → 接入与采集”接收器仍运行、上传显示退避而非重启耗尽；恢复接口后待发数量下降、ACK 更新。平台客户端采集状态应恢复新鲜上报；历史故障仍保留原时间。页面显示就绪不能替代待发记录的服务端落库和 ACK 核验。

2026-10-14 本机 macOS 验证：上传、受管客户端和 CLI 三个 Go 包回归通过；HTTP 分类及 Hook/日志连续三次 404 后恢复的测试通过 race 检查，原冻结字节不变、匹配 ACK 后出队。更新开发 sidecar 并恢复既有队列后，原 3 条 Hook 和 5 条日志待发记录逐条匹配平台记录与客户端 ACK，原冻结批次摘要一致。此验证不包含日常后端故障注入，也未确认此前短暂 404 的服务端成因。

**Local verification (2026-10-14):** Three Go packages passed; HTTP classification and Hook/log recovery after three consecutive 404s passed race checks. The updated macOS development sidecar resumed the existing queues, with all three pending Hook records and five log records matched to server persistence and local ACK evidence. Frozen digests were preserved. This did not inject a fault into the daily backend or establish the server-side cause of the earlier 404s.

### 多产品日志与 Hook 接入

在平台客户端策略的“Agent 日志来源”选择需要采集的产品，在 Hook 宿主选择相应入口。保存后到“采集状态”核对产品来源、覆盖错误和 ACK；不要仅凭设备在线判断有日志。新增产品需要协议 5 客户端。原策略未指定产品时维持 Claude / Codex，不自动扩大历史采集范围。

桌面“运行治理 → 接入与采集”提供 WorkBuddy、Qoder 共享设置、QoderWork 和 Cursor 的接入/移除入口；平台自动安装策略复用同一适配器。用户既有 Hook 与其他配置被保留。配置完成后按宿主要求开启新会话或重启，检查真实事件，并核对宿主授权。能力目录显示产品入口、来源、OS 和样本版本，尚未接入的产品不出现在采集目标选项中。具体矩阵与限制见 `docs/external-agent-integration.md`。

“允许用户自行接入 / Allow user enrollment”默认开启，已有策略缺少此字段时也采用该默认值。普通接入模式下，点击产品的“启用 Hook 采集 / Enable Hook collection”会复用现有安装器，保存与当前平台和设备绑定的本机选择，并随设备认证心跳自动同步。平台将管理员指定产品与允许的本机选择合并，再通过现有策略任务启用接收器及产品范围。无需再去平台勾选相同产品。安装失败不会提交接入选择；重复点击不会增加重复配置或产品；接收器已暂停时，本次明确的启用操作会请求重新尝试，正常运行的共享接收器不重启。

断网时选择保存在本机，显示“配置已安装，等待平台同步”，恢复后自动重传；在平台返回有效目标之前不扩大接收范围。关闭自行接入后仅管理员指定产品生效；运行治理/Hook 通道关闭、企业受管模式均优先于本机选择。本机选择独立存储，不生成单机策略覆盖，因此仍继承后续全局策略。移除设置型 Hook 会同步撤回本机选择；管理员指定的产品仍由管理员策略管理。日志来源、系统采集、脱敏和拦截模式不会因接入 Hook 改变。升级时先更新平台，再更新客户端；旧客户端继续收到其支持的任务字段。新客户端尚未收到接入策略时提示等待策略同步，不伪报成功。

启用按钮与产品接入状态共用判断：近期自检确认配置已安装且宿主未报告禁用、该产品已在有效接收范围时，显示不可重复点击的“已启用 Hook 采集”；允许自行接入的请求已保存而平台尚未启用时，显示不可重复点击的“等待平台同步”。插件更新、宿主授权和接收器重试仍使用各自入口；已启用不表示已收到事件。手工验收需分别检查中文/英文中的已启用、待同步、未安装、宿主禁用和策略受限状态，以及连续点击不重复提交；本次不新增 UI 单元测试。

The enable button uses the same product state as the status card. A recent inspection confirming installation, no reported host disablement and inclusion in the effective receiver scope displays a disabled **Hook collection enabled** button. A saved, permitted enrollment awaiting platform activation displays **Awaiting platform sync** and cannot be resubmitted. Updates, host authorization and receiver retries retain their own controls. Verify event delivery after enabling the product. Manually check both languages, pending sync, absent or disabled installations, restricted policies and repeated clicks.

宿主信任/授权仍在宿主完成，可能需要新建会话或重新加载。客户端显示已安装、待同步、策略受限和配置接收状态；事件实际送达以平台“插件接入”的最近事件为准。未发现宿主或尚未完成自检时，启用按钮不可用。运行治理使用独立滚动布局，冷启动首次进入即可上下滚动。

User enrollment is enabled by default, including existing policies without the field. In ordinary mode, **Enable Hook collection** installs the selected integration and persists a device/server-bound request. Authenticated heartbeats synchronize it; the platform merges allowed user choices with administrator-selected hosts and sends the effective target through existing policy tasks. Offline requests survive restarts. Disabled channels, administrator-only scopes and managed access take precedence. This does not change log sources, system collection, redaction or protection modes. Installation and receiver health do not prove event delivery: complete host trust review if needed and verify a new event on the platform. Settings-adapter removal withdraws the local request; administrator-selected products remain administrator-controlled.

**Manual UI acceptance:** Cold-start the desktop and open Runtime Governance directly; scroll to the final product card without visiting another page. With a manual/ordinary policy, verify available products can be installed, updated and removed while automatic/managed policy actions stay platform-controlled. Confirm installation preserves the receiver switch and selected hosts. Check Chinese and English, then switch through Overview and Agent Management back to Governance and verify scrolling again.

**English:** Select log products and Hook entry points in the global or per-device client policy. Check per-source coverage and ACK after saving. Protocol 5 is required for new targets; absent product selection keeps the original Claude/Codex scope. Desktop settings adapters preserve existing user hooks. Start a new host session (or restart where required), then verify actual delivery. Installed configuration is not host authorization or successful collection.

A manual/ordinary policy allows local plugin installation, updates and removal. Receiver state and selected collection hosts remain platform-controlled. Installing an unselected host does not enable collection. Missing hosts or pending inspection keep installation unavailable; consult the product status first.


### Agent Manager 插件名称与 Skill 使用审计

平台的“客户端策略 → 内容与脱敏 → Skill 使用审计”配置后台核对方式、摘要复用时间、平台状态刷新间隔、资源上限与分类告警。全局默认可由单机策略覆盖；保存预览与客户端最近报告分开展示。新版客户端通过策略协商接收这些参数，离线保留有效缓存；旧客户端需要升级后才能应用内容读取参数。

默认首次使用、内容变化或 300 秒缓存到期时计算；每次复用仍检查元数据。摘要缓存限 128 个目录与 8192 份文件元数据，进程重启后重新计算；策略本身由原 SQLite 策略缓存持久化。默认并发 1、256 文件、单文件 2 MiB、总量 8 MiB。超限或采集取消时记录待确认原因，不影响工具返回。实际采集器可能顺序执行，并发参数只设上限。只有新产生的观察采用新策略，既有冻结队列保持原策略与 ACK。

**English:** Skill audit settings support global inheritance and device overrides. Negotiated policies persist offline; digest caches are process-local and bounded to 128 directories and 8192 file metadata entries. Defaults are a 300-second reuse window, one concurrent check, 256 files, 2 MiB per file and 8 MiB total. Limits or cancelled observations remain pending without affecting tool results. Client reports and saved targets are separate; frozen queues retain their original policy and ACK identity.

Codex 会话日志遇到超出单行预算的已知压缩、元数据、消息或工具记录时，跳过正文并保留会话上下文；缺失范围仍报告为采集缺口。旧版因此丢失会话身份的游标会分批重读原文件到已提交位置，仅恢复上下文，不重传历史、不删除队列或修改原始日志。恢复完成后的新输入、回复和工具事件继续使用原生会话标识。平台升级时检查历史缺失会话的调用：仅当同一设备、用户、日志来源及文件实例、轮次和原生调用 ID 对应唯一调用与返回，且返回已有会话身份时，补齐展示关联；原始事件保持不变。存在歧义或证据不足时保留独立记录，缺少工具名称的返回显示“工具返回记录”。

Codex App 输入中的显式 `## My request:` 包装由日志和 Hook 共用的采集逻辑拆成“用户问题”和“附带上下文”。用户问题优先使用单段额度，上下文再使用剩余单事件额度；两部分分别经过脱敏、分别标注原始字节数和截断状态，总量仍遵守现有策略。平台按部分显示保存/原始字节数及采集上限。旧记录继续使用“原始输入（含附带上下文）”说明；已经截掉的正文不会因刷新或升级自动恢复。先升级平台，再升级客户端采集组件，新规则用于之后采集的记录。

**English:** Log and Hook capture split explicitly wrapped Codex App input into the user request and attached context. The request receives its fragment budget first; context uses the remaining event budget. Each part retains its own redaction, original byte count and truncation status. Existing policy limits still apply. Historical truncation refers to the full input including context; discarded text is not restored. Upgrade the platform before collectors. A one-time platform upgrade repairs unique historical call/result projections using device, user, source file instance, turn and native call identity. Immutable events remain unchanged; ambiguous returns stay separate and are labeled “Tool return record”.

日志队列接近容量上限时，上传优先于继续采集；冻结上传批次空间不足时减小批量，已冻结批次保持原文、摘要和身份直到严格 ACK。恢复不清空队列或游标，也不提高配置的数据库容量。English: Upload runs before intake. Near the storage limit, a new batch is reduced to fit available space; an already frozen batch stays unchanged until strict ACK. Recovery preserves queued records, cursors and the configured database limit.

采集进度快照的本地历史采用无损 gzip 压缩（`coverage_history.payload_encoding` 为 `gzip` 时，`payload` 是压缩后的 BLOB；`json` 为原始 JSON）。首次打开旧库时分批压缩已 ACK 的快照并回收空闲页，保留记录 ID、时间、ACK、完整采集游标和事件历史。新快照不上传仅用于解析续采的调用映射缓存；原生调用、会话和轮次标识仍随事件上传。上传队列及已冻结批次仍使用原始 JSON，严格 ACK 规则不变。库达到上限仍会明确报告容量故障，待发为 0 不代表采集可继续。

**English:** Coverage snapshots use lossless gzip in the local archive (`payload_encoding=gzip` stores a compressed BLOB; `json` stores plain JSON). Opening a legacy store compresses acknowledged snapshots in batches and reclaims free pages, preserving record IDs, timestamps, ACKs, complete parser checkpoints and event history. New uploaded snapshots omit the local call-binding cache; events still carry native call, session and turn IDs. Queued and frozen uploads remain unchanged JSON with strict ACKs. Capacity exhaustion remains an explicit collection error even when the outbox is empty.

验收：旧库接近容量上限时升级，核对历史条数与游标保留、空间释放、新问答继续采集及平台 ACK；断网冻结批次后重启，核对相同批次摘要与恢复上传。UI 人工检查中英文轮次导航的上下翻动、当前位置及窄屏选择器。Manual checks: upgrade a nearly full store, verify retained history/checkpoints, reclaimed space, new messages and platform ACKs; restart offline with a frozen batch and confirm unchanged digest and resumed delivery. Check turn arrows, position and the narrow-screen selector in both languages.

2026-10-08 本机恢复验收：256 MiB 满库导致 Codex 停留在 13:59 的游标，待发为 0；旧进度快照正文合计 118,246,262 字节。更新组件后，11,354 条旧快照逐条解压摘要一致，库占用降到约 192 MiB。14:30 核对当前真实 Codex 会话本轮的 1 条输入、4 条过程回复、21 条调用和 21 条返回均已在平台入库，并匹配本地 ACK；待发恢复为 0。中文页面已显示本轮日志，英文 700px 窄屏已检查。满库旧格式迁移、冻结批次、错误 ACK、续采及重复打开由 Go 回归测试覆盖；本次未人为断开真实平台网络。

**English:** On 2026-10-08, a full 256 MiB store stopped the Codex cursor at 13:59 despite an empty outbox. After upgrading, all 11,354 archived snapshot hashes matched after decompression and the database shrank to about 192 MiB. At 14:30, the live Codex turn had 1 user input, 4 progress replies, 21 tool calls and 21 results confirmed in both platform storage and local ACKs; the outbox was empty. Chinese rendering and a 700px English layout were checked. Full-store migration, frozen batches, invalid ACKs, resumed intake and repeated opens have Go regression coverage; a real network outage was not induced in this run.


人工验收 / Manual checks：
- 中文和英文会话活动中，历史截断提示显示完整输入的保存/原始字节数；新输入分别显示用户问题与附带上下文的截断情况。
- 带较长附件上下文的新问题保持完整；超过问题自身额度时仍正确截断；关闭 Prompt 采集后不保存两部分。
- 核对历史关联后的工具名称、结果和折叠记录信息；无法唯一关联的返回不显示成功颜色。
- 窄屏检查长截断说明、上下文展开和中英文标签换行。上述检查不以 UI 单元测试替代。

Skill 文件访问没有可靠名称时直接展示文件路径；有路径但无摘要显示“尚未采集内容摘要”，执行结果证据缺失显示“执行结果未确认”。这些信息不能替代批准版本和授权核对。

**English:** Oversized known Codex compaction, metadata, message and tool records retain session context while their skipped bodies remain reported as coverage gaps. Cursors affected by older readers rebuild context in bounded passes over the original file up to the committed position. This does not re-upload history, delete queues or change source logs. Newly collected messages and tools regain their native session identity; historical unassociated records are not reassigned automatically. Unknown identity records still require explicit session metadata. Skill file-access cards show the observed path when no reliable name is available and distinguish missing content digests from unconfirmed execution outcomes.

人工验收补充：在已有长 Codex 会话继续问答，分别核对新输入、过程/最终回复、工具操作及上传 ACK；确认历史缺口仍可识别。Skill 文件访问在中文、英文和窄屏下显示完整可换行路径，缺少摘要仍待确认，不能仅凭文件读取标为 Skill 已加载。

接入与采集页面按适配产品组织；Qoder 只保留一个产品入口，CLI / IDE / Work 的能力和验证范围在详情中区分。原生插件显示 Agent Manager，设置型接入显示 Agent Manager Hook；同一用户下的产品共享 Agent Manager 本地接收器，健康状态与产品安装、授权、首个事件分开判断。内部安装 ID 未变，更新仍通过原有更新流程，卸载保留用户其他 Hook。

桌面卡片明确区分“Hook 插件”和“Hook 配置接入”：Claude Code / Codex 提供“更新 Hook 插件”和“移除 Hook 插件”，WorkBuddy、Qoder 设置入口、Cursor 提供“移除 Hook 配置”。普通插件移除使用宿主原生卸载接口，仅处理当前设备连接拥有的 `aidr-claude@aidr-local` / `aidr-codex@aidr-local`；重新检查原生安装清单确认移除后，才撤销该产品的本机自行接入申请。受管安装仍走单独的系统授权移除入口。未安装时不显示移除按钮；平台管理策略仍限制本机操作。平台明确要求自动安装的宿主可能被再次安装，需由管理员调整目标。移除不停止其他产品共享的接收器，不清空日志、队列或历史；已有宿主会话是否立即卸载由宿主决定，必要时开启新会话。

**English:** Desktop cards distinguish Hook plugins from Hook configuration. Claude Code / Codex provide Update Hook plugin and Remove Hook plugin; WorkBuddy, Qoder settings entries and Cursor provide Remove Hook configuration. Native removal uses user-scope host commands for the plugin owned by this device connection and verifies its absence before withdrawing that product's local enrollment request. Managed removal retains its separate OS authorization flow. Removal is hidden when not installed and respects platform policy. Explicit automatic-install targets may be reinstalled until an administrator changes the target. Other products' shared receiver, logs, queues and history remain available; existing host sessions may need reopening.

Hook 移除人工验收 / Manual Hook removal checks（中文、英文与最小窗口各检查 / check Chinese, English and the minimum window size）：
- 已安装的 Claude Code / Codex 显示更新和移除插件；配置型接入显示移除配置，未安装或状态未知时不冒充可移除。Installed native integrations show update/removal; settings adapters show configuration removal; unknown or absent installations do not claim removability.
- 隔离宿主配置中移除后显示未安装，重复移除幂等；重新启用后可安装，新会话单独核对事件。In isolated host configuration, verify absence after removal, idempotent repeat removal, re-enrollment and new-session event delivery separately.
- 用户既有设置和其他插件保留；其他产品采集不受影响；本产品自行接入申请撤销。Preserve user settings and other plugins; verify other products remain collecting and this product's local enrollment is withdrawn.
- 平台受管策略限制操作；取消系统授权、卸载命令失败或安装清单不可读不显示移除成功。Check policy restrictions; cancelled authorization, failed commands and unreadable inventory must not display successful removal.

2026-10-08 隔离原生验收：Claude Code 2.1.220、Codex 0.162.0-alpha.2 均完成原生安装 → 移除 → 原生清单确认未安装 → 重复移除，隔离配置中的用户设置保留；没有模型调用。Go 回归覆盖所有权不匹配、命令失败、清单仍已安装/不可读，以及成功才撤销本产品申请、保留其他产品和平台策略。实际开发窗口未能由自动化接口定位，中英文、最小窗口布局及按钮点按保留为以上人工验收项。English: Isolated native lifecycle acceptance passed on these exact versions, without model calls. Go regressions cover ownership, command/inventory failures and enrollment preservation. Native window interaction and bilingual/minimum-size layout remain manual checks because the automation interface could not locate the development window.

客户端使用原有设备凭据上传 Skill 元数据，不额外索取管理员 Token、不上传完整 Skill 正文；平台“行为审计 → 会话活动 → Skill 行为”查看名称、尝试/结果、认证与关联证据。全局或单机“审计采集与脱敏 → Skill 使用审计”设置认证核对和告警，默认仅审计。缺少路径、摘要或实例映射时保持待确认；详情分别展示注册、批准、撤销、内容及授权。Hook 回调不执行同步目录摘要计算；可等待精确关联的日志观察，或在待确认详情中请求后台重新采集。重新采集需要新版客户端上报 `skill_audit_observe` 能力、近期在线心跳及唯一可信的 Skill 来源；按当前策略只读采集，新观察与原调用证据分别保留。受管安装目录链接需要与本机安装记录和发布版本精确匹配。

人工 UI 验收清单（中文和英文各执行）：
- 原有插件被识别，Agent Manager / Agent Manager Hook 名称正确，Qoder 单产品与入口详情一致。
- 同一用户多个产品接入时，接收器只显示共享健康；未授权/等待宿主加载/等待首事件仍分别展示。
- 在真实会话切换 Skill 行为，按 Skill/路径、原生轮次、行为、结果、认证筛选；区分本批无匹配但仍可继续查询与最终空结果。点击记录核对时间线，平台刷新保留当前内容，待确认步骤显示可操作原因。
- 长技能名、长路径、摘要及英文在窄屏换行；抽屉宽度不随插件/审计 Tab 改变；仅列表内容滚动。
- 在隔离设备与隔离 Skill 中验收批准、未登记、未批准、变更、撤销、未授权；检查查询失败为待确认，恢复后重新核对；同次调用只有一条告警，不同调用独立。
- 重复安装/更新/卸载确认用户 Hook 保留；宿主信任需人工完成，配置保存不算采集通过。断网积压/恢复与客户端重启不清空队列或游标，再核对严格 ACK。

重新采集人工验收：验证旧客户端升级提示、离线提示、无修改权限禁用、重复点击只建一条任务、任务过期后可重新请求；采集期间关闭策略应使旧回执失效；随后核对更新后的认证结论。核对变更历史受审计保留策略约束。

桌面端“操作记录 → 平台任务”显示重新采集的来源路径、状态和双语错误原因，用于区分同一 Agent 的不同采集任务。

**English — desktop task history:** Activity Records → Platform tasks shows the recollection source path, status and localized failure reason, distinguishing observations for different Skills on the same Agent.

**English — recollection:** Pending details offer evidence inspection and a background, read-only recollection task under the current policy. A unique trusted path, a recent online heartbeat and advertised `skill_audit_observe` support are required. New observations preserve original call evidence. Verify upgrade/offline/permission states, duplicate submission, expiry and stale-policy receipts. A successful receipt does not imply certification. The timeline includes retained evidence, observations and check changes.

逐产品实测状态和具体证据见 [Skill 使用识别与认证审计](external-agent-integration.md#skill-使用识别与认证审计)。WorkBuddy 的新调用通过不替代其他产品或全部审批状态的真实验收。

**English:** Product cards distinguish Agent Manager native plugins from Agent Manager Hook configuration. Qoder stays one public product with separate entry contracts. The per-user receiver is shared, while trust/loading/event evidence stays per product. Skill activity and current certification checks are available inside session activity; global and device policies control checks and audit-only alerts. Test both languages, narrow layouts, immediate filters, independent trust states, existing-install compatibility and offline/restart delivery. See the integration matrix for the exact real-call and sample-only coverage.

采集状态的 Agent 日志按原因显示“正在分批扫描日志”“部分日志文件或目录不存在”或“部分日志待检查”；来源详情直接说明原因和检查步骤。扫描中的来源不单独计为故障；丢失文件报告不能定位受影响会话，需结合最近记录到达及上传 ACK 判断链路。English: Agent log status distinguishes batched discovery, missing files/folders and other issues, with visible explanations. Scanning alone is not counted as a fault. A missing-source report does not identify affected sessions; verify recent arrivals and upload ACKs separately.

人工复核：中英文查看同一来源的原因和建议；混合“扫描中 + 文件不存在”应保留缺失提示；只有扫描进度时不计入需检查来源；检查窄屏长提示换行。Manual checks: compare bilingual reasons and guidance; retain missing-source warnings when scanning is also pending; do not count scanning alone as a fault; check narrow-screen wrapping.

采集状态首次进入显示加载指示与骨架屏，各通道等待自身数据及公共客户端报告就绪后分别展示，不再等三个接口全部结束；加载期间不显示“无来源”等空结果。手动刷新保留原内容并提示正在刷新，后台每 5 秒刷新不闪烁。此页调用日志状态时使用 `include_retention=false`，跳过页面不使用的历史过期数量统计；接口默认仍返回历史统计以兼容其他页面。English: Collection status shows a spinner and skeleton on entry, reveals each channel once its data and shared client report are ready, and preserves content during manual refresh. Background refresh does not flash. This page skips unused historical expiry totals with `include_retention=false`; the API default remains compatible.

人工验收：中英文首次进入、手动刷新、切换通道；慢接口时其他已就绪通道可查看；接口失败显示错误而不是空结果；离开或换设备后旧响应不覆盖新页面；窄屏检查骨架和刷新提示。Manual checks: bilingual initial/manual loading, channel switches, independent slow/failing requests, stale responses after device changes, and narrow-screen loading feedback.


### 概览中的日志来源分类 / Log-source classification

日志发现进度报告包含 `historical_missing`、`unread_missing`、`missing_directories`。历史文件已不存在且持久化游标已读至最后观察大小、没有待完成上下文修复时，归为历史缺失；否则仍为未读或进度未知。目录缺失单独计数。历史缺失保留在平台“概览 → 日志来源详情”和采集状态详情，不再单独触发当前来源故障；历史记录、读取游标和上传队列不删除。最后观察位置之外是否有未观察追加无法确认。

更新部署时先更新平台，再更新客户端。旧客户端可继续上报原格式，页面明确保留“缺失范围未确认”；只有新的客户端进度报告才能区分上述类别。已有平台支持新字段后，重启普通用户后台采集进程即可加载新版分类代码，不需要重新安装 Hook 或重新授权系统采集。

The discovery progress report adds `historical_missing`, `unread_missing` and `missing_directories`. A missing file is historical only when its durable cursor reached the last observed size and no context repair remains. Unread/unknown files and missing directories remain actionable. Later writes before disappearance remain unconfirmed. Deploy the platform first; older reports remain supported with an unknown missing scope. Updating the ordinary-user collector does not require reinstalling Hooks or authorizing the system collector again.

人工验收：移走隔离样本中的已读文件和未读文件，分别检查历史提示与当前问题；恢复文件后验证续采、重启后分类和严格 ACK 保持正常。不要用真实日志删除操作代替隔离验证。/ Manual checks: move read and unread files in an isolated fixture; verify classification, restoration, restart continuity and ACK without deleting production logs.


Qoder 轮次采集使用原生 request-set ID 与日志 UUID 父子关系；同设备、同用户、同会话的工具 Hook 可通过精确原生调用 ID 对照日志归属，不能按时间猜测。旧游标自动有界恢复上下文，不清空队列或重传历史。Hook 安装与日志来源策略独立，需要在“客户端策略 → 采集与治理配置 → 采集与接入 → 日志采集产品”选择 Qoder 才采集已适配的 CLI 格式日志。日志产品与管理员指定的 Hook 产品均按产品分组，Qoder 只显示一项；Hook 的共享设置 / Work 入口在折叠详情中分别选择。既有入口选择保持不变，新选择 Qoder Hook 默认使用共享设置入口。底层继续保存独立适配 ID，不自动扩大到其他入口。每轮模型保留 Hook / 日志来源，Auto 只表示自动模型选择。实际验证范围见集成指南“Qoder 原生轮次与模型”。

**English:** Qoder turns retain native request-set IDs and transcript UUID ancestry. Exact device/user/session/call/tool identity can link tool Hooks to a uniquely logged turn. Checkpoints recover context without clearing queues or replaying history. Select Qoder in the device log-source policy separately from Hook installation. Both policy selectors show one Qoder product; shared settings and Work remain separate choices in collapsed Hook details. Existing entry selections are preserved, and a new Qoder Hook selection starts with shared settings. Policies retain adapter IDs without enabling other entries automatically. Per-turn models retain their source; Auto is a host selection, not a confirmed upstream model.

策略选择人工检查 / Policy selection manual checks：在全局及单机策略中分别展开日志、Hook 产品列表，确认中英文都只有一项 Qoder；展开 Qoder Hook 入口确认共享设置与 Work 独立选择；仅修改其他产品后保存，核对原有 Qoder 入口不变；移除 Qoder 后确认对应通道的入口全部取消，另一通道不受影响；受管模式下不支持的入口不可新增。页面检查可不保存草稿，实际保存和客户端回执在隔离设备验收。


### Hook 工具规则持续有效 / Persistent Hook tool rules

Hook 工具规则发布后持续有效，管理员更新时以更高版本替换；客户端离线和重启继续使用已验证签名的缓存。仅审计模式不执行这些拦截规则，切换模式不改写规则内容。界面不再提供规则有效期。新发布使用签名协议 `aidr.tool-policy/4`，包含 `approval_wait_seconds`，不含策略 `expires_at`；新版客户端兼容已有 v1–v3 签名规则，并按持续有效的配置解释，保留原始签名和历史版本。旧管理台的 `lifetime_seconds` 仅作输入兼容，不参与新规则的期限计算。先升级客户端，再发布 v4 规则；旧客户端无法识别 v4，拦截模式需要升级后使用。

单次人工审批仍绑定具体调用及一次性授权：平台全局或客户端覆盖配置等待时长，默认180秒、范围30–300秒；平台审批记录与客户端使用同一本次截止时间，拒绝、撤销、策略版本更新和授权消耗继续生效。它不是规则配置的有效期。系统采集仍沿用已有独立签名和设备认证续签链路。

**English:** Published Hook tool rules persist until a higher signed revision replaces them, including offline and restart use. Audit mode does not enforce the rules. New `aidr.tool-policy/4` payloads include `approval_wait_seconds` and omit policy expiry; upgraded collectors accept previously signed v1–v3 rule configurations without changing their original signatures or history. Legacy UI lifetime input is accepted for compatibility but does not give new rules an expiry. Upgrade collectors before publishing v4: old collectors cannot interpret it. Exact-call, single-use approval windows remain bounded (180 seconds by default, configurable from 30 to 300 seconds globally or per client, with the same deadline on the client and platform). System collection retains its separate signed device renewal mechanism.

验证范围：自动化覆盖长期规则、旧签名兼容、离线缓存、重启和版本替换；TRAE / TRAE CN 的真实审批结果见文末180秒验收记录。/ Validation covers persistent rules, legacy signatures, offline caches, restarts and revision replacement. See the 180-second acceptance results below for live TRAE / TRAE CN approval evidence.

人工验收 / Manual checks（不新增 UI 单元测试）：
- 中英文工具规则编辑不显示有效期，发布后显示等待客户端获取，不能代替实际生效回执。
- 已缓存规则在离线、跨日和客户端重启后仍有效；新版本替换旧版，签名错误及版本回退仍拒绝。
- 仅审计模式工具正常执行；具体调用审批的取消、超时、消耗和撤销仍独立有效。
- Qoder 两轮切换分别显示输入、最终回复、成功 / 失败工具结果、Hook / 日志模型 Auto；旧无原生轮次事件保持未归属。
- Frozen Qoder coverage retries must retain their identity and receive durable ACK; new batches omit local parser links. Confirm both languages and narrow layouts.

### 授权拒绝与采集恢复 / License rejection and collection recovery

AIDR 将平台 License 暂不可用与设备凭证拒绝分开处理。已识别的 `license.*` 运行时错误保留具体原因，并使用现有退避（最长一分钟）重试；保留待发批次、游标及 ACK 身份，不消耗接收器重启次数。本地采集仍遵守已应用策略、容量与保留期。真实凭证拒绝、设备绑定错误及未知 401/403 保持暂停；未知拒绝不显示为凭证失效。诊断仅保存格式受限的稳定错误码，不保存原始响应或凭证。

旧版持久暂停不会被升级盲目清除。修正平台授权后，通过 `agent-manager-client aidr-desktop --action retry-logs` 对日志通道发起一次恢复；Hook 使用 `--action retry`。以新 ACK、游标推进和平台持久记录确认恢复，不以进程存在代替送达证明。

日志工作进程恢复时，新发现文件的起始时间取“最近 24 小时”和已有最后 ACK 中较早者；已有游标保持原采集范围。保留期水位、停用期间过滤与原文件缺失仍可能造成历史缺口，不能承诺全量补齐，也不清空队列或重置游标。

**English:** Recognized runtime `license.*` failures preserve the specific reason and retry with existing backoff (up to one minute), without exhausting receiver restart attempts. Pending batches, cursors and ACK identities remain intact. Local collection continues subject to the applied policy, capacity and retention. Credential rejection, device-binding errors and unknown 401/403 responses remain suspended; unknown denials are not described as invalid credentials. Diagnostics retain bounded stable codes only, never response bodies or credentials.

Upgrades do not blindly clear legacy suspension. After correcting platform authorization, request one log recovery with `agent-manager-client aidr-desktop --action retry-logs`; use `--action retry` for Hooks. Verify new ACKs, advancing cursors and platform records. For newly discovered files, resumed log workers use the earlier of the last ACK and the default 24-hour lookback. Existing cursors retain their original scope. Retention, disabled collection intervals and missing source files can still prevent complete backfill.

### Codex 会话日志兼容与历史恢复 / Codex log compatibility and recovery

Codex `0.163.0-alpha.10.2` 的 `response_item.additional_tools` 记录工具定义元数据。采集器跳过该元数据并保留原生会话、轮次和调用关联；既有 Codex 日志格式继续使用原解析路径。

升级后，若旧游标保留的隔离记录能与原文件中的该元数据逐字节摘要核对，客户端会分批重读已提交区间，恢复遗漏的消息和会话身份。重读遵守采集范围、暂停边界及保留策略，进度可跨重启续接，不回退已提交游标。平台仅在客户端、来源实例、物理位置、调用 ID、内容及证据摘要一致时移除空会话的错误聚合，原始审计事件保留。源文件已删除、改写或不再保留时，不能保证历史恢复。

Codex `0.163.0-alpha.10.2` emits tool definitions as `response_item.additional_tools`. These records are metadata, not tool executions or session boundaries. The collector skips them while preserving native session, turn and call identities; existing Codex log formats retain their parsing paths.

After upgrade, quarantined metadata is verified against the original file and its recorded digest before bounded replay restores missing messages and identities. Replay respects capture scope, collection pause boundaries and retention, resumes across restarts, and preserves the committed cursor. The platform removes an orphan operation projection only when the client, source instance, physical position, call ID, content and evidence digests match. Original audit events remain unchanged. Historical recovery cannot be guaranteed for deleted, rewritten or expired source data.

大型 `event_msg.item_completed` 超过单条读取上限时只记录内容缺口，保留会话和轮次；真正的会话/轮次边界仍按原规则处理。旧游标因超大记录丢失身份时，升级后分批重读并恢复可解析消息。超大记录本身仍受读取上限限制。

历史重读同时核对 Skill 使用聚合。与已修正来源记录精确匹配的空会话重复项退出当前使用列表，原始事件、旧聚合及核验历史保留；证据不同或身份存在歧义时不合并。后台上传收到 ACK 不代表文件发现和读取已经完成，因此受管采集的起点独立持久化；重启继续使用该起点，历史保留边界仍控制可上传的时间范围。

Oversized `event_msg.item_completed` records report a content gap while retaining session and turn context. Actual session and turn boundaries keep their existing handling. Upgrades replay old cursors whose identity was lost after oversized records, restoring parseable messages in bounded batches. The oversized record itself remains subject to the read limit.

Replay also reconciles Skill usage projections. An orphan duplicate is retired from the active view only when it exactly matches a corrected source record; original events, prior projections and verification history remain stored. Different or ambiguous evidence is not merged. Upload ACKs do not imply discovery or intake completion, so managed intake persists its starting point independently across restarts. Retention continues to bound admissible history.

### Codex 异步结束事件与仅 Hook 会话 / Async completion and Hook-only sessions

Codex 异步命令退出后，应继续通过 `write_stdin` 取得最终结果。读取重定向的日志文件不能替代宿主收尾；跨轮次取回结果时，PostToolUse 可能报告取回结果所在轮次。平台在同一客户端、来源流、系统用户、Agent、会话、原生调用 ID、工具及子代理身份下，恰有一条 PreToolUse 和一条结束事件且双方轮次非空时，允许 Codex 跨轮次关联。时间线归到发起轮次，标注跨轮次完成，各原始轮次和事件不变；重复或缺失身份不跨轮次配对。旧客户端及既有历史事件无需重传或修改，其他 Agent 保留原关联规则。

会话列表以当前保留证据分类。有日志时显示日志计数；只有 Hook 时显示“原因未知”，不能仅凭 SessionEnd 或文件不存在断言漏采或删除。具备正文查看权限并请求问题内容时，已采集的 Codex 后台建议提示标记可得到“推测为后台建议”分类；这是提示内容推断，不是宿主来源认证。没有正文权限、正文缺失或旧版本未采集标记时保持未知。平台目前没有采集宿主的 thread/delete 证据，因此不会自动判为源会话已删除。

After an asynchronous Codex command exits, retrieve its final result using `write_stdin`. Reading redirected files does not finish the host tool lifecycle. A completion retrieved in a later turn can report that later turn ID. Codex Hooks may be linked across turns only when the client, stream, OS user, agent, session, native call ID, tool and subagent match, with exactly one pre-tool event and one outcome, both carrying nonempty turn IDs. The timeline uses the initiating turn and marks cross-turn completion while retaining original events and turn IDs. Ambiguous identities remain unpaired. Existing clients and historical events require no rewrite or re-upload; other agents retain their existing rules.

Hook-only sessions show an unknown cause by default. SessionEnd or an absent source file alone does not prove collection loss or deletion. When authorized question content is requested, a captured Codex suggestion prompt marker can produce a background-suggestion inference. This is not authenticated host provenance. Missing content, restricted access and older clients without markers remain unknown. Host thread/delete evidence is not currently collected, so source deletion is not automatically asserted.

### 结束 Hook 缺失时的执行证据 / Execution evidence without an end Hook

Codex 的 MCP 错误返回和图片查看可能没有结束 Hook。会话时间线和 Hook 详情保留“结束 Hook 缺失”，另列执行状态、证据来源和记录 ID。经协商启用 `completion_schema=1` 后，客户端采集 `event_msg.item_completed` 中 MCP 和图片查看的最小完成元数据，不采集其中的参数或图片正文。原生完成记录不合并为普通工具结果，也不生成 Hook；`completed` 仅表示宿主报告完成，不表示业务执行成功。

命令完成采集通过 `X-AIDR-Command-Completion: 1` 另行协商，服务端返回 `completion_schema=2` 后启用。`CommandExecution` 按 Hook 工具名 `Bash` 关联，保留原始 `completed` / `failed` 状态及可选 `exit_code`，同时显示退出码 0 和非零值；退出码缺失时不补 0，也不根据退出码覆盖宿主状态。完成证据不携带命令正文或聚合输出。旧客户端继续使用原协议；新客户端连接只支持第一版的服务端时保持第一版采集。能力升级会重新安排有界历史重读，旧版未完成的重读检查点不能跳过新增命令证据，MCP/图片证据身份保持不变。

补充状态要求客户端、会话、轮次、调用 ID、工具与系统用户唯一匹配；重复来源、子代理或冲突身份保持未知。旧日志有唯一调用和结果时可补充已返回状态，但会明确标注推断关联；没有明确成败字段时保持成败未知。真实结束 Hook 到达后恢复正常 Hook 配对。仅保留 Hook 和原生完成元数据的会话标为“有原生完成证据”，不归为仅有 Hook；这不证明普通工具日志完整。旧客户端无需升级即可读取旧结果补充；新客户端对未声明支持的旧服务端不发送完成元数据。能力首次启用时，现存 Codex 文件按原采集起点和保留策略进行有界、可恢复重读，原始 Hook 和已存日志保持不变。

**English:** Session timelines and Hook details retain “End Hook missing” while showing execution state, evidence source and record ID separately. Negotiated `completion_schema=1` collects minimal MCP/ImageView metadata from Codex `event_msg.item_completed`, excluding arguments and image bodies. Native completion records remain separate from ordinary tool results and never create Hooks. Completion does not imply business success. Unique client/session/turn/call/tool/user identity is required; ambiguous sources and subagents remain unresolved. Legacy tool results support explicitly inferred associations, with unknown outcomes when no explicit status exists. Real end Hooks restore normal pairing. Sessions retaining only Hooks and native completion metadata are labelled “Native completion evidence available”; this does not prove ordinary log completeness. Older clients remain supported, and new clients emit completion metadata only to supporting servers. First activation schedules bounded, resumable replay of existing Codex files within the original intake and retention boundaries.

Command completion is separately negotiated using `X-AIDR-Command-Completion: 1` and enabled by `completion_schema=2`. `CommandExecution` links to the Hook tool name `Bash`, retaining the native completed/failed status and optional exit code. Zero and nonzero codes are displayed; absent codes stay absent, and codes never overwrite the native status. Command text and aggregated output are excluded from this evidence. Old clients retain their protocol, and new clients keep v1 collection against v1 servers. Upgrades schedule bounded history replay without reusing a v1 checkpoint that would skip command evidence; existing MCP/image identities remain unchanged.

### macOS 独立版豆包工作日志

升级客户端和服务端后，在现有运行治理策略的日志来源中选择 **Doubao Work**（`doubaowork`），启用日志采集。客户端读取 `~/Library/Application Support/DoubaoWork/Default/.doubaowork/agent_mode/workspace/.sessions/<会话>/agents/<代理>/system/trajectory.jsonl`，复用现有本地队列、断点、去重、重试和批量上报。

采集 Read、Write、Edit 等文件工具、Bash 命令和 `execute_defer_tool` 包装的 MCP 调用；MCP 保留实际的 `mcp__...` 工具名。以目录中的会话 ID 归组，以来源文件和原生调用 ID 配对调用与结果，不混合不同子代理。文件路径和命令使用现有元数据规则；文件正文、命令正文和工具返回文本遵循现有内容开关、脱敏和长度限制。MCP 任意参数暂不展开，保留参数摘要和返回内容；不会读取业务文件补齐日志。

用户输入和模型回复沿用现有 `prompt`、`model_response` 开关、脱敏、内容长度限制及审计内容查看权限。升级后，在消息采集协议启用时自动分批重读保留的历史轨迹，补采聊天消息；补采进度可恢复，已采集的工具记录不会重复新增。关闭的内容项只保留消息元数据；系统消息不采集，原日志没有保存的首次提问不能补造。完整会话 ID 直接显示在会话标题下方，可选中复制。

客户端还只读扫描 `Default/IndexedDB` 下聊天页与启动页的 IM 状态缓存（`chrome_doubaowork-chat_0`、`chrome_doubaowork-launcher_0`）。已确认发送的提问使用 `extra.conversation_id` 和原生 `message_id`，回复的 `reply_id` 指向提问轮次；重复缓存按消息 ID 去重，不按文字或时间匹配。回复仅采集明确结束、可见的顶层正文块，以过程回复展示；缓存中仍在生成的最终回复不作为完整回复采集。缓存并非完整历史库：已清理的消息无法补采，原轨迹中没有 ID 的正文继续保留未归属，不以相同文字合并。新来源使用缓存记录时间，原轨迹仍使用采集时间。历史补采遵守既有采集时间范围、保留期、内容开关和脱敏规则。

**English — message cache:** The client reads the chat and launcher IM state caches under `Default/IndexedDB` without modifying them. Acknowledged prompts use native message and conversation IDs; reply IDs identify the originating prompt. Duplicate cache entries are deduplicated by ID. Only finished, visible top-level assistant text blocks are captured as commentary. Streaming final replies are not treated as complete. These caches are not a full history store: removed messages cannot be recovered, and ID-less transcript messages remain unassigned rather than being merged by text. Cache records use their recorded timestamps; trajectories retain collection timestamps. Existing lookback, retention, capture and redaction controls apply.

轮次关联另读取同一安装目录 `sdk_storage/log/saman_frontend_*.log` 和 `saman_*.log` 的原生元数据：通过 `tcid → agent_id → chat_session_id/session_id → send_message_id/开始消息 ID` 关联工具调用和结果，消息 ID 作为轮次标识。兼容旧消息接收事件和新版 local-office 生命周期开始事件；不会以时间、命令文本或相同工具名猜测关联。缺字段、冲突、原日志被清理时保留未归属。轨迹中的聊天正文没有原生消息 ID 时也保留未归属，不能把同会话全部消息归到某一轮。

更新客户端和服务端后，关联索引变化会触发可恢复的历史重读，通过现有 `turn_links` 补充已保留记录；不重传已确认的正文、不重复新增工具，不恢复已过期记录。索引缓存 15 秒，采集器按现有调度重新检查；单次读取上限 128 MiB，超限或文件不可读时停止本次关联，普通轨迹采集继续。新建两轮无敏感命令会话已验证调用和结果各自归属不同消息 ID。MCP 的前端 `tcid`、运行时 `call_id` 与轨迹调用 ID 尚无已验证映射，仍保留未归属。

**English — turns:** Native tool IDs are joined through the runtime agent ID and frontend request metadata to the originating message ID. Both legacy receive events and local-office lifecycle start events are supported. Missing or conflicting identities remain unassigned, including transcript messages without native message IDs. Changes trigger resumable metadata-only history enrichment through existing `turn_links`, without restoring expired content or duplicating tools. Upgrade server and client together. The metadata index caches for 15 seconds and scans at most 128 MiB; unavailable metadata leaves transcript collection running. A fresh two-prompt command conversation verified distinct native turns. MCP's frontend, runtime and transcript IDs still lack a verified join and remain unassigned.

本地 2.33.1/2.33.3 样本没有执行时间戳，`observed_at_source=collection` 表示采集时间。首次启用和历史补采按预算读取保留的轨迹，不能用采集起点筛掉更早执行的记录，补采时间也不代表原始对话发生时间。结果已返回与执行成功分开：保留返回内容，成败保持未知，不从任意输出文字推断退出码。不提供 Hook 阻断。豆包升级改变日志格式时需重新验证。

**English:** Select **Doubao Work** (`doubaowork`) in the macOS runtime log policy. File operations, Bash and deferred MCP calls reuse checkpoints, deduplication and batch delivery. User input and assistant replies follow the existing prompt/model-response switches, redaction, limits and protected content access. With message capture negotiated, upgrading automatically replays retained trajectories in resumable batches, adding messages without duplicating tool records. Disabled content retains metadata only; system messages and questions absent from the original log are not reconstructed. Full session IDs appear below session titles. Times represent collection, including historical backfill, rather than original execution. Returned content does not establish success. Hook enforcement remains outside this adapter.

### macOS 飞书内豆包工作的本地电脑模式

已闭合的原生工具交换可补充消息轮次和回复阶段：以用户记录分段，段内全部工具调用 ID 必须准确归到同一提问、全部结果返回后，末尾不再请求工具的唯一回答标记为最终回复；携带工具调用的正文标记为过程回复。缺少首条用户记录的初始段仍需完整调用 ID 链。缺 ID、冲突、未返回或中断段保留未归属，不按文字或时间匹配。这里的“最终回复”表示该段模型回答结束，不表示业务任务成功。

更新后的服务端与客户端通过 `message_link_schema=1` 协商元数据补充能力；历史记录按原事件身份补轮次/阶段，原始正文、摘要和事件数量不变。旧服务端继续按原能力采集。桌面轮次导航直接显示序号；未归属记录单独保留入口。

飞书缓存被替换后，客户端复用仍在保留期内、已按完整工具事件身份保存的轮次关联补充轨迹消息；确认上传后释放正文不会丢失这项关联。没有保存过的关联不能凭顺序或相同文本恢复，仍归入未归属。

**English — retained associations:** After Feishu replaces its cache, retained tool-event identities can recover previously verified turn associations for transcript enrichment, even after acknowledged bodies are released. Associations never captured cannot be reconstructed from ordering or matching text and remain unassigned.

**English:** Closed native tool exchanges can enrich message turns and phases. All call IDs in a user-delimited segment must resolve to one native prompt, and all results must return before its sole terminal answer without tool requests. Tool-bearing prose is progress; the terminal answer is final for that exchange, not proof of business success. Missing IDs, conflicts, incomplete results and interrupted segments remain unassigned. Metadata enrichment is negotiated with `message_link_schema=1` and preserves original event bodies, hashes and counts. Desktop navigation shows explicit round numbers alongside the unassigned entry.


飞书本地电脑模式复用 **Doubao Work**（`doubaowork`）日志来源和现有采集开关、正文开关、脱敏、保留期、本地队列及批量上报。自动发现只枚举 `~/Library/Application Support/LarkShell/aha/users/` 下最多 16 个配置目录，并分别读取：

- `doubao/.doubao/agent_mode/workspace/.sessions/<会话>/agents/<代理>/system/trajectory.jsonl`：文件操作、命令、MCP 原生调用及返回内容；无原生消息 ID 的轨迹正文保留未归属。
- `profile_explorer/IndexedDB/https_www.doubao.com_0.indexeddb.leveldb`：已发送提问、明确结束且可见的回复正文、MCP 操作块。仅接收任务元数据指向当前飞书本地工作区的消息；普通飞书聊天和云电脑任务不作为本地执行采集。兼容消息时间的秒数字符串及毫秒数值。
- `sdk_storage/log/agent_infra/agent_infra_*.log`：原生 `tcid → agent_id`，结合消息缓存 `reply_unique_key → reply_id`，将命令和文件工具归到原生提问消息 ID。关联索引缓存 15 秒；新增关联沿用 `turn_links` 补充保留的历史事件。字段缺失、冲突、缓存清理或预算超限时保留未归属。

同一操作系统用户下，两端同步的缓存消息沿用独立版逻辑身份（会话 ID、原生消息 ID、正文块 ID），MCP 消息块使用 `cache-mcp:<消息 ID>:<块 ID>` 标识，并按调用/结果分别保存。相同 ID 和内容只入队一次，物理来源分别作为证据保留；不按文字去重，因此不同轮次的同内容调用仍分别保留。缓存中的 MCP 操作块包含参数和结果并能归轮；它与轨迹原生调用 ID 尚无可靠映射，二者保留为不同证据，不按工具名、参数或结果强行合并。来源目录表示采集位置；同步副本不证明在该客户端执行过。

历史补采限于本机仍保留的记录。正在生成或存在正文冲突的缓存块不作为完整回复；原轨迹仍可保留其已记录正文。采集不修改飞书缓存、不注册 Hook、不阻断工具。验收应检查多轮命令的调用/结果归属、MCP 消息块与未归属原生证据、两端同步去重、正文开关及脱敏、暂停/恢复、重启后的补采与重复上报情况。

**English:** Feishu local-computer tasks on macOS reuse the **Doubao Work** log source and its existing collection, content, redaction, retention and upload controls. Discovery is limited to 16 profile entries under `LarkShell/aha/users`, their Doubao trajectories and the Doubao WebView IndexedDB. Only task metadata identifying the profile's local workspace is accepted from the cache. Native runtime call IDs join through request IDs and message `reply_unique_key`/`reply_id`; missing or conflicting links remain unassigned. The 15-second correlation index enriches retained history via existing turn links. Synced cache messages and MCP blocks share logical identities across clients while retaining separate source evidence; identical content with different native IDs is not deduplicated. Finished MCP blocks provide parameters, results and a message turn, but are not merged with native trajectory calls without a verified ID join. A synced cache does not establish execution on the reading client. Historical recovery is limited to retained data; unfinished/conflicting reply blocks are not complete replies. No cache writes or Hook enforcement are introduced.

本地 Skill 列表按内容区域宽度自动切换四列或紧凑两行布局；长名称省略显示，可悬浮查看完整名称。全选旁的帮助提示说明跨页选择与筛选清空规则，窗口缩放不改变选择。

English: The local Skill list switches between four columns and compact two-line rows based on available content width. Long names are truncated with the full name available on hover. Help beside page selection explains cross-page selection and filter resets; resizing preserves selection.

### 内嵌 ZIP 与原始发布内容 / Nested ZIPs and original release contents

ZIP 上传、Scanner 和网络 ZIP 导入仅解开外层传输包，保留 Skill 根目录中的原始文件和内嵌 ZIP。签名、内容指纹、发布包及详情文件树均基于该原始目录；详情直接预览普通文件，不提供内嵌 ZIP 的展开树。

安全扫描独立创建临时副本，展开内嵌 ZIP（包括后续内嵌 ZIP，最多 8 层），各压缩包合计最多 50,000 个展开文件、1 GiB，单文件最多 100 MiB；路径逃逸、软链接及超限均中止扫描。展开目录独立命名，避免覆盖原始同名目录。分析结束或异常退出会清理副本；在 Windows/macOS/Linux 上，下次扫描通过跨平台进程存活检查回收已退出进程留下的专用临时目录，不向进程发送信号；仍存活或无法确认状态的进程目录保留。

旧版本保持历史内容，不原地改写签名包；重新提交原始目录以生成一致的版本。扫描缓存版本已更新，避免沿用旧分析流程的结果。

English: ZIP uploads, Scanner submissions, and network ZIP imports unpack only the transport archive. Original Skill files and embedded ZIPs remain unchanged for fingerprints, signatures, release packages, and the detail file tree. Ordinary files remain previewable; embedded ZIPs are not expanded in that tree. Security analysis uses a disposable copy and recursively expands ZIPs with an eight-level limit, aggregate limits of 50,000 files / 1 GiB, and a 100 MiB per-file limit. Unsafe paths, symlinks, and exceeded limits stop the scan. Copies are cleaned on completion or exceptions; subsequent scans on Windows/macOS/Linux reclaim directories owned by exited processes using a cross-platform liveness probe without sending signals. Directories with live or unknown owners are preserved. Historical signed versions remain unchanged; resubmit originals for a consistent version. The scan-cache schema has been updated.

### 历史采集提示确认 / Acknowledging historical collection issues

运行治理页的“已知悉，不再提示”只隐藏当前历史采集问题，确认状态保存在当前桌面客户端的本地界面存储中，重启后保留。诊断文件和平台审计记录不删除，也不补齐曾丢失的事件。新发生时间或不同原因、产品、Hook 的问题会重新显示；无法保存确认时保持提示并显示错误。清除客户端界面存储后，仍保留的历史问题可能再次显示。

“Acknowledge and dismiss” hides only the current historical collection issue. The acknowledgement is stored locally by this desktop client and survives restarts. Diagnostic files and platform audit records remain intact; lost events are not reconstructed. A new occurrence, cause, product or Hook appears again. Storage failures keep the notice visible with an error. Clearing the client's UI storage may show the retained historical issue again.

### Skill 治理配置 / Skill governance settings

“客户端配置 → Skill 治理”提供“使用审计 / Usage audit”和“分类处置 / Classification actions”两个子标签。默认进入使用审计，无审计查看权限时进入分类处置。使用审计配置后台异步核对和告警；分类处置配置按 Skill 状态执行的动作。两个子标签分别预览并保存，切换保留未保存草稿。内容与脱敏保留采集范围、脱敏、大小限制和保留期限。使用审计与内容脱敏可分别继承全局，既有配置按原继承状态兼容；复用原有接口和审计策略下发协议。

**Client settings → Skill governance** separates Usage audit from Classification actions. Each section previews and saves independently. Usage audit checks asynchronously and reports or alerts; classification rules define actions for Skill states. Content/redaction manages capture, redaction, size limits and retention. Usage audit and content/redaction inherit independently while preserving existing policy choices and reusing existing delivery protocols.

### 日志与客户端空闲开销 / Log and client idle overhead

已发现但暂时缺失的日志源保留游标和覆盖状态，按目录重扫周期（默认 30 秒）复验；文件恢复后重新加入采集。每次复验检查全部父目录和文件本身，复用本次文件属性结果。日志通知按原采集轮次有界读取（默认每 2 秒，最多 256 条、最多等待 5 毫秒）；通知错误或溢出恢复轮询。文件变化、读取失败及策略变化继续触发正常读取。

Discovered missing sources retain their cursors and coverage and are revalidated at the directory rescan interval (30 seconds by default). Revalidation checks every parent and the file, reusing that pass's metadata. Notifications are consumed at the existing collection cadence (normally every two seconds), bounded to 256 notifications and five milliseconds per round. Notification errors or overflow restore polling. File changes, read failures and policy changes retain the normal read path.

完全未变化的批次不重复递增源版本或生成审计记录。事件、关联、游标或覆盖变化时，读取调度标记和检查点在同一事务提交；仅调度变化按读取批次合并提交，提交前核对源版本。中断后未提交标记会再次复验。待读取源查询预取每批最多 32 个检查点，游标和覆盖编码合计不超过 1 MiB；超过预算单独查询，预取值只消费一次，源提交、清理和关闭时失效。

Unchanged batches avoid redundant revisions and audit records. Read-scheduling markers commit with changed events, links, cursors or coverage; scheduling-only changes are batched with source-revision checks. Uncommitted markers cause revalidation after interruption. Ready queries prefetch up to 32 checkpoints within a combined 1 MiB encoded cursor/coverage budget. Larger entries use individual queries. Prefetched values are consumed once and invalidated on source commit, pruning or close.

已完成读取的缓存仅在文件身份、权限、大小、修改时间、变更时间及读取参数保持一致时复用，不保留事件正文。TeleAgent 同时检查数据库 WAL，并要求分页快照完整校验；无法取得可靠变更时间时正常读取。剩余执行时间不进入已完成读取的缓存键，未完成读取仍受本轮预算约束。

Completed reads are reused only while file identity, permissions, size, modification/change times and read parameters match; the cache retains no event bodies. TeleAgent also checks its WAL and requires a fully validated paginated snapshot. Systems without reliable change-time metadata continue reading. Remaining execution time is excluded from completed-read keys, while incomplete reads remain subject to the current budget.

日志状态的 5 秒上报节流在统计查询之前执行，首次立即上报。日志统计使用同一只读事务，Hook 状态及运行时、上传目标配置合并查询。日志与 Hook 队列优先重发冻结批次；空日志队列不创建冻结事务或读取发送所需的 stream ID，不缓存空状态。Hook IPC 使用向量写入，保留原协议、身份验证、超时和短写处理。

Log status applies its five-second throttle before querying counts, with an immediate first report. Log statistics share one read transaction; Hook status and runtime/upload-target reads are consolidated. Log and Hook queues prioritize frozen batches. Empty log queues skip freezing transactions and sending-only stream-ID reads without caching emptiness. Hook IPC uses vectored writes with the existing protocol, authentication, deadlines and short-write handling.

日志库使用 8 MiB SQLite 页缓存预算及历史清理、来源和缺失统计索引，按需增加内存占用。旧库先释放已持久确认正文并回收空间，再建维护索引；索引事务因容量不足失败时回滚，使用不强制索引的查询继续采集和处理队列，下一次打开重试。未确认数据、冻结批次、游标、配额、WAL 和同步持久化等级不变。

The log store uses an 8 MiB SQLite page-cache budget and maintenance indexes, increasing memory use on demand. Upgrades release durably acknowledged bodies and reclaim space before building indexes. Capacity failures roll back index creation and use queries without mandatory index hints; the next open retries. Unacknowledged data, frozen batches, cursors, quotas, WAL and synchronous durability remain unchanged.

私有配置每次仍校验权限与文件身份，在支持变更时间的系统上复用未变化文件字节，绑定配置只读取一次并统一规范化。相同同步错误不重复写入，恢复和其他任务的成功时间继续记录。守护进程健康检查保持每秒执行，持续健康时间由原子同步写盘的健康文件提供，失败与恢复仍写数据库。普通事件上传只监听 `events-wake` 文件，删除或重命名后重新创建监听，保留 30 秒持久队列补偿检查；采集、心跳、上传和健康检查周期保持。

Private configuration reads still validate permissions and file identity, reusing unchanged bytes where change-time metadata is available and normalizing binding configuration from one read. Repeated identical sync errors avoid writes; recovery and other tasks' success timestamps remain recorded. Daemon health checks run every second, with successful health timestamps provided by the atomically replaced, synchronized health file; failures and recovery remain in the database. Ordinary-event uploads watch only `events-wake`, recreating its watch after removal or rename and retaining the 30-second durable-queue repair check. Collection, heartbeat, upload and health-check intervals remain unchanged.

日志发现器在每轮有界探测中合并提交文件和目录元数据；失败时回滚并重新枚举，保持原有探测周期。豆包会话关联每 15 秒检查 SDK 日志，按文件复用解析索引：支持变更时间的系统上，文件身份、大小、修改时间和变更时间均未变化时复用；变化的文件重新解析，删除文件的关联从合并结果中移除。无法取得变更时间时继续重新解析。关联冲突、日志读取上限和路径校验保持。历史清理使用确认时间、源关联索引；首次升级需要在本地数据库创建索引，会增加少量磁盘占用和启动时间，既有审计数据与保留规则不变。

Each bounded discovery pass commits file and directory metadata together. Failures roll back and restart enumeration without changing the probe interval. Doubao correlation checks SDK logs every 15 seconds and reuses per-file parsing indexes when identity, size, modification time and filesystem change time are unchanged. Changed files are reparsed; deleted files are removed from the merged index. Systems without change-time metadata continue reparsing. Conflict handling, read limits and path validation remain in place. Retention queries use acknowledgement-time and source indexes. The first upgrade builds these local indexes, adding some disk usage and startup work while preserving audit data and retention rules.

Skill 监听保留配置根目录的直接父目录监听，用于发现同名目录替换；父目录不存在时监听最近的现存祖先，无关路径事件不触发扫描。目录删除、重命名及携带明确路径的异步路径消失错误，复用 300 毫秒事件合并窗口重新注册受影响根目录并请求补偿扫描。无法确认监听完整性的错误立即重建监听器；连续失败按 1、2、4 秒递增退避，最长 30 秒，恢复后请求补偿扫描。健康监听器不启动周期重试定时器。

Skill monitoring retains the direct parent watch of each configured root to detect replacement at the same path; if the parent is absent, it watches the nearest existing ancestor. Unrelated paths do not trigger scans. Directory removal, rename, and asynchronous missing-path errors with an identifiable path use the existing 300 ms coalescing window to re-register affected roots and request a compensating scan. Errors that leave watch integrity uncertain trigger an immediate rebuild; repeated failures back off from 1 to 2 to 4 seconds, capped at 30 seconds, with a compensating scan after recovery. Healthy monitors have no periodic retry timer.

审批等待时长由签名工具策略下发。升级客户端后，在全局或单机安全规则页保存以发布新等待时长；旧配置显示默认180秒时也可直接保存完成升级。旧接收器缺少能力报告时拒绝发布并提示升级。仅修改时长保留已有申请的原截止时间，规则变化或接收器重启仍使旧申请失效。CLI在本次截止后保留5秒返回预算；支持审批的受管PreToolUse宿主配置使用315秒上限，覆盖300秒最大等待及通信开销，不随每次配置变更重启宿主。平台列表及详情每秒显示剩余等待，过期禁用审批，详情自动同步回执。


2026-10-28 本机 TRAE CN 3.4.9 实测：浏览器在申请后 89 秒批准、100 秒拒绝均有效；自然超时的原生 PreToolUse 持续 180.126 秒并拒绝执行。仅批准标记文件存在，平台倒计时与客户端截止时间一致，超时回执自动刷新。现用全局/客户端“安全规则”页均可配置时长；本机最终全局与客户端覆盖均为 180 秒。此结果限定本次 TRAE CN 宿主版本。

2026-10-28 本机 TRAE 3.6.4 两个入口完成 180 秒审批回归：SOLO / Work 在申请后 95 秒批准、85 秒拒绝，专用自然超时 180.243 秒；切换 IDE 界面后在 74 秒批准、93 秒拒绝，专用自然超时 179.730 秒（截止时间按整数秒）。批准、拒绝由平台浏览器完成，平台倒计时和回执与实际文件结果一致。两个界面复用同一宿主会话引擎，各次工具调用及审批独立；本结论不扩展到独立旧产品 TraeWork。临时测试规则已移除。

## 千问办公（QwenWork CN）

macOS 客户端可以发现 /Applications/QwenWorkCN.app，从 Info.plist 读取版本，并发现共享与 identity-data/v1/*/skills 个人 Skill 目录。日志与 Hook 在产品目录中独立启用；本机 Hook 设置位于 ~/.qwenworkcn/settings.json，安装后开启新会话。共享 plugins/plugins-custom 只报告已安装包，启用状态未知；身份加密 MCP 配置不读取。验收版本为 1.4.0（26102705），其他平台及引擎不作支持承诺。参见 [长期接入说明](external-agent-integration.md#千问办公--qwenwork-cnqwenwork)。

**English:** On macOS, the client discovers QwenWorkCN.app and its bundle version, shared Skills and identity-scoped personal Skills. Enable logs and Hooks separately, install user settings, then start a new conversation. Shared plugin packages retain unknown enablement; encrypted connector settings are not read. The verified host is CN 1.4.0 (26102705). Upgrade the platform, sidecar and desktop together.

## ZCode 客户端接入

macOS 通过 /Applications/ZCode.app 和 Info.plist 发现 ZCode 及版本。日志来源为 ~/.zcode/cli/db/db.sqlite，Hook 用户配置为 ~/.zcode/cli/config.json 的 hooks.events。启用采集、安装 Hook 后新建会话；原生运行程序只在会话加载时读取 Hook 配置。先验证接收器、平台 ACK 和真实执行结果，再使用执行前策略及审批。

用户/已知工作区 Skill、MCP 配置、插件目录和安装记录分别展示，未明确的启用状态保持未知。Hook 安装/移除保留其他配置；宿主 Hook 进程失败可能继续执行，移除接入不能仅停止服务。完整范围和三端升级说明见 [ZCode 接入](external-agent-integration.md#zcodezcode)。

撤回接入前检查客户端的“采集与接入 → 安装、更新与重试”：管理员仍指定 ZCode 且启用自动安装时，后续策略应用会重新安装已移除的 Hook。需要保留产品范围、由用户控制安装时选择手动安装，再在桌面移除 Hook 配置。移除后分别确认本机配置、桌面“未安装”和平台插件接入状态；历史事件仍然保留。完整平台与 macOS 桌面按钮验收记录见 `outputs/zcode-acceptance/full-ui/验收报告.md`。

**English:** Discover the macOS ZCode bundle, enable SQLite logs, install user Hooks, then start a new session. Check receiver health, platform ACK and actual tool execution separately. Inventory distinguishes configuration, installation and enablement. Native Hook failures may fail open. Upgrade the server, Go client and desktop together.

If ZCode remains an administrator-selected product with automatic installation, a subsequent policy application can reinstall removed Hooks. Select manual installation when users should control installation within that scope. After removal, verify the local configuration, desktop status and platform plugin status separately; historical events remain available.
