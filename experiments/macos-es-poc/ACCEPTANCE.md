# macOS ES PoC 独立验收记录

## 2026-10-06：桌面授权后的系统模式连续切换

真实设备 `amc_911abfcfe720cc52f3c4ffe6`，现有本地平台 `127.0.0.1:8001` 与管理台 `localhost:5173`。用户完成管理员授权后，新组件建立真实 ES 订阅；桌面 UID 501，独立采集管理进程 UID 0。已安装原生组件为 ad-hoc 签名，包含 `com.apple.developer.endpoint-security.client=true`。

临时策略仅增加专用探针与其测试文件拒绝规则，签名规则版本 6 在两轮模式切换中保持不变。通过现有策略预览、版本校验及保存流程更改运行模式，客户端通过现有认证链路读取策略、上传记录。

| 阶段 | 探针 PID | 实际读取结果 | 平台证据 |
| --- | --- | --- | --- |
| 初始仅审计 | 84487 | 成功，退出 0 | exec、exit，无文件授权记录 |
| 单机覆盖为拦截 | 84770 | EPERM，退出 1 | exec、deny/responded、exit |
| 恢复全局仅审计继承 | 85154 | 成功，退出 0 | exec、exit，无文件授权记录 |
| 再次单机拦截 | 85733 | EPERM，退出 1 | exec、deny/responded、exit |
| 再次恢复继承 | 86224 | 成功，退出 0 | exec、exit，无文件授权记录 |

平台真实页面核对 07:35:29、07:35:50 两条拒绝记录，以及恢复后的采集状态。原 root 管理进程 78376 在模式切换后仍存活，原生订阅进程随模式重建。恢复全局原未配置状态、单机原运行配置和原 Agent 归属/规则后，运行策略版本为 `10:17`、签名系统策略版本为 7；三个通道均确认当前运行策略已应用。系统保持原先的仅审计运行状态，待上传 0，原采集范围及脱敏设置保持。

本轮复验覆盖两项实测修复：同一签名信封经过 JSON 重排不再误判版本冲突；旧策略 `modes:null` 与类型序列化省略空值不再导致协调任务误报已过期。相同版本但签名内容变化仍拒绝，真正不同模式仍视为不同目标。Go enforcement/客户端 race、managedclient 串行全包回归及原生测试通过；未新增 UI 单元测试。

证据保留于 `/tmp/aidr-mode-acceptance/`：`live-run.log`、五组 `live-*-open*.json`、`live-final-runtime.json`、`live-final-system.json`、`live-roundtrip-platform.png`。此前失败证据在 `pre-envelope-fix/`。探针仅用于受控系统测试，不是原生 Agent 工具调用；不将此结果扩展为真实宿主 Hook 拦截/审批验收。真实 FDA 拒绝、正式 Developer ID/Apple ES 授权与公证环境仍待验。

**English:** Two live system-mode round trips passed after user authorization. Three audit reads succeeded; two intercept reads returned EPERM. Every probe's exec/exit and both denials were uploaded and visible in the platform. Original policies and audit collection state were restored. The desktop stayed unprivileged. This run validates the development environment and the envelope-format/legacy-null fixes, not native-host Hook approval, actual FDA denial or production distribution.

## 2026-09-27：P2 网页与原生联合补验

本轮真实浏览器使用 41879 隔离后台及原有测试账号，未重启后台、提升权限或改动脱敏开关。新增有界交互工具 `run_p2_browser.py`，只创建临时合成文件、专用签名探针和 sleep，最长 15 分钟；代理可单独暂停命令 GET，健康及审计上传继续使用真实接口。

- 发现并修复终止确认框每 5 秒随刷新销毁的问题：`loading` 不再被当成执行器失效；仍校验报告时效、有效时间、boot/monitor、精确实例及服务端可操作性。真实确认框跨刷新保留后提交成功。
- 网页发布版本 20 → 执行器报告 20 → 保护读取 EPERM；网页撤销版本 21 → 报告 21 → 同文件读取成功；网页载入历史 20 并发布 22 → 报告 22 → 读取再次 EPERM。允许文件及独立普通用户读取全程成功。长路径 237 字节，未使用业务文件。
- 网页核对 PID 90083 / pidversion 7164438 / start_us 1790473550410459 后精确终止，原生 ES 匹配退出，回执 `8f2e5b08-eeb1-4021-8895-449cf03d1d63` 为 verified，独立 wait 为 -15。
- 暂停命令下发后，对 PID 97546 创建 `005ed8db-0c95-4c51-96c2-685e0f63fa23`。超过 120 秒后，中英文真实页面分别显示“有效期已结束，未确认执行”及 “Validity ended; execution unconfirmed”；历史 verified 不变。恢复命令通道后该 sleep 仍存活，最终只由测试清理回收。
- 对确认属于本轮 supervisor 的原生子进程执行 SIGKILL，中英文页面均显示异常退出及 `aidr_enforcement_native_exit`，历史进程终止入口禁用。脚本因预期故障退出 1，finally 回收自有子进程；该退出码不是整套脚本成功。独立 ps 确认 supervisor、原生父子及两个 sleep 均无残留。
- 英文真实进程分页从 09:50 最近记录进入 06:40 历史记录，再返回最近页；完整身份详情打开/关闭通过。两编辑窗口先后发布触发 `aidr.enforcement_revision_conflict`，旧窗口未覆盖新版本。
- 本轮前版本 18 的规则、根路径及动作已通过正常网页历史发布恢复为版本 24，有效期 3,600 秒；执行器已退出，未声称应用版本 24。只读数据库比较确认原策略内容相同，P1 逻辑操作仍为 11 条。未重置数据库、队列或历史。

证据：`/private/tmp/aidr-p2-browser.n9nhv95s/report.json`；截图及恢复核对位于 `/private/tmp/aidr-p1p2-20260927/p2-browser/`。本轮 Go AIDR/客户端回归、7 项 Python enforcement 回归、现有 i18n 门禁及 22 项检查、Vite 构建通过；仅既有弃用及大 chunk 警告。未新增 UI 单元测试。

剩余条件：真实 Claude 模型此前无法完成调用；本机 Claude 插件清单为空，现有 Codex 文档/浏览器插件不是已接入的治理插件，不能冒充治理插件开关对照。仍需真实治理插件开启对照、Claude 保护读取、人工 Terminal 对照、正式签名及 SIP 开启测试机。默认客户端策略的 super_admin 页面编辑属于另一个待验权限项。上述补验不代表整个 P1/P2 出口通过。下文较早记录保留其当时范围，本节为最新进度。

## 2026-09-27：P2 实现与验收进度

状态：P2 核心实现及原生/平台接口链路已完成本轮受控实测，真实 Agent 与网页验收仍有待验项，不能视为整个 P2 出口通过。新执行器位于 `client/macos-enforcer/`，独立于正在运行的只读观察服务；平台签名控制接口、Go 持久化转发及双语页面已接入。

- 身份状态机及签名策略 Go/C 自动回归通过：精确实例、父退出、PID 重用、容量上限、签名和设备边界、版本冲突。
- `/private/tmp/aidr-p2-native.qc11i4in/report.json`：真实 ES 确认 1,000 个并发短命子进程的 fork/exec/exit，每个子进程归属根一致，父退出后后代继续被识别；无观测到的序列/审计缺口。
- 100 次受保护文件读取拒绝、100 次允许文件读取成功，硬链接和符号链接拒绝，非目标 cat 成功；无效签名及旧版本拒绝，撤销及新版本回滚成功。107 条授权记录的 P95=8µs、P99=9µs、最大=11µs，均在 deadline 前响应。
- 受控启动 `/bin/sleep`：错误 pidversion 被拒绝且目标仍存活；准确 audit token 的 SIGTERM 成功并由 ES exit 核实；重复命令没有再次发送信号。停止传感器后测试文件可读。
- 保留失败：首次输出未添加 JSONL 换行，等待首条健康事件超时，已修复；复制系统 sleep 作为直接根的测试没有取得匹配证据，不能宣称该方式通过。后续改用已签名的受控入口 exec 原始 `/bin/sleep`，验证继承身份和终止；根身份不匹配现在产生明确诊断。签名检查、进程归属与新策略范围保持独立。
- 本轮环境仍为 SIP 关闭、root、ad-hoc ES entitlement。未安装常驻服务、未修改其他观察进程；正式签名分发、SIP 开启和完整平台/网页闭环仍待对应验收。

新增实测：

- `/private/tmp/aidr-p2-platform.sbifl3ba/report.json`：隔离后台 `127.0.0.1:41879` 签名策略 → root Go supervisor → ES 真实拒绝 → SQLite/冻结批次 → 平台 ACK 与查询通过。平台对受控 sleep 发起精确实例终止，重复请求幂等，独立 wait 得到 SIGTERM，ES exit 回执为 verified。断网重启后缓存继续拒绝，6 条待发记录恢复补传；新 monitor 身份可见；发布空规则后文件可读。自有 supervisor/原生进程回收，管理员原采集服务未动。
- `/private/tmp/aidr-p2-native.m7dg2756/report.json`：补测根选择器重新排序保留运行中后代归属、策略过期按配置拒绝、读取端暂停超过 1,024 条队列预算。正常阶段 107 条授权 P95=8µs/P99=9µs/最大=9µs；过载阶段另生成 1,000 个子进程，授权继续响应，恢复后明确报告 1,706 条审计缺口，RSS 实测 26,592 KiB。过载属于明确降级通过，不是无丢失通过。
- 代码审查发现审计队列统计也会推进内部缓冲，已与 enqueue 使用同一锁；上述新原生实测包含此修复。原生响应先于审计序列化。
- Go AIDR 包及客户端测试、4 项 P2 Python 回归、前端现有 i18n 检查和生产构建通过。其余完整回归将在收尾时补记。
- `/private/tmp/aidr-p2-native.sf5p1_kj/report.json`：定位并修复 universal 映像的默认静态切片与实际运行切片摘要不一致问题，复制系统 sleep 的直接根识别通过；再次执行全套原生用例，正常授权 P95=9µs/P99=11µs/最大=12µs，故意暂停消费后 1,707 条审计缺口、RSS 27,712 KiB。该结果替代此前复制系统 sleep 未通过的兼容性结论。
- 31 项 AIDR Python 回归、Go enforcement/upload 的 race 检查及现有 i18n/生产构建通过；包括错误 ACK/设备/条数/持久化标志、认证失败与服务不可用时冻结正文保留及相同字节重试。未增加 UI 单元测试。
- `/private/tmp/aidr-p2-codex-native.dc0t_yxw/report.json`：真实 Codex 0.158.0-alpha.2.1、普通用户工作目录 `/private/tmp/aidr-p2-codex-work.ox53jxw0`、不加载插件，只有一次 shell 工具调用运行独立计数脚本。100 次保护文件读取全部 PermissionError，100 次允许文件读取成功；100 条 ES deny 均为同一 Codex 根实例后代，无观测缺口，Agent 退出 0。测试前和停止执行器后，以同一普通用户读取保护文件成功，排除普通文件权限造成拒绝。原始日志只有一个 custom_tool_call 和匹配结果，模型传输重试单独保留，不当成额外操作。
- 首次真实 Agent 测试登记了 Codex 的 shell 包装器，策略明确返回 root_invalid，没有调用模型；核对启动器后改为实际签名映像 `CodexCLI.app/Contents/MacOS/codex`。这是使用路径修正，没有放宽代码身份校验。
- 最终原生回归 `/private/tmp/aidr-p2-native.aen4e5le/report.json` 包含相同命令 UUID 更换目标被拒绝：P95=8µs/P99=8µs/最大=11µs，过载缺口 1,707、RSS 27,584 KiB。最终平台回归 `/private/tmp/aidr-p2-platform.0_xw2958/report.json` 包含自有原生进程 SIGKILL、supervisor 明确失败并上传 native_exit、平台 failed、显式重启恢复缓存控制。正常停止回收、6 条离线积压补传仍通过。
- 同一 P1 状态目录的原写入者已退出后，以自动发现重新采集该次 Codex 会话，平台得到一个合并操作、reported_success、明确退出码 0；日志证据与上述 ES 证据分别保留，未声称实现 P3 强关联。
- 权限映射补强后，5 项 P2 后端测试与 32 项现有 IAM 测试共 37 项通过；策略发布映射 clients:update、终止映射 clients:execute，并继续要求管理员角色及设备可见性。最终中英文 i18n 门禁/既有测试、Vite 构建、Python 语法和两仓库 diff --check 通过；构建仍有既有大 chunk 提示。

后续复核仍需覆盖：真实 Claude 保护读取、插件开启对照、正式分发条件、原生异常退出的真实页面降级、中英文策略发布/历史载入/分页/详情和响应回执。平台 API 成功不替代网页验收。

### 补充并发与未知身份验收

`/private/tmp/aidr-p2-native.kzzyajdy/report.json`：保留此前完整用例，另以 16 个并发工作线程执行 100 次保护读取和 100 次允许读取，分别全部拒绝/成功。显式切换 `unknown_actor_action=deny` 后，未登记的独立 cat 被拒绝，授权证据仍保持 unknown，不推测 Agent 归属。正常阶段 207 条授权响应 P95=9µs、P99=10µs、最大=12µs；独立过载阶段报告 1,706 条审计缺口，RSS 27,920 KiB。传感器回收后保护文件可读，Python 语法及 diff --check 通过。

该脚本的独立 cat 是进程隔离对照，不等同于用户在 Terminal 窗口中的人工交互录像；完整网页流程录像及人工终端对照仍保留待验，不用脚本结果替代。

### 剩余实机条件核实

独立 Terminal 窗口验收尝试被计算机控制工具禁止（`com.apple.Terminal`），没有打开新窗口或操作用户原有终端，也没有改用其他 UI 自动化绕过。该项需要人工完成。隔离后台 ready 检查通过，真实浏览器仍在 `127.0.0.1:41879/login`，本轮网页交互未完成，不计通过。Claude 最后一次独立重试报告为 124、零工具调用；恢复可用模型后再继续真实任务。插件开启对照及正式签名/SIP 开启条件仍未验证。

用户随后确认：可自主完成的验证继续执行，剩余项目交给用户手验。本轮补跑 Go AIDR 全部包及客户端测试、32 项 Python AIDR 测试、原生身份测试与编译均通过；前端 i18n 门禁和既有 22 项测试、Vite 生产构建及项目/Wiki 的 diff --check 通过。仅有既有依赖弃用及大 chunk 警告。隔离后台仍 ready。代码、原状态和已有证据保留，不提交推送部署。可复制复跑命令、中英文页面逐项预期及清理边界见 [执行器 README 的本机验收交接](../../client/macos-enforcer/README.md#本机验收交接2026-09-27)。本次交接不把尚未手验项目记为通过，也不宣称整个 P1/P2 出口通过。

## 历史基础 PoC

本页记录基础 PoC 里程碑；后续真实客户端结果见 [真实 Agent 归因验收](AGENT_ACCEPTANCE.md)。

日期：2026-09-22。实现由 GPT-5.6 Sol 子代理完成；主代理审查、要求修正并独立运行验收。

## 结论

**本机受限 PoC 实机验收通过。** 范围为 SIP 关闭、root 运行、带 ES entitlement 的 ad-hoc 签名开发程序。该结果证明本机能创建 ES 客户端、订阅生命周期并通过 AUTH_OPEN 拒绝指定测试进程对单个合成文件的打开；正式签名分发、SIP 开启、真实 Agent 集成与网络控制尚未验收。

## 实际环境与执行

- macOS 27.0，arm64；Command Line Tools SDK 27.0。
- `csrutil status`：disabled。
- 普通用户 UID 501 构建，用户授权后在交互终端通过 sudo 运行测试。凭据未写入任何项目文件。
- 使用 `libEndpointSecurity`，不需要以“缺少 EndpointSecurity.framework”为由等待完整 Xcode。
- 签名包含 `com.apple.developer.endpoint-security.client`；本次 es_new_client 成功，说明本次运行所需权限满足，未修改 TCC 或系统安全设置。

执行命令（实验目录内）：

```sh
make clean adhoc-sign
codesign --verify --strict --verbose=2 build/es-monitor
codesign --verify --strict --verbose=2 build/file-probe
/usr/bin/python3 -B -m unittest -v test_validate_evidence.py
zsh -n run-test.sh
sudo ./run-test.sh
```

## 结果

| 验收项 | 实际结果 |
| --- | --- |
| 编译与签名 | 两个二进制通过；编译启用 Wall/Wextra/Werror |
| 验收器合成证据测试 | 5/5 通过；拒绝错误 PID、实例、响应和 deadline 证据 |
| 非特权负向探针 | es_new_client 返回 NOT_PRIVILEGED (5)，程序退出码 77 |
| ES 创建和订阅 | 成功；随后收到目标生命周期与 AUTH_OPEN |
| 目标实例 | PID 61341；fork、exec、exit 各 1 条，父进程和执行实例校验通过 |
| 保护文件 | 100/100 返回拒绝；errno=EPERM；无意外成功 |
| 允许文件 | 100/100 成功 |
| 非目标进程 | cat 读取同一保护文件成功 |
| 退出恢复 | 监控退出后，新 file-probe 实例读取保护文件成功 |
| 授权响应 | 100 条拒绝响应成功、cache=false、deadline 剩余 ticks 均大于 0 |
| 本地日志 | response_errors=0、dropped_logs=0、log_drain=complete |
| 清理 | 合成文件和 ready/bound 标记均删除；无 es-monitor 残留进程；证据目录归 UID 501 |

原始证据保存在本目录下 `evidence/2026-09-22-parent-acceptance/`（Git 忽略），含事件、探针结果、monitor 汇总及源码/二进制 SHA-256。父代理已独立解析证据并核对清理，未仅采用子代理总结。

## 实现边界

- 仅单个串行测试进程和固定保护文件；目标身份以 exec 后的 PID + PID version 绑定。并发多 Agent、重启跨 boot 的身份管理属于后续产品实现。
- AUTH_OPEN 回调先响应，日志队列容量 1024，退出排空最多等待 2 秒；本次没有日志丢弃。未进行压力和长期运行测试。
- 生命周期在阻断模式中实测通过；纯观察模式可用入口已实现，其独立特权运行尚未单独验收。
- 测试的阻断对象也是 root 启动的专用探针；普通用户真实 Claude Code/Codex 进程归因与阻断需下一阶段验证。
- 未安装系统扩展、daemon、网络过滤或持久化策略。未修改产品代码，未提交、推送或部署。

## 2026-09-27：网页问题针对性修复

四项确认原因：隔离启动壳未注册外部网关路由，前端 Promise.all 将选项失败扩大为整个策略加载失败；历史进程按钮没有使用当前执行器健康和 monitor，服务端也缺少该前置校验；回执把 expired 无条件叠加到 verified；P1 心跳把持久化来源覆盖状态混作当前解析器支持。

修改：隔离壳注册生产 external_ai_gateways、agents、llm_gateway.admin 路由，保留原数据库和签名密钥；弹窗分别处理策略/选项失败，持续双语错误与重试，选项失败暂停编辑保存；终止前后端共用当前状态语义，服务端按完整实例和来源序号检查最新证据；回执有效期与执行结果分开；心跳新增可选 parser_status/parser_version，旧客户端未知，原覆盖状态保留。设备详情入口补充 Enter/Space 键盘操作。

自动化：Go AIDR/客户端全包、Python AIDR 34 项及默认治理权限回归 1 项通过；现有 i18n 门禁与 22 项测试、前端构建、Python 编译通过。默认策略回归分别验证 super_admin 可预览保存、admin 可读不可写，未提升隔离账号角色。未新增 UI 单元测试。

真实数据：原 22 条日志事件、11 条合并操作逐行摘要不变。新版采集器以原私有状态有界运行 4 秒，增加 1 条覆盖记录和对应批次；历史批次/覆盖前缀逐行摘要不变，aidr_log_version_unverified 仍保留。新心跳同时报告 Codex parser_status=available、来源 status=unavailable，未用成功操作反填覆盖完整。

真实浏览器与剩余手验结果在本节后续条目记录；接口和原生结果不代替网页交互。

本轮真实链路：`/private/tmp/aidr-p2-platform.4d5mjwht/report.json` 的 8 项检查通过，受控 sleep 完整身份 SIGTERM→匹配 exit verified、离线重启 6 条补传、撤销/恢复、原生异常退出均通过。另用停止状态下的真实历史实例调用 terminate 返回 409 / aidr.enforcement_executor_inactive；进程列表 50 条均不可终止。服务端退出判断增加来源序号排序，测试覆盖 exit 后迟到的更低序号 exec。

浏览器实测（同一 loopback 平台，普通 admin，不修改角色）：

- 中文/英文平台默认策略、设备策略正常显示；默认策略只读，设备保持原客户端版本限制及继承值。
- 用隔离启动壳可选 `--fault-marker` 注入指定 GET 路由 503：网关失败保持策略可见且编辑/保存禁用；默认及设备策略读取失败显示独立持续错误与重试；移除标记后点击重试恢复。未使用固定成功数据。标记已移除。
- 中文/英文实际进程列表中 stopped 状态的历史 exec/exit 终止按钮禁用，原因可见；证据详情保留完整身份及长路径，弹窗可关闭。
- 中文/英文六条真实历史回执均显示退出已验证，没有追加过期失败暗示；命令 expires_at/expired 保留在详情。
- 中文/英文 Codex 0.158.0-alpha.2.1 解析器报告为可用、时间为最后心跳、设备离线；来源诊断仍显示历史 aidr_log_version_unverified。11 条操作和退出码 0/7 仍可见。
- 截图保存在 `/private/tmp/aidr-p1p2-20260927/web-fix/`：default-zh、gateway-error-zh/en、device-policy-zh/en、process-detail-en、receipts-zh/en、capability-zh。

进程与配置：仅重启本任务的隔离后台，保留 platform.db、私有 fixture 及签名密钥；只对本轮独立合成文件/进程运行保护测试。P2 测试策略原内容已作为新签名版本 18 恢复，版本/时间不回退；当前执行器已停止，报告版本 17 与目标 18 的差异如实显示。默认客户端策略、设备治理策略、真实脱敏开关和账号角色未改。接口测试和网页测试分时进行，避免同一账号登录踢出浏览器。所有本轮临时原生执行器/代理已回收，后台留供复验。

仍未验（不能用上述测试替代）：super_admin 真实页面编辑；运行中 sleep 的网页终止确认及实时 verified 更新；queued/dispatched 未确认超时的真实页面（自动回归已覆盖）；大于当前样例的超长路径及完整分页交互。这些不影响记录本轮已有证据，也不代表整体 P1/P2 完成。

人工复验：打开 `http://127.0.0.1:41879/clients`，使用本机私有 fixture 账号，验证码 aidr，不在截图中暴露密码。依次打开“平台默认客户端策略”和 AIDR P1 acceptance →“客户端策略”；查看“Agent 日志观察”的解析器报告与“来源覆盖与采集诊断”；系统防护选择“进程”，确认 stopped 历史行禁用，再展开“响应回执”。用页面语言选择重复英文检查。需要故障复验时，在启动参数指定的私有 `web-fault-route` 文件写入 `/api/v1/external-ai-gateways` 或 `/api/v1/clients/aidr-p1-acceptance/governance`，重新打开弹窗；清空文件内容后点重试。该故障入口只存在隔离验收脚本。实时终止复验须另行启动受控执行器和自己的 sleep，核对 boot/monitor/PID/version/start 全部字段，不选择业务进程。
