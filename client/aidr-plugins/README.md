# AIDR native lifecycle plugins (P3)


## 2026-10-04：Hook 接收故障的审计与控制语义

仅审计模式在 Hook 输入解析、接收、持久化或并发容量失败时，不以审计故障拒绝普通工具：stdout 返回空 Hook 响应、退出 0，stderr 提供 `aidr_hook_audit_gap` 和具体稳定原因。原生宿主自己的权限、审批和执行结果仍独立生效。收到该响应不是执行成功或完整审计的证明。

工具控制模式继续要求有效签名策略及匹配的授权决定；接收器不可用、缺少决定、审批超时/中断保持拒绝。模式未知、连接配置不可读以及桥接二进制不可用时，不能猜测为仅审计。暂停采集仍按既有 gate 处理，不把主动暂停当作本次故障。

客户端生成的私有连接文件记录 `control_mode`（来自实际接收器使用的固定公钥配置）及设备/平台队列内的 `gap_file`。旧桌面连接缺少字段时，仅在既有私有偏好、连接路径和设备 socket 匹配后读取模式；其他旧手动连接故障时保持未知。已连接的控制接收器覆盖过时的审计声明；控制配置连到仅审计接收器时，`PreToolUse` 缺少决定仍拒绝。IPC 复用已有 `state.control_mode`，保留旧桥接严格字段解码兼容。

缺口保存在队列目录内单个 0600 `bridge-gap.json`，只含 Agent、Hook 点、稳定原因和时间，不含命令、参数、Token、Prompt 或正文。它只保留最近一次观察，不是丢失数量或事件 ACK；恢复接收器不清除历史缺口，也不补造失败事件。桌面“Agent 运行治理”显示持续双语历史提示和时间。诊断无法保存或读取时报告 `aidr_hook_gap_report_failed`。该诊断目前仅保存在本机，不追加到平台事件或冻结批次。

**生效与复验：**这是源代码修复，需使用包含新 Go 桥接及界面资源的客户端构建，既有运行进程不会因源码变更自动升级。本轮未提交、推送、发布、部署或替换日常运行二进制。脚本和原生信任内容未修改；实际安装升级仍按既有产品流程进行，不写入信任哈希。

**人工 UI/宿主清单（中英文均检查）：**在独立测试设备的新会话中，确认为仅审计后使自有接收器不可用，执行临时目录中的 `/usr/bin/true`，核对工具没有被 AIDR 审计故障拒绝、宿主 stderr 有缺口；进入 Agent 运行治理核对持久提示、具体原因、时间及英文换行。恢复接收器后历史缺口仍可见，新事件可另行确认 ACK。工具控制环境中同样故障必须拒绝；缺失/过期策略和审批中断不得放行。不要终止业务接收器或改日常策略来进行此测试。

**English:** Audit-only intake failures return an empty, non-blocking Hook response and a stable audit-gap warning. Tool control, unknown modes and interrupted approvals remain fail-closed. A private bounded diagnostic retains the latest observed gap; it does not reconstruct events, count losses, or acknowledge delivery. Existing frozen bytes and ACK contracts are unchanged. Check the persistent historical warning in both languages and verify native host behavior using isolated new sessions; source changes do not update installed binaries automatically.

## 当前三通道自动管理进度（2026-10-04）

最新续验：普通Codex0.160.0的18条真实Hook、七组Pre/Post及双语网页通过，另六条真实Hook通过非空冻结积压安装包更新，24条全部严格ACK。标准测试包后台301秒的300条受控输入全部到达平台并ACK，队列采样峰值2，App/接收器RSS峰值64.73/23.23 MiB；这不是300次真实Agent调用。

本机开发签名的真实ES仅采集现已通过订阅、精确身份和平台链路：180.666秒，主监视4493条记录，加上先前拒绝未签名Codex直接根的36条记录共4529条唯一记录；暂停上报积压4423条，恢复后字段/身份匹配、待发/冻结0、报告缺口0。独立父进程预期的1000个后代全部匹配exec、exit及归属根；受控sleep与孤儿进程匹配。再次启动保留同一状态目录，新增53条后平台共4582条，中英文真实网页确认sleep及仅采集/停止时禁用终止。客户自动授权入口仍未实现，正式产品签名/发行资格仍未验，本机开发通过不能替代这些项目。

当前内置Codex二进制实际未签名，不能作为已验证的直接根；临时签名测试根启动的新Codex任务在85秒预算内请求超时，没有工具执行记录，Codex执行sleep仍未通过。标准安装包Hook链路连续前台601.007秒（601个焦点样本、600条受控输入）及随后后台301.001秒（301个后台样本、300条受控输入）均通过；900条全部与平台唯一记录及本地durable ACK身份/序号匹配，每阶段待发/冻结0、队列采样峰值2，同一接收器持续运行。真实中英文客户端状态检查通过；这不代替runtime_watch真实relay长时验收。隔离41893设备已通过产品预览/CAS恢复继承且未配置（新版本0:4）、上报关闭，凭证8吊销；测试App/接收器/socket/基础工作者回收，测试Home原目录恢复，用户确认语言恢复。1226条平台Hook全部匹配本地durable ACK，数据库、游标、回执和事件保留。日常LaunchAgent在19:24:03改为已安装Applications客户端，区别于上午开发版基线且不是测试路径；来源尚未确认，没有覆盖或重新加载，等待用户选择保留或恢复。ES自有进程已退出，临时平台签名配置已移除，只用产品API新增允许/空根修订3，测试策略历史与事件保留，原策略不存在的状态没有被伪装恢复。日常配置和基础服务未改变。详见主仓库已有验收记录。

**English:** Ordinary native Codex 0.160.0, bilingual details and a nonempty frozen-batch package upgrade passed. Local development-signed, collection-only ES now passed real subscription, exact identities for 1000 descendants, durable backlog recovery and bilingual system-event pages. The first live round retained 4529 unique records; a same-state restart added 53. No reported source gaps or pending runtime records remained. The actual Codex executable is unsigned, and its bounded controlled task timed out before a tool result; direct Codex-root and Codex-executed sleep acceptance remain incomplete. Packaged Hook intake/upload passed 601.007 seconds foreground and 301.001 seconds background; all 900 labeled inputs matched unique platform records and durable ACKs, with zero pending/frozen queues. Actual bilingual client status views passed. This does not prove runtime-watch GUI stability. Temporary ES signing configuration was removed and empty allow-only revision 3 retained policy history. Product preview/CAS restored isolated inheritance at revision 0:4 and reporting disabled; owned processes/socket were reclaimed, credential 8 revoked and the test Home restored. All 1226 retained platform Hooks match durable ACKs, with fixture and native counts recorded separately. The daily LaunchAgent differs from the morning developer baseline and now points to the installed application; it was not overwritten or reloaded and awaits the user choice. Customer automatic authorization and formal distribution remain unverified.

以下分项保留先前执行证据；当前完成状态以本节开头和已有验收记录的最新小节为准。

本节以本轮代码和实测为准，独立于既有 P1/P2/P3 出口及普通插件接入验收。平台默认客户端策略和设备覆盖复用现有权限、继承、预览/CAS及版本；运行目标包含 Agent 日志、插件 Hook、macOS 系统事件。运行目标、审计采集许可、设备上报许可和控制策略分别生效，正文范围与脱敏仍使用既有审计配置。

日志循环已接入现有 Go 用户后台，独立于页面和桌面自有 Hook 进程，不新增服务。新客户端以协议3回报各通道自己的策略版本、观察时间、传输、待发及严格ACK时间；旧客户端的未报告通道保持未知。关闭日志目标停止新读取，已有冻结积压继续上传；重新开启采用持久化恢复边界并报告停用期间缺口。平台/设备绑定目录保持，凭证轮换加入旧工作循环后刷新传输，不重算冻结批次。

独立41893设备已完成Codex0.160.0日志自动管理、持久化、严格ACK与真实中英文网页：18事件/9操作，退出码0/7有结构化依据。服务端游标可选call_turns[].tool补齐后，原15条冻结批次原摘要恢复上传；重启不重复。前一日志分项结束时策略已恢复继承/未配置、上报关闭、当时凭证吊销；本轮续验状态见本节开头。日常目标及正文/脱敏未改。当前私有0.160候选尚未替换日常Go侧车。

Codex0.160.0普通插件接入已补验：用户在独立原生profile审阅并信任Hook；一个真实新任务分别调用七次工具，18条Hook持久化并严格ACK，七组Pre/Post身份准确，中英文网页详情通过。另一个真实单调用任务产生六条Hook，用于非空冻结积压跨安装包更新，恢复上报后全部ACK且旧回执不变。精确0.160.0现加入普通插件已验版本；相邻0.160.1仍未验证，受管Codex仍限0.159.0。Hook未提供结果依据时保持未知，日志的明确退出码不填入Hook记录。

**English:** Ordinary Codex 0.160.0 plugin integration now passed user-reviewed native trust, seven real tool calls, eighteen exact acknowledged Hooks, and bilingual web details. Six additional real Hooks survived a nonempty frozen-batch package replacement and were acknowledged after reporting resumed. Only the exact verified version was added; managed Codex remains 0.159.0. Missing Hook results remain unknown. Daily policy and audit scope were not changed. See the latest acceptance record for test cleanup and load-test status.


Hook采集gate单独持久化在既有hook_meta，关闭后拒绝新记录，已确认的重试保留原身份，旧冻结字节和摘要保持；上传不受gate关闭影响。已应用的桌面监督代码使停用中的自有接收器持续排空，确认待发为0后回收，关闭再开启不因同一配置反复启动。通道实际版本从已持久化gate和原生停止证据读取，不从待应用目标猜测。连续恢复设21次上限，到达后需显式重试；既有退避和配置/队列绑定保持。新增字段可缺省，旧队列无需重建。

自动检查另通过最终Go相关三包race、冻结失败ACK重试、停用重启及确认后事件幂等；隔离Rust12项含真实自有侧车离线停用/恢复（PID相同、待发1）、回收/轮换/上限及停止身份投影。现有桌面i18n29项和平台i18n22项通过，平台构建10.99秒。尚未启动更新后的桌面测试包，不能用受控侧车回归代替真实桌面/Agent/平台闭环或15分钟负载验收。

系统通道新增仅采集实现：Go启动前有界核验原生能力，原生仅订阅NOTIFY_FORK/EXEC/EXIT；独立验证签名后保留Agent映像身份、版本和期限，移除控制规则与拒绝动作，使用独立采集缓存，不读取终止命令。原生采集边界及Go兼容回归通过，但这不等于已经提供客户自动授权入口或完成真实ES订阅。服务端/页面区分“仅采集运行中”与“控制在线”的补丁已获批准并应用，后台已自动重载；真实ES仅采集状态分支仍待验；仅采集时服务端拒绝新终止请求，不改写既有回执。桌面日志重试按钮禁用条件覆盖缺陷已随补丁修复并应用，真实桌面分支仍待验。

系统非特权条件预检新增在Go侧，检查结果不作为运行或授权证据；桌面“系统采集条件”中英文只读入口已应用，新Go侧车支持该动作，实际标准测试包双语页面已确认签名未验证、固定组件缺失及授权/订阅未知。开发版原生界面另按安装形态复验。拟采用的原生按需系统入口会新增一个SMAppService LaunchDaemon注册，需要单独批准及有效产品签名/公证；当前没有安装或注册该组件。本机可用签名身份数量为0，不能用开发签名或既有插件授权代替系统通道实机验收。

系统既有队列新增非特权有界补传函数，退出时复用5秒/8次预算；停止监视与已确认排空分别报告。离线、暂停上报、无效ACK保持冻结字节并退避，认证拒绝保留队列并返回；预算耗尽不能报已清空。受控HTTP/SQLite回归覆盖300条记录、限次、重启、冻结恢复、错误ACK、取消与错误设备。系统自动入口的停用长期排空及真实ES仍未实施/验收；该补强不替代它们。

系统仅采集模式另补齐Go管理层异常退出的回收路径：原生控制管道断开记录既有稳定原因码，原子通知主循环停止采集并走既有收尾。非特权子进程回归直接调用生产控制读取器，真实关闭OS管道并核对断开健康JSON；没有创建ES客户端，真实取消订阅及安装包故障回收仍待验。


**已批准应用与现场核对：**两份审查补丁已应用；随后用户批准开发侧车更新及相关自有进程重启。按prepare-update、同路径原子替换、reconcile-service及既有Tauri重载流程，基础Go45612→35033、开发桌面85502→38017、自有Hook85757→38088，后台85148未再次重启。LaunchAgent程序参数和配置结构保持，设备连接配置摘要不变；未安装新服务、改平台策略或操作ES。旧二进制、连接配置及队列数据库私有备份保留，新随包二进制与候选摘要匹配。

真实channels-status/system-check均返回成功；此前日常抽样1839条ACK身份/序号与平台一致，升级前1806条保留，不代表长时负载。开发版package_unverified、系统授权/订阅未知。日常目标未配置、日志旧心跳10月2日17:46:42；独立41893的0.160.0日志与普通插件原生信任/实际Hook已通过，受管支持仍独立待验。

本轮直接使用更新后的开发侧车，Rust12项11.71秒通过；此前Python8项、既有desktop i18n29项/web i18n22项、JS/Python语法与前端构建通过，Go三包race为已通过缓存。原生桌面自动操作工具无法识别非应用包开发进程，未通过启动另一已安装客户端绕过；系统条件/日志重试等真实桌面分支需人工核对。默认未配置日志/系统保持未报告，真实双宿主、系统collecting分支、三通道实际策略与15分钟负载仍未验。

客户入口为平台 **客户端管理 → 平台默认客户端策略** 或设备详情 **策略与审批 → 客户端策略** 配置目标；桌面 **Agent运行治理** 核对收到的目标与实际观察、执行原生信任/授权及故障重试；**行为审计 → 采集状态** 查看各通道独立诊断。普通客户流程不依赖开发用aidr-sync命令；支持新自动管理的安装包仍需分项实机验收后发布。


## 当前验收状态（2026-10-02，P3 续验）

原 P3-01～04 和阶段出口在既有 macOS、Claude Code 2.1.220、Codex 0.158.0-alpha.2.1 声明范围内已有验收证据。后续客户接入补强单独计状态：普通接入、自动接收器、标准安装包生命周期、正文权限与双语详情已验；macOS 原生受管授权与完整受管链路仍未通过，不因普通接入成功宣布全部完成。

本次独立 Claude 2.1.220 新会话 `aacc08e6-e9d2-48c8-b8f5-662788802483` 只调用一次 Bash，13.137 秒完成、CLI 退出 0、临时 marker 实际生成，六条原生 Hook 持久化并严格 ACK。用户报告的模型恢复已用该任务确认，不能扩展为长期供应商健康保证。已有 Codex 会话 `01a0fa4b-514d-7942-958f-bb4dfaaec873` 六条 Hook，以及新 Claude Pre/Post，均已在真实中英文网页核对会话/call、命令、工作目录、未知结果/退出码和详情关闭；网页不会把独立 CLI 退出 0 填入缺失的 Hook 证据。

真实冻结积压安装包更新已补验：暂停隔离设备上报，旧标准包 Go `d6860b94…` 的独立 Claude 会话 `e86e0482-5563-4164-b69a-65ddaf31c080` 在 10.007 秒完成一次 Bash；六条待发，其中两条构成非空冻结批次。正常 Quit 后恢复最新标准包 Go `ba96ba5e…`，自动接收器恢复，冻结字节及 SHA-256 `26d6f4726c42b9723fc4dcbbcbea5d91ca38e1f79dbc7162b2f898fbd2d56546` 完全保持。重新允许上报后六条全部 ACK；重放原冻结批次得到相同设备/stream/digest、accepted=2、durable=true，平台未新增逻辑事件。该证据是普通接入的真实冻结积压跨包兼容，不替代系统受管升级/移除或正式发行验收。

结束核对：41891 独立设备 `amc_475de6e4066e48fde2b0dbdd` 的 182 条已 ACK event_id/seq 与认证平台集合精确相同，待发/冻结 0；平台全部 388 条，既有 370 条摘要保持。默认运行目标 6/任务 21 和审计策略 31 保持；脱敏开启、三类正文关闭、采集开启/保留 7 天。设备“允许上报”已恢复；隔离后台、数据库及签名密钥未重启或重置。最新标准包运行 App 49019、唯一自有接收器 49088，既有私有基础工作者 29882 保持；终态为本次采样，不作永久计数。

真实测试用户准备前的基线：本次已有有限授权，系统级受管测试当时因真实运行冲突暂停：日常真实 Home 的基础工作者、接收器及业务 Codex 进程仍在运行；日常 bridge 为 ordinary。产品受管入口校验操作系统真实用户 Home，不能把私有测试 Home 冒充真实 Home，也不能把日常设备/队列切成独立测试设备。该基线阶段未调用系统安装/移除、未弹管理员授权。已私有保存基线；`/etc/codex/requirements.toml`、Claude macOS managed-settings 和产品 managed 目录均仍不存在；日常 bridge 与 launchd plist 字节、权限、所有者、摘要完全不变，不需要恢复系统配置。随后使用真实aidr-test用户和独立设备完成取消、批准及三种受管生命周期；当前系统变化和恢复待验项见下文。

普通 Codex 精确支持 0.158.0-alpha.2.1、0.159.0、0.159.2、0.160.0；受管 Codex 目标仍为精确 0.159.0；Claude 目标 2.1.220。本次没有删除版本限制、伪造原生信任或启动手动接收器。Claude 信任报告仍未知，实际 Hook 触发证据单独保存。

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

“客户端管理 → 客户端策略 → 审计采集与脱敏”管理全局默认脱敏和采集范围；进入具体客户端的“客户端策略 → 审计采集与脱敏”，可关闭“继承全局审计策略”并单独配置。管理员分别配置 `capture.prompt`、`capture.tool_output`、`capture.file_body`，默认均关闭；脱敏默认开启。选项只作用于后续来源事件，不回读业务文件或重采旧原文，也不改变行为字段白名单。版本4行为与版本2 Hook支持这些选项；旧客户端继续行为字段范围，其正文支持与实际应用保持未知。

Prompt当前明确适配 `UserPromptSubmit.prompt`；文件正文适配Write/Edit/MultiEdit的明确内容、apply_patch的原始补丁字符串、明确patch/command字段以及可靠调用绑定的Read文本结果；工具输出适配文本结果、明确stdout/stderr/output字段和文本块。未知参数不完整透传，包装调用不会据字符串推断文件正文。日志结果只在来源会话内的明确call/turn绑定下分类；有界游标保存16个调用绑定，歧义或缺失时不推测。每事件最多4片段、每片段1024 UTF-8字节、合计2048字节；先执行所选脱敏策略再截断，记录来源字段、源字节数、脱敏及截断标记。截断切中脱敏替换时缩短尾部，保持可验证且不增加预算。

客户端以`X-AIDR-Policy-Schema: 2`协商范围凭据。服务端保存设备/流/序号绑定的范围快照，不能凭客户端自行声明接受正文；新旧凭据在同一策略版本分别签发。已有策略凭据表增加可空`capture_json`和`lifecycle_json`，旧行不回填。SQLite事件、游标、逻辑身份、冻结批次字节/摘要和严格ACK保留；历史缺失正文明确显示信息不足。策略每30秒尝试刷新，离线使用有效持久缓存，首次失败默认开启脱敏且不开启正文。

列表、操作、审批详情及投影JSON只返回正文描述，正文通过设备可见性与独立`clients:read-audit-content`权限接口按需获取；响应`Cache-Control: no-store`。访问审计只记录来源、记录ID和片段数。页面关闭、设备变化或失去权限清除展示数据；不自动展开正文。脱敏关闭时，只在授权范围内保留原文，说明凭证可能进入本地与平台。

**实际证据：**隔离设备在无手动接收器、无桥接环境变量下运行Codex0.159.0，开启脱敏时Prompt与工具输出中的虚构秘密已遮蔽，关闭时虚构Token及完整git文本保留（git文本仅为printf输出，未执行提交）。该阶段3次有限模型任务新增17条真实Hook，流内54条本地/平台回执ID相等、待发与冻结批次均0，原242条平台Hook摘要不变。文件正文实机任务被原生只读沙箱拒绝，文件未生成，Hook未提供正文；该项未通过。后续真实中英文网页已核对来源描述、按需正文、脱敏Prompt/输出、关闭脱敏时的完整git文本及收起清除；接口证据与网页证据分别记录。隔离配置已恢复开启脱敏、三类正文关闭，该阶段实际应用版本4；日常后台未改。

**English:** The existing audit settings own three independent, default-off source-content options. Behavior v4 / Hook v2 clients receive device/stream/sequence-bound scope receipts; legacy receipts and frozen bytes survive. Explicit source fragments are bounded to 4 items, 1024 UTF-8 bytes each and 2048 bytes total, with redaction before truncation. Lists contain descriptors only; content requires separate permission and an audited, no-store request. Live Codex0.159.0 proves Prompt/tool-output ON and OFF handling with fictional data. The file-write probe was rejected by the native read-only sandbox and is not a file-body acceptance pass. The original conservative test policy has been restored. Bilingual content viewing passed; Restricted-reader browser checks passed in both languages; managed system authorization remains pending.

## 平台自动接入策略进展（2026-10-01）

平台默认客户端策略新增运行治理目标：开启/暂停、目标宿主、自动/管理员安装、普通/企业受管接入、随包自动/手动更新，以及不重试/固定次数/持续重试。配置只存于默认策略，设备页继承查看；权限沿用普通管理员查看、超级管理员保存及既有影响预览。旧部署未保存该配置时保留原本地偏好。

协议2客户端通过既有心跳及每5分钟一次的有界宿主检查触发 `aidr_plugin_action` 协调任务；设备、策略、随包版本和实际宿主变化参与幂等标识，时间刷新和健康计数不生成新任务。原子领取、持久回执与手动动作共享通道和文件锁。执行前重新认证核对当前策略，旧目标不能覆盖新目标。平台目标、策略收到/检查/应用时间、宿主信任和事件ACK独立显示。普通模式已有后台安装/更新差异协调；macOS受管模式新增原生系统授权入口和固定动作安装组件，部署Codex requirements.toml或Claude managed-settings.json，原子合并并保留有界恢复依据。受保护的版本回执和二进制摘要证明安装版本；Codex原生hooks/list另外核实受管加载与信任。系统级安装、取消/批准及原生受管加载尚未实机验收，不能称受管接入通过。

原生监督器持久保存平台/设备绑定的启动次数、最近故障、暂停原因及下一次重试时间；初次启动与重试分开计数，退避封顶并加入抖动。重开应用不重置故障耗尽，健康正常退出允许下一次初始启动。单实例锁覆盖停止和退避期间；切页和后台不依赖展示计时器。授权取消、失败或中断结果绑定策略版本持久记录，不自动重复弹窗；中断安装需检查真实文件及恢复依据。宿主检查时间变化不重启健康接收器。隔离默认策略已通过真实后台自动安装全新Claude配置（未点接入）；Codex0.159新会话及暂停补传测试共新增12条真实Hook全部ACK，Claude新会话因模型HTTP502只收到3条生命周期事件，工具操作未验。此前记录ID及摘要保留，该阶段54条本地/平台集合相等、待发0；后续真实中英文已按精确会话核对事件、详情及来源正文。三种重试及准备锁竞争已有本任务自有进程实测，双语保存失败/重试和409冲突已验；低权限正文页面已通过中英文实测；成功文件正文后续已由真实Codex/Claude新任务及持久查询补验；新增正文网页与专用macOS受管授权仍需分项验收。详见主仓库 experiments/aidr-agentlog/ACCEPTANCE.md，不等同目标完成。

设备“暂停上报”只拒绝新事件批次，继续允许绑定正确且权限有效的凭证获取审计策略、报告状态和获取控制快照。本地日志/Hook继续按容量限制持久化。上传返回稳定码 `aidr_upload_reporting_paused`，按1/2/4/8/16/32/60秒封顶退避；实际轮询周期可能延后下一次尝试。认证或权限失败停止上传并保留待发数据，需修正配置。冻结批次在暂停、策略刷新及新增采集期间保持原字节，恢复后严格匹配ACK。状态报告成功不代表事件送达：桌面和平台分别展示最后状态报告、上传原因/下次尝试及最后事件ACK。ACK时间在客户端匹配成功后持久保存；旧客户端未报告时保持未知。

**English:** The default platform policy owns runtime targets and retries. Protocol-2 clients reconcile through existing atomic tasks and durable receipts. Ordinary automatic installation and real Codex 0.159.0 audit delivery have isolated-device evidence; native macOS managed authorization and new-content browser checks remain pending; real Codex/Claude file-body persistence passed; restricted-reader browser acceptance passed in both languages; bounded optional source content is implemented. Pausing device reporting retains local intake and frozen batches, with bounded upload backoff; it does not invalidate device authentication. Status-report success and the client's durable event-batch ACK time are shown separately. Older reports without ACK telemetry remain unknown. Fifty-four local/platform Hook receipt IDs match after pause/resume and source-content tests; Bilingual event review passed; restricted-reader content access passed in both languages with metadata-only projections and no content-view action.


## 客户入口与平台管理 / Customer entry and platform management

Codex 0.159.0 / 0.159.2 自检使用原生 App Server 的本地市场查询和有效配置校验，不等待 CLI 的远端插件目录。缺失配置来源、市场读取错误或多来源冲突不会显示为“未安装”；本地版本由原生报告的包 manifest 读取，不替换成随包版本。0.159.0已通过原生安装、12项持久信任与8条真实审计事件验收，现开放接入；自检、信任和实际事件仍分别展示。

**English:** Codex 0.159.0 / 0.159.2 inspection reads local marketplaces and effective configuration through the native App Server, without waiting for the CLI remote catalog. Missing sources, read failures and ambiguity remain unknown. The version comes from the native-reported package manifest. Codex 0.159.0 passes the installation gate after native installation, twelve persistently trusted hooks and eight real audit events; these remain separate evidence states.

桌面侧边栏 **Agent 运行治理 / Agent Runtime Governance** 提供接入、自检、接收器状态和故障重试；平台 **客户端管理 → 设备详情 → Agent 运行治理** 可下发安装、更新、自检、接收器启用/停用。远程任务沿用设备权限，安装包提供插件版本，客户无需管理接收器终端、桥接环境变量或 Token。平台接管后，本地安装/启停不可覆盖目标。原生插件启用和 Hook 信任与接收器启用是不同状态；安装不自动授予信任。

插件包现为 **0.1.1**。更新调用宿主原生机制并核对文件，保留已有停用状态；重复安装及更新不自动开启停用接收器。已有手动桥接存在时显示迁移/冲突，不接管进程或重置队列。普通 Codex 插件由用户在原生 `/hooks` 审阅；受管方式由宿主认可的系统管理配置提供信任，仍须核对实际加载。新配置需新会话生效。普通接入兼容目标为 Claude 2.1.220、Codex 0.158.0-alpha.2.1、0.159.0和0.159.2；0.159.0 普通客户流程已通过原生信任、真实审计和包升级后的队列保留，系统级受管加载另验。此次6种审计事件不替代该版本全部事件载荷或控制验收。

接收器随桌面生命周期运行。切页、最小化和后台持续接收；关闭窗口/退出回收自有实例与 socket，保留 SQLite、冻结批次和 ACK。父管道关闭也使接收器结束，崩溃恢复按平台重试策略执行；默认首次启动加两次重试，支持不重试或持续有界退避。页面可见时两秒读取快照，健康每五秒更新、15 秒过期，平台显示最后报告时间，超过30秒标为历史。页面刷新不进行宿主扫描；原生后台每5分钟及显式自检读取有界宿主来源。

**English:** Platform automatic installation requires no per-device Connect click. The dedicated desktop sidebar and device-detail Agent Runtime Governance panel expose actual state and any necessary native authorization. The existing authenticated client worker performs bounded installation/update/inspection tasks; remote management prevents local target overrides. Package 0.1.1 updates through native host commands, preserves disabled states and queues, and does not grant trust. Receiver execution follows the desktop lifetime, including background operation and parent-pipe cleanup. Recovery follows the platform retry target: none, a fixed number of retries (default two after the initial launch), or continuous capped backoff with jitter. Visible pages read snapshots; status reports retain their timestamps. Ordinary installation targets are Claude 2.1.220 and Codex 0.158.0-alpha.2.1 / 0.159.0 / 0.159.2. Codex 0.159.0 has customer-flow audit evidence for six event types; 0.159.2 native installation, trust inspection and automatic coordination passed, and fresh native tool runs with durable ACKs passed after refreshing isolated authentication. Managed Codex access remains limited to 0.159.0 pending dedicated-system acceptance.

本轮独立包、平台任务、真实 Claude、离线补传和中英文网页/桌面记录见 [已有验收记录](../../experiments/aidr-agentlog/ACCEPTANCE.md)。

本次实际包十分钟最小化后台121次采样健康有效，进程及14条ACK保持、待发/冻结均0；独立设备205条明确合成协议记录在真实中英文浏览器按100/100/5分页，身份与重复上传逐条核对。前者是低负载连续性，后者是网页/协议验收。后续独立 Codex 0.159.0 会话新增8条真实 Hook，客户设备22条全部ACK且零待发，旧14条保留；请求命令、未知结果及中英文详情逐条核对。

**English:** The packaged application passed ten minutes of minimized idle continuity with 121 health samples and unchanged ACKs. Real Chinese/English browser pagination verified 205 explicitly synthetic protocol records in pages of 100/100/5. A separate Codex 0.159.0 native session added eight real hooks, with exact local/platform identities and all twenty-two receipts acknowledged. These checks do not replace sustained load testing.

两个独立宿主包 `aidr-claude`、`aidr-codex` 通过共享 Go 客户端发送生命周期证据。已实现审计链路、打包安装、自检、精确范围审批和独立来源关联。审计接收成功不代表权限授予或 OS 操作成功。P3-01～04 及阶段出口已在当前 macOS、Claude Code 2.1.220 与 Codex 0.158.0-alpha.2.1 的声明范围内验收；Claude 16/16、Codex 12/12 种声明事件均有原生证据。

**English:** Separate Claude and Codex packages forward lifecycle evidence through the shared Go client. Audit transport, installation, inspection, scoped approvals and independent evidence correlation are implemented. Event receipt grants no permission and proves no OS operation. P3-01 through P3-04 and their exit criteria passed in the declared macOS scope for Claude Code 2.1.220 and Codex 0.158.0-alpha.2.1, with native evidence for all 16 Claude and 12 Codex event types.

## 当前验证范围

固定实测版本为 Claude Code 2.1.220 和 Codex 0.158.0-alpha.2.1；本机 PATH 的 Codex 0.132.0 不视为已验证兼容版本。安装、重复安装、停用状态、真实审计和原生批准/拒绝已有独立报告。Codex 控制试验使用单次信任覆盖；原生 `hooks/list` 的新配置实测 12 个 Hook enabled 但 untrusted。用户原生审阅后，持久信任及新启动 App Server 的实际触发已补验，见下方生命周期记录。

**English:** Installation, idempotent installation, disabled-state preservation, native audit and allow/deny probes have separate reports for Claude 2.1.220 and Codex 0.158.0-alpha.2.1. Codex control probes use a one-invocation trust override. Native inventory found 12 enabled but untrusted hooks in a new profile; user-reviewed persistent trust and execution after restart have since passed. PATH Codex 0.132.0 is not a verified target.

两个真实 Claude 会话共享 MCP 服务和常驻 shell，20 次调用形成 20 条日志操作与 48 条 Hook，重复同步无新增操作。独立并发审计实测 20 路同时在途；独立审批试验中只有批准调用到达共享 shell。Claude 日志/Hook/ES 联合采集及中英文详情通过；日志关联保持 inferred，工具进程保持 unknown。精确 ES 记录仅证明 IPC 桥接进程的历史实例，不等于工具执行身份或当前存活。

**English:** Two native Claude sessions produced 20 operations and 48 hooks through a shared MCP server and persistent shell, without duplicate operations on resync. A separate audit measured 20 concurrent requests; a separate approval probe allowed only the approved call to reach the shell. Bilingual log/Hook/ES details passed. Log linkage remains inferred and tool-process attribution unknown; exact OS evidence describes the historical IPC bridge only.

真实网页已通过：中文批准与英文拒绝对应原生 Claude 文件标记及客户端 ACK；中英文列表/详情读取故障、持续提示和重试；过期授权保留历史核销回执；协议请求撤销和双页面版本冲突；只读策略控件。只读账号修改策略/提交决定被 403 拒绝，跨设备查询被 404 拒绝。协议请求没有执行宿主工具，不冒充原生验收。

**English:** Real browser checks cover native Claude approval/denial with marker and ACK evidence, bilingual read failures and retry, expired grants retaining receipts, protocol-request revocation and stale-revision conflicts, and read-only policy controls. Read-only writes return 403 and cross-device reads 404. Protocol UI probes execute no native tool.

来源配置摘要变化、停用状态、过期接收器、规则冲突与扩大，以及 514 分区汇总/64 条明细截断/244 字符工具名的中英文页面已验证。英文确认说明、同设备延迟审批响应时关闭/切换详情、延迟读取后关闭，以及 55 条审批的中英文分页（50/5，无重复）已通过真实浏览器检查。中英文带待审批记录的只读详情和正常设备切换已验证，按钮禁用且服务端拒绝写入。协议样例经真实 API 和中英文页面验证来源/文件不可读、报告随实际时间转过期，以及 12 个匹配规则仅展示前 8 个 ID，同时保留第 12 个最终决定规则。来源歧义/根冲突/证据截断的中英文真实页面已补验。Codex 持久信任及重启后压缩/中断已通过；声明生命周期矩阵及 P3 出口审计已完成。Linux ARM64 容器内核下的真实 Unix socket、身份与授权回归已通过；独立 Linux 主机端到端仍待验，其他平台返回不支持。此验收范围不扩展至其他版本、其他平台或正式分发。

**English:** Bilingual pages have verified source digest changes, disabled sources, stale receivers, policy conflicts and expansion, 514-partition totals with 64 displayed details, and 244-character tool names. Real browser checks also passed the English confirmation, closing/switching details during delayed same-device decisions, closing delayed reads, and 55 approvals across two pages (50/5, no duplicates). Populated read-only details and normal device switching passed in both languages; action buttons are disabled and server writes denied. Protocol fixtures passed real API and bilingual browser checks for unreadable sources/files, reports becoming stale with actual elapsed time, and eight displayed matching IDs out of twelve while retaining the twelfth deciding rule. Bilingual ambiguous/conflicting/truncated evidence pages have passed. Codex persistent trust, the full declared lifecycle matrix and the P3 exit audit passed. Linux ARM64 container-kernel Unix socket and authorization checks passed; standalone Linux host end-to-end acceptance remains separate, and other platforms return unsupported. Acceptance does not extend to other versions, platforms or formal distribution.

复验命令、逐次报告、截图和证据边界见 `experiments/aidr-agentlog/ACCEPTANCE.md`。本实现未复制 AgentGuards 业务代码；插件布局和宿主反馈边界用于参考，审计、设备认证、脱敏及上传沿用本项目契约。

**English:** See the existing acceptance record for commands, reports, screenshots and evidence boundaries. No AgentGuards business code was copied; AIDR retains its own audit, device-authentication, redaction and upload contracts.

## 客户端安装与自动运行

客户入口是桌面客户端 **Agent 运行治理**。完成现有设备认证，管理员确认现有设备凭证具有 `aidr:heartbeat` / `aidr:report-events` 权限并允许设备上报后，客户端按平台默认策略自动接入所选 Claude/Codex；选择管理员安装模式时，由平台下发明确安装任务。随包 Go 程序执行原生安装，生成固定路径的 bridge 与仅含 socket 的私有连接文件；Token 只在既有设备配置读取，不进入宿主配置、参数或普通日志。新终端不需要 `AIDR_CLIENT_BIN`、`AIDR_HOOK_SOCKET`，也不需要保持终端运行。普通模式遵循原生用户审阅，受管模式使用宿主认可的系统配置；配置在新会话应用，实际信任须核对原生报告。

正式包包含 Go sidecar 与两种插件的六份声明资源。首次接入将 sidecar 原子复制到 `~/.agent-manager/aidr/runtime/agent-manager-client`，连接位于 `bridge.json`；升级保留稳定路径，用新随包程序原子替换缓存。内容及连接路径决定独立 marketplace 版本目录，重用前校验八份文件 SHA-256；不会覆盖其他宿主插件和设置。生产程序不接受开发 sidecar 环境覆盖。开发与正式包资源路径分别定位，必须执行 `npm run prepare` 后运行开发版。

原生后台每秒检查启用偏好和设备配置，页面不消费或不渲染时仍工作。专用私有 root 的桌面锁和 Go 状态锁共同防止竞争，遇到已有 socket/旧手动连接显示冲突，不杀外部进程、不移除旧 socket。凭证变化重启自有实例，同一平台与设备保留 stream、事件及冻结批次；平台变化选择独立绑定目录，保留旧积压。异常按平台重试策略处理；默认首次启动加两次重试，显式重试重新计数。健康文件过期显示采集未知；平台 ACK、上传错误、待发量与本地运行分开。

切页、最小化及后台运行保留实例；本客户端关闭窗口会退出应用，关闭/正常退出和更新重启回收自有接收器、socket，保留 SQLite。无 launchd 或开机常驻服务。本地 IPC 不依赖网络；平台策略约30秒刷新、事件上传约2秒轮询，按既有缓存策略与 ACK 契约补传。首次未取得脱敏策略仍开启。默认仅审计；已核实的工具控制公钥在受管偏好中显式配置，原控制实例按迁移说明处理，不能用新默认审计冒充旧控制。

迁移：确认旧实例的平台、设备与状态目录，恢复原连接并排空积压，保留状态；由原进程管理者停止它，再通过原生宿主移除旧 AIDR 插件。重新点击客户端接入并审阅新定义。无法读取来源时不按“未安装”覆盖；安装器保持用户停用状态。没有自动转换旧手动队列，也没有删除历史或冻结批次。

当前 macOS 接入目标为 Claude 2.1.220、Codex 0.158.0-alpha.2.1 和 0.159.0。0.159.0 的原生安装、12项持久信任、新会话8条真实审计Hook与平台精确ACK已验。桌面只读 `hooks/list` 报告当前 inventory 的 `trusted/needs_review/unknown`，平台治理面板显示最后一次客户端自检和时间；旧来源投影的 `hook_trust` 保留其原证据。Linux 自动管理代码未做独立宿主验收，Windows 接入明确不支持，不能按跨平台构建推定通过。

macOS 实际 `.app` 已验证 Claude 按钮首装/重复安装与独立新会话，26条唯一 Hook、本地 ACK 和平台集合一致，含断网6条补传；Codex0.159.0另新增8条真实Hook。原生菜单退出、窗口关闭、启停和三次崩溃后的显式重试保留队列。启动管道先登记自有 socket 身份，原生最终 Exit 同步回收；没有有效健康时传输/上传保持未知。网页设备详情 → 行为审计 → 生命周期与 Hook可查看白名单命令、工作目录、结果依据与原生身份，中英文实际页面已核对。受管工具控制公钥配置、该新Codex版本其他载荷/控制及正式升级分发另验。

**Manual UI checks / 人工复验：**核对安装/启用/信任/接收器/传输分别显示；以新会话执行临时目录内一次工具调用，在上述网页匹配session/call；中英文检查长路径和详情关闭。关闭后确认接收器结束，重新打开确认同一stream恢复；停用不删除待发。新客户仍须原生审阅 `/hooks` 后独立触发；本轮0.159.0已完成该步骤。205条分页、加载失败与重试已有真实页面证据；正式签名升级、长期负载及其他平台仍需验收。

**English:** Customers use Agent Runtime Governance after device authentication. The bundled Go receiver runs under desktop supervision; the generated bridge contains stable paths and no tokens, so independent terminals require no AIDR environment. Native trust and actual delivery remain separate. Collection survives navigation/minimization/background operation; closing or quitting stops owned processes without deleting queues. Platform-configured crash recovery retains attempts, recent failure and next retry time; correction-required faults suspend recovery. Existing sockets/manual installations require explicit conflict resolution. Immutable package hashes, platform/device-bound queues, credential rotation and strict ACKs preserve pending data. The default is audit-only; existing control requires an independently verified pinned key and explicit migration. Codex 0.159.0 installation, persistent trust, eight native audit events and bilingual details passed; broader payload/control and distribution acceptance remain separate.

## 开发与独立 CLI 接收器

### 接收器实际报告

设备详情 → 行为审计 → 采集状态 → 接收器来源与上传诊断，查看各接收器实例上报的模式、版本、状态、待发数量及平台接收时间。约每 30 秒上报，页面刷新时按 90 秒阈值标记是否过期；版本一致不证明插件启用、信任或实际执行。无报告保持未知（包括旧客户端）。网络失败不停止审计 IPC，失败状态码为 `aidr_hook_runtime_report_failed`。

临时报告每设备保留最多 256 个实例，写入时清理超过 7 天的报告；达到容量明确拒绝新增实例报告，不删除审计数据。页面只展示最近 20 个并标记截断。

**English:** Receiver telemetry is separate from published policy and execution evidence. Reports arrive about every 30 seconds, become stale after 90 seconds, and are shown as fetched snapshots. Unknown remains unknown for older clients. Per-device telemetry is bounded to 256 instances with seven-day expiry on writes; audit history is unaffected.

**UI 手验 / Manual checks:** 中英文核对无报告、仅审计、策略缺失/有效/过期、版本不一致、多实例、停止超过 90 秒后刷新、长实例 ID 换行和面板关闭。Verify these states in both languages; real browser acceptance remains pending.

### 已发布策略变化解释

设备详情 → 策略与审批 → 工具审批与规则 → 工具策略 → 已发布策略变化与权限解释，展示当前及上一已发布版本的决定变化、决定规则和冲突。Agent/工具分区计数不是调用或进程数量；规则比较也不证明接收器已应用。先核对本地 `aidr-hook --health` 的实际控制模式、版本和状态。初次发布没有基线，过期策略显示历史解释。大结果保留完整汇总，只截断展示明细。

**English:** Expand the published-policy explanation in device details to compare deciding rules and conflicts. Counts represent Agent/tool partitions, not calls or processes. Published configuration does not prove client application; inspect the receiver health separately. An initial policy has no comparison baseline, and expired rules are presented as historical evidence.

### 操作详情中的关联证据

设备详情 → Agent 日志观察 → 操作详情可查看匹配原生调用身份的插件证据。当前日志缺少用户/子代理来源，匹配标为推断关联，不用于审批或 OS 归属。日志结果和 Hook 结果分别保留；多来源、工具不一致及证据预算不足会说明原因。历史上传正文不重写。

**UI 手验待办 / Manual UI checks:** 中英文分别打开有匹配、无匹配、歧义和超预算的操作；核对 Hook 退出码与日志结果独立、长证据 ID 换行、弹窗滚动与关闭、刷新后迟到事件出现、操作总数不因 Hook 增加。Matched evidence, independent results, scrolling and closing passed in both languages. Ambiguity, budget and late-arrival branches remain pending; API tests do not replace them.

### 开发验收：独立 Claude 会话

`native_claude_acceptance.py --native-permission-deny` 使用仅审计接收器，在新临时目录请求一次未加入宿主允许清单的 touch；不复用 AIDR 授权、公钥或共享 MCP。报告分别记录待发与已 ACK 的 Hook 数量，宿主拒绝和文件不存在不自动证明 PermissionDenied/PermissionRequest Hook 已触发，须与实际事件核对。该模式与 `--expected-decision` 等控制验收参数互斥。

**English:** The native permission-denial probe requests one non-allowlisted touch in a fresh temporary workspace using an audit-only receiver. It reports pending and acknowledged hooks separately. Host denial and an absent marker do not prove that permission hooks fired; inspect the actual events. This mode cannot be combined with AIDR control, shared MCP or the basic audit API verifier.

增加 `--permission-host` 可由本任务的 stdio MCP 接收原生权限提示，固定返回拒绝，不执行请求参数，也不保存参数正文。Claude 2.1.220 实测一次 Bash 权限请求、匹配拒绝结果及 5 条基础 Hook 全部 ACK；这个无界面入口没有观察到 PermissionRequest/PermissionDenied。当前[官方 Hook 文档](https://code.claude.com/docs/en/hooks#permissiondenied)将 PermissionDenied 限定于 auto 模式；当前文档不能替代固定版本的实际触发证据。

**English:** Add `--permission-host` to route the native prompt through the owned deny-only stdio MCP fixture. It executes no input and retains no argument bodies. Claude 2.1.220 produced one denied Bash permission request and five acknowledged baseline hooks, but no PermissionRequest/PermissionDenied hook on this headless path. Current official documentation limits PermissionDenied to auto mode; documentation is not fixed-version runtime acceptance.

Codex 原生批准/拒绝试验使用相同控制后台脚本：

```sh
backend/.venv/bin/python experiments/aidr-agentlog/native_approval_acceptance.py \
  --agent codex \
  --codex /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
  --model gpt-5.6-sol
```

模型参数应使用本机已有可用模型。该测试只在新的私有配置中对已审查插件使用单次信任覆盖，不代表持久信任已完成。[Codex 官方 Hook 信任说明](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)要求审核当前 Hook 定义；不能把安装或启用当作已信任。Codex 与 Claude 原生允许/拒绝已分别有实机报告；网页批准/拒绝已有独立 Claude 闭环，剩余页面分支见上方清单。

**English:** The Codex probe uses a fresh private profile and a one-invocation trust override for the vetted local plugin. It validates native allow/deny behavior, not persisted hook trust. Select an already available model; browser approval acceptance remains separate.

原生批准/拒绝受控试验从仓库根目录执行：

```sh
backend/.venv/bin/python experiments/aidr-agentlog/native_approval_acceptance.py \
  --claude "$HOME/.local/bin/claude" \
  --settings "$HOME/.claude/settings.json"
```

脚本创建新的临时后台和签名密钥，限定两个真实 Claude 会话，各尝试创建自己工作目录内的标记文件；分别通过真实 API 拒绝、批准，核对文件状态、宿主结果、精确审批和客户端终态 ACK。结束回收本次后台及宿主进程，保留私有报告，不修改现有平台策略。需要现有模型配置可用；这不是浏览器按钮验收。

**English:** The command uses an owned temporary platform and two fresh Claude sessions. It denies and approves a scoped file-marker probe through real APIs, checking host outcomes, file existence and acknowledged client receipts. It preserves private reports and stops its processes. Existing policies remain unchanged; browser approval controls require separate acceptance.

`experiments/aidr-agentlog/native_claude_acceptance.py` 接受 `--claude` 原生二进制路径、`--settings` 现有私有配置路径、`--server` 隔离后台地址、`--client-id` 和 `--token-file`。可增加 `--platform-fixture` 指向隔离后台私有登录 fixture，完成真实 API 回读；该选项只允许本机 loopback。脚本创建新的 profile、工作目录及接收器状态，读取白名单内的现有模型环境配置，限制为两次测试命令，120 秒到期结束本次宿主进程。报告保留在打印的私有临时目录中；不会打印凭证、原始 Prompt 或工具输出。报告的审计烟测结果不能替代浏览器、审批和系统执行验收。

**English:** The native Claude acceptance script uses a fresh private profile, workspace and receiver state. It reuses only allowlisted provider environment settings, permits the two controlled commands, and bounds the host run to 120 seconds. Optional loopback API verification uses the isolated server's private fixture. Audit smoke results do not establish browser acceptance, approval enforcement or OS attribution.

先在平台允许目标设备上报，使用绑定该设备、具有 `aidr:heartbeat` 与 `aidr:report-events` 权限的凭证。凭证通过既有安全配置注入 `AGENT_MANAGER_AIDR_TOKEN`，不放进插件或命令参数。接收器与 Agent 必须使用同一系统用户。

```sh
# 在 scanner/ 构建；此命令不会安装常驻服务。
go build -o /private/tmp/aidr-client ./cmd/agent-manager-client
mkdir -m 700 "$HOME/.aidr-hooks"
export AIDR_CLIENT_BIN=/private/tmp/aidr-client
export AIDR_HOOK_SOCKET="$HOME/.aidr-hooks/h.sock"
"$AIDR_CLIENT_BIN" aidr-hook-serve \
  --state-dir "$HOME/.aidr-hooks/state" \
  --socket "$AIDR_HOOK_SOCKET" \
  --server https://your-platform.example \
  --client-id your-device-id
```

使用专用私有目录；已有目录先检查所有者和权限，不与 P1/P2 状态目录共享。启动时不会删除已有 socket。正常退出回收本次连接与 socket，待发事件留存。异常退出留下 socket 时，先确认原接收器已退出再人工处理该 socket，不能删除数据库解决启动问题。

另一个继承相同环境变量的终端可执行：

```sh
"$AIDR_CLIENT_BIN" aidr-hook --health
```

目前查询接口为设备作用域 `GET /api/v1/clients/{client_id}/aidr/hooks`，沿用管理登录和设备可见性。设备操作详情已整合关联插件证据，策略与审批中的工具审批与规则提供控制入口。实际宿主安装、启用和信任必须分别确认；本说明不要求更改当前用户会话配置。

## 打包、安装与自检

`aidr-plugin-package` 导出两种原生 marketplace、白名单内的插件文件和 SHA-256 文件清单。目标必须是新目录；它不会覆盖已有分发包，也不会复制用户设置和凭证。

分发包回归在 `scanner/` 执行 `go test -race ./internal/aidr/hooks -run TestPackag -count=1`。测试实际导出文件的摘要，并通过包含空格的路径执行 Claude/Codex 共 28 个声明事件的桥接入口，检查 stdin、参数、退出码和缺少客户端时的 PreToolUse 拒绝。此测试使用临时替身客户端，不等同于 28 种事件已由真实宿主触发。

**English:** Run `go test -race ./internal/aidr/hooks -run TestPackag -count=1` from `scanner/`. It checks exported digests and executes all 28 declared bridge routes through paths containing spaces, verifying stdin, arguments, exit status and PreToolUse denial when the client is missing. The temporary stand-in client checks packaging, not native lifecycle coverage.

```sh
"$AIDR_CLIENT_BIN" aidr-plugin-package \
  --source-dir /absolute/path/to/skill-manager/client/aidr-plugins \
  --destination /absolute/path/to/new-aidr-marketplace
"$AIDR_CLIENT_BIN" aidr-plugin-install \
  --agent codex --host-bin /absolute/path/to/codex \
  --marketplace-path /absolute/path/to/new-aidr-marketplace
"$AIDR_CLIENT_BIN" aidr-plugin-doctor \
  --agent codex --host-bin /absolute/path/to/codex \
  --socket "$AIDR_HOOK_SOCKET"
```

Claude 使用 `--agent claude --host-bin /absolute/path/to/claude`。安装复用宿主 CLI，已安装时保持当前启停状态；读取失败或多来源歧义时拒绝覆盖。安装只对已核对的目标版本开放，未知版本返回 `aidr_plugin_version_unverified`。此状态不表示该宿主版本已通过所有生命周期事件验收。

默认操作当前用户配置；隔离测试通过 `--host-config-dir /absolute/private/test-directory` 指定新的宿主配置目录。该参数仅作用于子进程环境，不修改当前终端环境变量。不要把隔离配置中的安装成功当作日常配置已安装。

自检分别输出宿主版本、安装状态、启用状态、来源读取状态、检查时间和接收器连接状态。Codex 原生列表不提供信任信息，因此 `hook_trust` 保持 `unknown`；到 Codex `/hooks` 审核当前定义后，还须核对实际事件到达。安装命令不会自动授予 Hook 信任。参考 [官方 Hook 信任说明](https://learn.chatgpt.com/docs/hooks)。

**English:** Packaging exports only declared plugin files and their hashes. Installation uses the native host CLI, preserves an existing disabled state and does not grant hook trust. Doctor reports installation, enablement, source readability and receiver health separately. An unreadable source remains unknown rather than becoming “not installed.” Use `--host-config-dir` for an explicitly isolated test profile.

## 数据契约和故障语义

- 桥接器不写入原始 stdin，不执行被采集的命令。接收器按字段白名单投影，在持久化前应用平台脱敏策略。默认开启；未取得策略时保持开启，刷新失败使用绑定同一平台、设备的缓存。
- 平台策略约每 30 秒刷新（请求耗时会延后下一轮）；收到有效凭据后原子记录实际应用序号。改变策略只影响后续新事件，不修改冻结批次。
- 首次事件投递 ID 包含桥接器生成时间及随机量。新投递接受 24 小时窗口、最多 2 分钟未来时钟偏差；已入队事件不按此期限删除。ACK 后保留至少 48 小时接收回执，旧 ID 超出首次接收窗口后不能重建历史投影。回执与待发合计上限 100 万，待发默认 1 万；数据库配置 256 MiB 页数上限。容量或磁盘错误明确拒绝，不隐式丢弃待上传事件。
- 最多 16 个活动 IPC 请求，单条原始事件 256 KiB；每批最多 100 条、记录合计 900,000 字节。内核提供系统用户身份，插件输入不能指定设备、用户或进程归属。
- `aidr_hook_event_conflict`：同一 ID 内容变化；`aidr_hook_event_expired`：新投递超出时间窗口；`aidr_hook_outbox_full` / `aidr_hook_receipt_capacity`：达到容量；`aidr_hook_receiver_busy`：接收预算不足；`aidr_hook_ack_invalid`：ACK 不匹配。宿主错误反馈及平台覆盖展示还需完整 P3 验收。
- Prompt、文件正文和工具输出片段按平台独立范围选项采集，默认关闭，并遵守字节预算与脱敏策略。调用参数 HMAC 仅用于本接收器范围内的确定性比对，不把不同接收器摘要直接作为跨来源关联键。

## 工具审批控制

已实现 P-256 签名的 `aidr.tool-grant/1` 验证与 SQLite 原子核销。授权范围绑定设备、stream、接收器实例、系统用户、Agent、session/turn/call、子代理、工具、完整参数与工作目录的 HMAC、尝试 nonce、规则和策略版本。执行点固定为插件工具预检查；它不授予 OS 文件访问豁免。

授权最长 5 分钟；同一尝试即使收到多个授权也最多核销一次。重复投递或更新版本不恢复已消费授权，已拒绝或撤销的 nonce 不能恢复为允许。接收器重启创建新实例，清理本地授权缓存，使先前实例的授权失效；审计事件、上传游标和待发队列不清空。旧 Hook 记录缺少接收器实例时仍可查询，但不能形成新执行尝试的授权范围。

平台已提供设备作用域工具策略与审批 API：`GET/PUT .../aidr/hook-policy`，设备请求 `POST .../aidr/hook-approvals`，管理列表 `GET .../aidr/hook-approvals`、决策 `POST .../aidr/hook-approvals/{id}/decision`，设备控制下发 `POST .../aidr/hook-control/snapshot`。设备接口沿用 `aidr:report-events` / `aidr:heartbeat`，管理决策沿用设备可见性、管理员角色与 `clients:execute`。审批从已上传的精确 Hook 尝试构造范围，不接收客户端自行扩大的授权范围。

工具规则使用 Agent 和工具原名的精确匹配，`*` 表示该维度全匹配；拒绝优先于审批，审批优先于允许，并保留全部命中规则 ID。没有匹配时使用显式默认行为。策略有签名、版本和期限；配置了可信公钥的内部求值器在缺少/过期策略时拒绝，未配置控制时明确为仅审计。控制下发按接收器实例隔离并分页，响应不超过客户端预算。

启动接收器时增加 `--public-key /absolute/path/to/platform-public.x963` 可开启插件工具控制。公钥为平台 P-256 签名密钥对应的 65 字节 X9.63 公钥，不能从未验证的远程响应自动取信。未指定公钥时保持仅审计；配置后缺少或过期策略会拒绝工具预检查。`aidr-hook --health` 的 `control_mode`、`control_revision`、`control_code` 表示本地实际状态。

控制同步器每轮处理一个有界分页，完成后从头重扫以取得撤销和授权修订；失败不推进游标。待审批先持久化精确范围，再由上传线程提交平台；请求重试轮换，避免单个尚未上传的证据阻塞其他请求。审批等待最多 40 秒，本地尝试最多 45 秒；插件 PreToolUse 的宿主超时为 60 秒。超时/取消拒绝当前尝试，后续重试产生新的尝试；旧授权不能转用于新调用。平台批准与本地单次核销分开，成功核销不代表工具已执行或 OS 操作成功。

已通过真实 Go 桥接器进程、Unix socket、SQLite 与测试 HTTP 后台的批准/拒绝链路：批准输出空对象以保留宿主原权限，拒绝输出 PreToolUse `permissionDecision=deny`；审批中不占用长连接，20 个并发轮询仅一次返回许可。该测试使用合成 Hook 输入；真实 Claude/Codex 批准与拒绝、Claude 网页闭环各有独立报告。Codex 持久宿主信任已验收，剩余 Claude 事件覆盖仍待补齐。Hook 被宿主禁用、未信任或进程被外部终止时的行为由宿主决定，不能宣称覆盖所有执行途径。

**English:** Add `--public-key /absolute/path/to/platform-public.x963` to enable plugin control using a pinned 65-byte P-256 public key. Health reports the actual local mode, revision and readiness. Approval waits up to 40 seconds; local attempts expire after 45 seconds, within the 60-second PreToolUse timeout. Cancellation, expiry, policy changes and receiver restarts invalidate the attempt. Signed grants are consumed atomically once and do not create OS exemptions. Owned Go-process/HTTP tests pass for allow and deny, using synthetic hook input. Native Claude/Codex allow/deny and Claude browser approval have separate evidence. Codex persistent trust and the declared P3 lifecycle/UI exit checks passed; disabled or untrusted hooks cannot provide enforcement.

**English:** Policy refresh is approximately every 30 seconds; a validated policy applies atomically to subsequent intake. Cached policy is used offline, with redaction enabled before first successful contact. Frozen batches remain immutable. Acknowledged retries retain their original receipt and cannot re-project history. Capacity, framing and ACK failures are explicit. OS identity and execution evidence are not inferred from plugin claims.

## 验证

### 按真实试验核对生命周期覆盖

使用 `experiments/aidr-agentlog/native_lifecycle_evidence.py --report <原生审计报告> --database <平台数据库> --output <新的报告路径>`；`--report` 和 `--database` 可重复。工具只读指定数据库，按报告 stream 对照当前插件声明，输出观察次数和未观察事件。它拒绝跨设备歧义、冲突副本、计数不符及重复试验；不读取原始会话正文、不触发宿主。事件出现只证明该次输入到达，不能替代权限控制、全部载荷格式或持久信任验收。

**English:** Run the read-only lifecycle evidence inventory with explicit native audit reports and platform databases. Repeat `--report` or `--database` as needed and choose a new output path. It matches declared hooks by exact run stream, rejects device ambiguity, conflicting copies and count mismatches, and lists unobserved events. It runs no host and reads no transcript; event presence does not establish every payload variant, control behavior or persisted trust.

平台入口：**客户端管理 → 设备详情 → 策略与审批 → 工具审批与规则**。工具策略支持版本检查、默认决定和精确 Agent/工具规则；审批详情读取已保存的脱敏 Hook 投影，批准、拒绝、撤销复用设备可见性和角色权限。详情独立展示客户端终态回执；未收到时保持未知，已收到也只表示客户端报告已核销或拒绝，不证明工具执行成功。

终态通过 `POST .../aidr/hook-attempt-reports` 上传。SQLite 冻结正文及 SHA-256 摘要，按设备/stream/event/digest/durable 校验 ACK；断网或重启不改变冻结字节。未确认回执不因 48 小时保留期到达而删除。平台按原始 Hook 事件与审批身份验证范围，重复上传幂等，内容冲突拒绝；收到客户端终态后拒绝继续审批该尝试，但不改写历史平台决定。回执生成时间是冻结报告的时间，不是工具执行时间；旧客户端没有回执时显示未知。

**English:** Client terminal receipts use a separate durable outbox and exact device/stream/event/digest ACKs. Offline retries and restarts preserve frozen bytes; unacknowledged receipts are retained. The platform checks the original hook and approval identities and rejects conflicting replays or further decisions after a terminal report. Report creation time is not execution time. Missing legacy receipts remain unknown; a consumed receipt is not proof of tool success.

**English:** Open **Client Management → Client details → Plugin tool policy and approvals**. Review the stored hook projection before approving an exact attempt. Policy updates use expected revisions; decisions reuse device access and role permissions. Platform approval is separate from execution evidence.

UI 手验清单：已通过的分支见上方“当前验证范围”。继续检查中英文长命令详情、英文修正确认弹窗、只读账号的带数据审批详情、重复点击、翻页、切换设备后旧响应不覆盖新页面，以及来源漂移、规则解释与关联异常分支。

```sh
# scanner/
go test -race ./internal/aidr/hooks ./internal/aidr/upload ./cmd/agent-manager-client
# 仓库根目录
uv run pytest tests/test_aidr_hooks.py tests/test_aidr_hook_bridge.py -q
```

已验证固定版本的原生安装、重复安装、停用状态和安装包装命令；证据由 `experiments/aidr-agentlog/plugin_acceptance.py --with-client` 在新私有宿主配置中生成。原生审计、控制、共享服务和页面证据分别记录。Codex 持久信任和 12 种声明 Hook 已有实际触发记录；Claude 剩余声明 Hook 的触发条件仍需补验；安装或合成测试不能替代这些项目。

## 插件来源漂移自检

使用同一个明确的宿主二进制和配置目录保存第一次报告，再以 `--previous-report /absolute/before.json` 比较后续报告：

```sh
"$AIDR_CLIENT_BIN" aidr-plugin-doctor --agent codex \
  --host-bin /absolute/path/to/codex \
  --host-config-dir /absolute/private/profile > /absolute/private/before.json
"$AIDR_CLIENT_BIN" aidr-plugin-doctor --agent codex \
  --host-bin /absolute/path/to/codex \
  --host-config-dir /absolute/private/profile \
  --previous-report /absolute/private/before.json
```

基线只读，不在采集失败时自动覆盖。未知报告不能当成卸载，文件不可读不能当成未变化。`configuration_digest` 描述原生列表，`files_digest` 描述产品 manifest、hooks.json、bridge.sh，`files_comparable` 描述两次文件观察是否可比较；这些都不是宿主信任或执行证明。Claude 使用 `native_install_path`，Codex 使用 `declared_local_source`，后者不保证与已加载缓存一致。只有同一设备/用户/宿主配置的报告才有比较意义，路径不输出。自动上报与平台来源面板已接入；来源故障和状态过期的中英文真实页面已有验收记录。

**English:** Save a doctor report, then compare with `--previous-report`. The baseline is read-only. Unreadable sources remain unknown; file read failures preserve installed status. Configuration and bounded product-file digests are evidence of observed changes, not permissions, hook trust or loaded runtime bytes. Compare reports from the same device, user and host configuration. Automatic reporting and the platform source panel are implemented; bilingual source-failure and stale-status browser checks have passed.

## 自动来源报告

`aidr-hook-serve` 默认从 PATH 查找两种宿主；如有多个版本，传入 `--codex-host-bin`、`--claude-host-bin` 的绝对路径。可用 `--codex-config-dir`、`--claude-config-dir` 指向明确的私有配置。每轮检查结束后等待 60 秒；检查在独立工作线程中进行，不阻塞审计 IPC/上传。

平台设备详情 → 插件接入 → 插件来源与漂移证据。来源范围按用户、Agent 和配置目录区分，绑定设备与本地流；安装状态不可读保持未知。报告序号跨接收器重启递增，旧报告不覆盖新报告，最近可读基线不因读取失败丢失。每设备最多 64 个来源，满容量返回 `aidr.plugin_status_capacity`；查询展示最近 20 个并提示截断。180 秒未更新标为过期。采样未覆盖两次检查间的所有变化，不应将接收时间视为修改发生时间。

**English:** The receiver independently inspects native hosts about every 60 seconds. Use explicit host/configuration paths when needed. Source scopes are bound to the device and stream; persistent sequencing survives receiver restart. Unreadable observations preserve the readable baseline. The platform retains up to 64 source scopes per device, shows the latest 20 and marks reports stale after 180 seconds. Snapshots are not a complete change log or proof of permissions.

复验真实原生列表到平台报告（创建独立后台及私有配置，不调用模型）：

```sh
backend/.venv/bin/python experiments/aidr-agentlog/native_plugin_status_acceptance.py \
  --codex /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
  --claude "$HOME/.local/bin/claude"
```

**UI 手验 / Manual checks:** 中英文打开来源面板，核对双宿主、未报告、读取失败、文件缺口、最近变化保留、长摘要换行、JSON 展开、面板关闭；停止受控接收器超过 180 秒后刷新应显示过期。协议上报驱动的真实中英文页面已验证读取失败、文件缺口、基线保留及实际时间过期；原生宿主故障注入不由此推定通过。 Bilingual real pages passed these status branches using protocol reports and elapsed time; this does not constitute native-host fault injection.

原生故障复验：上述命令追加 `--source-failure-probe`。仅在新建私有目录里损坏 Codex 配置、暂时移除 Claude 已安装 Hook 文件，然后恢复；不调用模型，不改变日常配置。固定版本实测 Codex 来源不可读时 installed/enabled 为未知，Claude 文件缺失时保留 installed=true、enabled=false 并报告文件不可读。可读基线保留，恢复后配置/文件摘要一致，报告序号跨接收器重启递增。Claude 设置文件语法损坏并不必然使原生列表失败，不能把该操作本身当成来源不可读证据。

**English:** Add `--source-failure-probe` to test a malformed Codex configuration and a temporarily missing installed Claude hook file in newly owned profiles. No model is called. Codex reports an unreadable source with unknown installation/enabled status; Claude preserves installed/disabled status and reports unreadable files. Readable baselines survive, restored digests match, and sequences advance across receiver restarts. Malformed Claude settings alone did not cause native listing failure in the tested version. These native/API checks complement, rather than replace, the bilingual page checks above.

## 原生生命周期复验

### Claude 原生压缩生命周期

在已启动的隔离验收后台上运行；fixture 与设备凭证路径必须来自该隔离后台。脚本新建私有 profile/workspace，两轮禁用工具的短文本对话后只恢复本次 session 执行 `/compact`；不复用用户会话。最多三次原生 CLI 调用，每次最多两轮，检查真实 PreCompact/PostCompact、同会话和上传确认。平台 API 登录会使同测试账号已有浏览器登录失效，应先运行脚本再做页面验收。

```sh
backend/.venv/bin/python experiments/aidr-agentlog/native_claude_acceptance.py \
  --claude "$HOME/.local/bin/claude" --settings "$HOME/.claude/settings.json" \
  --server http://127.0.0.1:41886 --client-id aidr-p1-acceptance \
  --token-file /absolute/private/platform/device-token \
  --platform-fixture /absolute/private/platform/fixture.json --compact-probe
```

Claude 2.1.220 已实测压缩前后事件各一次、14 条 Hook 全部 ACK、待发为 0。仅一轮种子对话会返回消息不足，该失败试验单独保留。压缩过程出现 SubagentStop 不代表普通子代理完整启停已验收；合并独立原生报告，当前 Claude 16/16、Codex 12/12 种声明事件已观察到；事件出现与具体控制行为分别验收。

**English:** The compaction probe creates an isolated profile and session, performs two short tool-free seed turns, then resumes only that session for `/compact`. It uses at most three native CLI invocations, each bounded to two turns. Claude 2.1.220 produced one PreCompact/PostCompact pair and fourteen acknowledged hooks with no pending records. A SubagentStop observed during compaction does not validate a general subagent lifecycle. Combined independent reports cover all sixteen declared Claude and twelve Codex event types; event presence and control behavior have separate acceptance evidence. Run before browser login because test-account API login invalidates its existing browser session.

### Claude 任务完成生命周期

使用上述 native_claude_acceptance.py 命令，将 `--compact-probe` 替换为 `--task-completion-probe`。一次新的私有会话、最多四轮，仅开放 TaskCreate 和 TaskUpdate；创建标题 AIDR-TASK-PROBE 的合成任务并完成，不调用 shell、不启动子代理。独立检查工具调用/结果 ID、临时任务文件 completed 状态、平台同会话 TaskCompleted 和队列 ACK。

Claude 2.1.220 实测两次工具调用、9 条 Hook（含一个 TaskCompleted）全部确认，待发为 0。任务对象证据来自受控宿主的临时状态；平台事件不能当作 OS 进程执行证明，也不补造缺少的原生任务关联字段。

**English:** Replace `--compact-probe` with `--task-completion-probe` in the command above. A fresh private session permits only TaskCreate/TaskUpdate, uses at most four turns, and creates then completes one synthetic AIDR-TASK-PROBE task. It checks exact tool/result IDs, the owned task file's completed state, the same-session TaskCompleted event and durable acknowledgements. Claude 2.1.220 produced nine acknowledged hooks and no pending records. This does not establish an OS process relation or invent missing task identifiers.

### Claude 空闲通知验证边界

上述命令改用 `--idle-notification-probe`，会新建禁用工具的私有会话，通过 stream-json 输入一条合成消息，在成功结果后保持输入流打开 75 秒，然后关闭并核对平台事件。只调用一次模型，不发送模拟 Hook。Claude 2.1.220 实测会话持续存活 75.097 秒，SessionStart/UserPromptSubmit/Stop/SessionEnd 四条均确认上传，未出现 Notification；该非交互入口未通过空闲通知验收。独立交互终端已观察到 Notification，但投影没有通知子类型；不能把它解释成此无界面入口的空闲通知通过。

**English:** Use `--idle-notification-probe` to create one private tool-free session, send a synthetic stream-json message, keep stdin open for 75 seconds after a successful result, then close it and verify platform events. No synthetic hooks are sent. Claude 2.1.220 stayed alive for 75.097 seconds and acknowledged four lifecycle events, but emitted no Notification. Independent interactive runs observed Notification, but its subtype was not projected. Those events do not establish idle-notification success for this headless probe.

### Codex App Server 生命周期前置检查

`native_codex_lifecycle_acceptance.py` 用官方 thread/compact/start 与 turn/interrupt 接口验证独立会话，原生 hooks/list 必须报告产品的 12 个 Hook 均 enabled/trusted 才会启动模型轮次。CLI 审计试验的单次信任覆盖不能用来推定 App Server 的 Hook 已生效。未信任返回 `native_hook_trust_required`，不自动修改宿主信任。

已有私有验收 profile 完成人工 `/hooks` 审阅并退出 CLI 后，可复验（这里沿用已生成的独立配置，不使用日常 profile）：

```sh
backend/.venv/bin/python experiments/aidr-agentlog/native_codex_lifecycle_acceptance.py \
  --codex /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
  --client /private/tmp/aidr-p3-process-client \
  --profile /private/tmp/aidr-p3-hook-inventory-5rwbse76/home \
  --server http://127.0.0.1:41886 --client-id aidr-p1-acceptance \
  --token-file /absolute/private/platform/device-token \
  --database /absolute/private/platform/platform.db
```

`--profile` 仅接受本项目这两个验收脚本建立的私有配置及其已有报告；省略时建立新配置，但不会代替用户授予信任。试验最多两轮短文本种子、一轮压缩、一轮立即中断的文本请求；禁止工具请求，使用只读沙箱。复制的认证文件在结束时移除，原有认证文件不覆盖；自有原生进程与接收器均回收。用户原生审阅后已通过持久信任、压缩前后与中断实测：十条 Hook 全部确认，待发零。中断请求必须在精确轮次的 turn/started 后发送；仅 turn/start 的响应不能证明轮次已经开始。若登录时使用文件存储，追加 --file-auth 保持同一凭证来源。

**English:** The native App Server probe requires twelve enabled and trusted product hooks before starting model turns. Untrusted inventory stops with `native_hook_trust_required`; it does not grant trust. The CLI smoke test's one-invocation override does not establish App Server hook operation. After reviewing `/hooks` in the owned profile and exiting the CLI, rerun with that profile and the isolated platform paths. The probe uses two text seed turns, compaction and one immediately interrupted text request, rejects tool requests, and reclaims its processes and copied auth file. After native user review, persisted trust and compaction/interrupt hooks passed: ten hooks acknowledged, none pending. Wait for the exact turn/started notification before interrupting. Add --file-auth when the user logged into this profile with the file credential store. Existing auth files are preserved.

## 预检查时延复验

```sh
backend/.venv/bin/python experiments/aidr-agentlog/hook_precheck_latency.py --samples 200
```

脚本创建独占隔离后台、签名密钥、接收器状态；经产品 bridge 发送合成 Hook 输入，核对允许/拒绝，不执行输入命令。记录启动、IPC、持久化及策略判定的 P50/P95/P99/最大值和阶段末 RSS。包含在线允许、在线拒绝、后台关闭后的缓存拒绝；保留待发数据及私有报告，回收本次进程。此测量不包含宿主分发、模型或人工等待，也不能代替真实 Agent/网页验收。

可选 `--client-bin /absolute/path/to/packaged/agent-manager-client` 使用已有随包程序，省略仍按原流程构建。`--burst-size 256 --capacity 400` 增加有界并发IPC、连接预算、明确容量拒绝、同序号重放及冻结字节检查；输入仅为独立合成测试数据。2026-10-01的600次串行样本各组P95为18.11–27.97ms，256条突发接受100条、明确拒绝156条，待发保持400条上限；此结果不是任意负载保证。真实桌面/Codex短时离线补传另有证据，详情及未验项目见已有ACCEPTANCE.md。

**English:** `--client-bin` optionally uses an existing packaged binary. `--burst-size` and `--capacity` exercise bounded synthetic IPC concurrency, explicit capacity/busy responses, replay identity and immutable frozen bytes. These measurements exclude native host dispatch, model execution and approval time. Native offline delivery and bilingual desktop checks are documented separately in the existing acceptance record.

**English:** This owned-environment probe measures shipped bridge startup, IPC, durable admission and cached policy decisions with synthetic input. It never executes input commands. The report retains every sample, percentiles, maxima and receiver memory snapshots. It excludes native host dispatch, model work and human wait.


### 权限请求与普通子代理复验 / Permission and subagent probes

在上方 Codex 原生生命周期命令末尾增加 `--permission-probe`，请求一个仅位于测试目录的标记命令并拒绝原生审批；或增加 `--subagent-probe`，运行一个文字回复子代理。两种模式互斥，不改变持久信任；使用已有登录时保留 `--file-auth`。前者检查精确审批、declined 结果和标记不存在，后者检查同一子代理的启停身份。当前 Codex 12/12 种声明事件已有原生记录。

Claude 受控命令末尾增加 `--subagent-probe --platform-fixture /absolute/path/to/isolated/platform/fixture.json`，创建独立 profile 和单个合成任务，平台回读需在浏览器登录前执行，避免同账号会话失效。明确完成状态、子代理身份、零工具调用和固定回复必须同时匹配；缺少 is_error 不单独视为成功。当前 Claude 16/16 种声明事件已有原生记录；auto 权限拒绝的独立复验方式见下文。

**English:** Add either `--permission-probe` or `--subagent-probe` to the native Codex lifecycle command. These exclusive modes respectively decline one exact owned marker command or run one text-only child; persisted trust is unchanged. Keep `--file-auth` for an existing file-store login. All twelve declared Codex event types have native evidence. For Claude, add `--subagent-probe` and the isolated platform fixture path before browser login. Verify explicit completion, matching child identity, zero child tools and the synthetic reply; an absent error field alone is insufficient. All sixteen declared Claude event types have native evidence; the separate auto-denial probe is described below.

**UI 手验 / Manual UI checks:** 中英文跨设备详情 GET 和决定 POST 的 30 秒延迟已验证。新的 pending 协议请求提交拒绝后切换设备，旧响应未重开详情或覆盖新设备；数据库确认两条原设备精确审批均为 denied / revision 2，另一设备原有操作、日志和系统证据数量不变。Bilingual delayed cross-device GET and decision POST checks passed. Both exact approvals became denied at revision 2; the switched device retained its own data without reopening stale details. These protocol fixtures do not prove native tool execution.


`native_claude_acceptance.py --auto-permission-probe` 新建独立 profile 和私有脚本，仅尝试创建自身工作目录内的标记。通过临时 `--settings` 的 `autoMode.hard_deny` 配置 AIDR Canary Denial 规则，并用同一原生版本的 `auto-mode config` 确认实际加载；不修改用户配置。Claude 2.1.220 实测 auto 模式明确拒绝精确调用，PermissionDenied 一条，6 条 Hook 全部 ACK、待发 0，标记不存在，宿主与接收器退出 0。须独立核对会话、调用 ID、原生日志与平台 stream；这验证原生拒绝事件链路，不评价默认分类器的风险识别质量。

**English:** `--auto-permission-probe` creates an owned script/profile and attempts only an owned marker. Temporary inline settings add the AIDR Canary Denial `autoMode.hard_deny` rule, verified by the same native CLI's `auto-mode config`; user settings are unchanged. Claude 2.1.220 denied the exact call in auto mode and emitted one PermissionDenied. All six hooks were acknowledged, none pending; no marker was created and both processes exited zero. Match the native session/call and platform stream independently. This validates native denial transport, not the default classifier's risk-detection quality.


### Claude 交互式生命周期复验 / Interactive Claude lifecycle checks

`experiments/aidr-agentlog/native_claude_interactive_acceptance.py` 必须由用户在真实终端运行。参数沿用原生验收的 `--claude`、`--client-bin`、`--settings`、`--server`、`--client-id`、`--token-file`，增加 `--mode permission|idle|team`。服务端必须是隔离本机后台。每次新建私有 profile、工作目录和接收器，仅复制允许的模型连接环境变量，不复用用户会话或预置工作区信任；无终端立即拒绝，最长300秒，报告只代表收集、默认 unverified。

- permission：审阅并信任显示的新临时目录，请求一次创建该目录内标记；宿主权限提示出现后等待至少8秒再拒绝，观察权限通知。模型回复结束后保持空闲75秒，输入 `/exit`。
- idle：不开放工具，固定回复后保持空闲75秒，再 `/exit`。
- team：仅在新的交互 profile 启用实验团队，要求一个文字任务队友，观察其空闲及关闭；不把普通子代理代替团队。确认队友已停止后 `/exit`。任何额外工具请求需审查，不扩大权限。

结束保留 report.json、独立原生日志及原接收器数据库。按报告 stream 对照平台事件、原生会话和准确队友身份后才能计入验收；PermissionDenied 的 auto 拒绝条件另验，普通人工拒绝不代替。

**English:** Run the interactive probe in a real user terminal with the existing native-test arguments and `--mode permission`, `idle`, or `team`. Each run owns a new private profile, workspace and receiver; trust is reviewed natively, never prefilled. The 300-second limit bounds the session. Permission mode requests one owned marker creation: wait eight seconds at the prompt and deny it, then leave the completed conversation idle for 75 seconds before `/exit`. Idle mode enables no tools. Team mode requests one text-only teammate and requires its idle/shutdown evidence. Reports remain unverified until native session and exact platform-stream evidence are independently matched. Manual denial does not prove the auto-only PermissionDenied event.


交互补验：用户运行独立permission入口，原生日志与平台精确stream确认PermissionRequest一次、Notification两次；通知子类型未在当前投影中保存，保持未知。该次交互报告证明权限请求与通知事件，auto 拒绝另有独立报告。命令实际被允许，不能算拒绝通过；宿主达到300秒上限，原报告保持超时。最后一条SessionEnd通过原状态补传，9条全部ACK、待发0，未删除状态或重写历史。验收启动器已调整为先结束原生宿主、再排空最终事件、最后停止接收器。详见主仓库ACCEPTANCE.md。

**English:** The user-operated permission probe produced one PermissionRequest and two Notification events, independently matched to its native session and platform stream. Notification subtypes remain unknown because they were not projected. Auto-only PermissionDenied has a separate native report. The command was allowed and the session hit its 300-second limit. Its final SessionEnd was recovered from the original queue: nine acknowledged, zero pending. The launcher now drains after native shutdown before stopping the receiver; the original timeout report is retained.


团队验收使用 `Agent.model=sonnet` 这一合法别名；在本次独立环境内将 `ANTHROPIC_DEFAULT_SONNET_MODEL` 与 `CLAUDE_CODE_SUBAGENT_MODEL` 映射到私有 `ANTHROPIC_MODEL`。`--team-model` 指定的是映射目标模型，不直接传入 Agent 的闭集参数。不修改用户配置或凭证权限。报告的 `requested_team_model` 只是目标，必须对照原生 Agent spawn 的实际模型与完成结果。队友收到403属于失败，不能将错误后的空闲消息算作成功的TeammateIdle验收。team模式完成并关闭唯一队友后输入 `/exit`，失败也退出，不创建替代队友；不需要权限模式的75秒等待。

**English:** Team acceptance passes the supported `Agent.model=sonnet` alias. The isolated environment maps it through `ANTHROPIC_DEFAULT_SONNET_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` to the private `ANTHROPIC_MODEL` value or explicit `--team-model` target; full provider IDs are not passed to the Agent enum. It does not guess accessible models or change credentials. `requested_team_model` is a target; verify the actual spawn model and completion independently. A 403 and subsequent failure-idle message do not pass TeammateIdle acceptance. After the sole teammate shuts down, use `/exit`; exit on failure without spawning a replacement. The permission probe's 75-second wait does not apply to team mode.


团队空闲验收已通过独立日志与平台核对：唯一队友实际模型正确，回复AIDR-TEAM-DONE，平台TeammateIdle一条，关闭请求与确认匹配，17条全部ACK、待发0。同一子身份在回复和关闭确认阶段各有启停，不代表两个队友；任务回复无工具调用，关闭时仅使用SendMessage确认。主终端达到300秒上限的退出143保留，不声称正常退出。TeammateIdle投影未提供native_agent_id，按精确会话和独立的唯一队友记录解释，不补造字段。当前 Claude 16/16 种声明事件已有独立原生证据；详见 ACCEPTANCE.md。

**English:** Native teammate-idle acceptance now has an exact reply, one platform TeammateIdle event, and a matching shutdown request/acknowledgment. All 17 events were acknowledged. The same child identity handled the reply and shutdown confirmation; it was not two teammates. Host timeout/exit 143 is retained. The idle projection lacks a native agent ID, so exact session evidence and the single native teammate remain distinct. Auto-only PermissionDenied has a separate native report.

## 插件接入与采集页面

桌面侧边栏 **Agent 运行治理 → 插件接入与采集** 首先展示本地接收器、平台传输、待发记录和最近事件上传确认。Claude/Codex 各自的卡片显示实际版本、兼容性、安装、启用、原生信任和检查时间，接入/更新操作位于对应宿主卡片内。未连接设备时使用“前往客户端概览”完成现有认证；平台管理的安装和启停仍在平台执行。路径与来源、采集范围、策略应用、重试及状态报告时间可展开查看。状态报告成功与事件 ACK 分开，缺失信息保持未知。

平台 **客户端管理 → 设备详情** 使用五个标签：**概览、Agent 与 Skill、插件接入、行为审计、策略与审批**。概览只显示可跳转摘要、各自报告时间及最近需关注任务；待审批数字仅统计最近读取的最多50条申请，不是全量计数。Agent与Skill集中库存、模型配置、治理、恢复副本及相关任务/记录，其他标签不重复显示。

插件接入展示Claude/Codex的版本、安装/启用/信任、接入方式和安装/更新/自检；来源漂移按需展开，接入任务保留独立回执。接收器、上传及覆盖诊断统一通过“采集状态”跳转查看。配置接入策略链接到策略与审批的唯一客户端策略入口。

行为审计使用工具操作、生命周期与Hook、系统事件、采集状态四个视图。日志调用/结果仍按可靠身份合并，Hook原生事件独立分页，系统证据不由日志替代；日志空列表提供Hook入口。采集状态分别展示Hook接收器与日志读取器，各自保留报告时间、未知值、脱敏/范围、ACK和覆盖原因。来源覆盖明细与来源报告展开时读取，不默认请求全部诊断。

策略与审批先展示工具审批申请，再展开工具规则/漂移分析；系统策略、历史与响应回执使用独立视图。进程终止仍在系统事件行，保持完整身份、执行器/monitor新鲜度及服务端独立校验。客户端分类/安装目标等既有配置通过此标签的客户端策略入口编辑；Skill治理方式仍在Agent与Skill中操作。

非活动标签及审计/策略视图卸载组件，清理其计时器；返回重新读取，未提交筛选和展开状态可能重置。概览无定时轮询，插件页只按需刷新；系统事件视图不读取策略/历史/回执，系统策略视图不读取完整事件列表。读取失败持续提示，不作为空配置；已有日志快照保留并明确可能过时。正文、设备可见性和操作权限沿用既有接口，不更改采集、身份、队列或ACK协议。

**English:** Device details provide Overview, Agents and Skills, Plugin access, Behavior audit, and Policies and approvals. Inventory/model/Skill actions and records belong to Agents and Skills; host installation/trust/actions and access receipts belong to Plugin access. Behavior audit separates log operations, native lifecycle/Hooks, system events, and collection status. Collection diagnostics distinguish Hook intake from log reading, including separate report times, unknowns and coverage. Approvals/rules and system policies/responses live under Policies and approvals; exact-process termination remains in system event rows. The overview fetches bounded summaries once; detailed diagnostics load when expanded, and inactive views dispose their timers. Existing access/content permissions and all evidence/ACK contracts remain unchanged.


新版五标签的实测范围与人工清单见 experiments/aidr-agentlog/ACCEPTANCE.md 最新设备详情记录；此前桌面900宽证据继续保留，平台布局验收分别记录。
