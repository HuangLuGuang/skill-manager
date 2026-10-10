# 桌面运行时归属视图：实现与验收状态

日期：2026-09-23。

当前结论：已修复 macOS 输出背压导致的记录截断，并完成真实 GUI 连续 10 分钟前台、5 分钟后台复测，未再出现原错误。另行暂停开发客户端 36 秒时，窗口正确显示具体背压超时、覆盖降级并清空归属。旁路额外状态记录未完整留存，因此不宣称整段链路零丢失；详见文末本轮数据和验收边界。未提交、未推送。

## 已实现

- 新增“运行时归属”页面，通过普通权限客户端连接管理员部署的 macOS relay。
- 传输、采集心跳、事件覆盖独立展示；原始证据可展开，状态与错误使用稳定编码及中英文资源。
- 进程以 PID、PID version、start time 组成身份，分别呈现 ES 确认根、确认后代和未知归属；当前订阅没有完整历史或快照候选身份名单，页面不伪造完整进程树。
- 每次连接 reset、会话变化和 coverage epoch 变化清除旧归属；心跳失联也清空当前进程展示。
- Rust 读流线程收到完整记录后立即聚合状态，不再等待页面排空事件队列。输入帧上限 128 KiB，超长或不完整记录使观察停止。
- 页面每秒单次读取完整快照，无重叠请求；原生进程状态上限 500 条、序列化内容 4 MiB，原始证据上限 200 条/1 MiB（UTF-8 字节）。这些是逻辑数据上限，实际 RSS 还包含对象、索引和快照副本。
- 展示历史淘汰仅累计 `history_evicted`，不影响归属；状态容量触顶清空旧状态，累计 `state_overflows` 并持续显示 `runtime_state_capacity`。`sensor_coverage` 与 `client_gap` 独立，健康心跳不能消除客户端缺口。
- uint64 在 Rust 中保持整数；快照以 JSON 字符串传过 IPC，页面在解析前保留大整数为字符串，原始证据不重新序列化。
- 页面离开、取消、窗口关闭和应用退出回收本次 watch 进程。不会停止管理员 relay，也不会启动 root 服务。

## 已完成的验证

| 项目 | 结果 |
| --- | --- |
| JavaScript 语法 | app.js、i18n.js、runtime-observation.js 通过 |
| 既有 `npm run test:i18n` | 29/29 通过；未新增 UI 单元测试 |
| `cargo check --offline` | macOS 本机通过 |
| `cargo build --offline` | macOS debug 二进制构建通过 |
| Rust 原生状态与桥接测试 | 10/10 通过，包含显式启用的受控持续流及真实 Go 离线测试 |
| Go | `go test ./internal/runtimeobservation ./cmd/agent-manager-client` 通过 |
| 实际 Go 客户端接入桥接 | 使用已构建的 agent-manager-client，连接不存在的 socket，验证 offline/reset 输出、停止及进程回收 |
| 差异空白检查 | `git diff --check` 通过 |

Rust 测试覆盖突发输入、暂停页面读取、历史字节上限、真实状态过载、PID 重用及过期 EXIT、EXEC 身份迁移、会话/epoch/健康变化、大整数原文保持、超长/无换行帧拒绝、受控进程取消回收、真实 Go 客户端离线状态。追加验证了停止后重启，以及窗口关闭/退出共用的原生 shutdown 路径；9 项短测试复跑通过，持续流结果单独保留。原生生命周期测试不代替 GUI 切页和窗口关闭测试。

复验桥接测试：

```sh
cd client/desktop/src-tauri
AGENT_MANAGER_CLIENT_BINARY=/absolute/path/to/agent-manager-client \
  cargo test --offline runtime_watch:: -- --include-ignored --test-threads=1 --nocapture
```

此前独立 CLI 的真实 ES 连接验收见 [RUNTIME_CONNECTION_ACCEPTANCE.md](RUNTIME_CONNECTION_ACCEPTANCE.md)。该结果不等于本次新增 GUI 已通过真实 ES 到页面的端到端验收。

## 待手验 Todo

受影响 UI：侧边栏新增入口、套接字连接表单、健康卡片、当前进程列表、原始证据列表，以及离开页面/关闭窗口行为。

- [ ] 中文、英文分别检查 1080×720、900×620 窗口，包含长路径、长错误说明和原始 JSON；确认没有按钮、卡片或列表溢出。
- [ ] 连接管理员部署的真实 relay，确认真实探针的根/后代、PID version 和启动时间与原始证据一致。
- [ ] 前台观察至少 10 分钟，再置于后台至少 5 分钟后返回；记录事件接收/处理增量、进程与历史内存峰值、过载计数及客户端 CPU/RSS。
- [ ] 由 Codex 启动 `/bin/sleep`，核对 PID、PID version、start time、归属根；退出后对应身份消失。
- [ ] 暂停页面读取期间，原生状态继续更新；返回后显示最新状态，历史淘汰不会显示成归属缺口。
- [ ] 停止再开始观察，旧会话状态清除，新 watch 正常启动。
- [ ] 在连接中快速切换页面或关闭窗口，确认本次 runtime-watch 被回收，管理员 relay 继续运行。
- [ ] Windows/Linux 客户端显示未支持状态，其他客户端页面正常。

本轮工具通过开发版二进制路径获取窗口返回 `Invalid app`，应用清单仅列出未运行的安装版，没有可选的开发版窗口；没有启动安装版冒充开发版验收。管理员 relay/observer 在检查期间已退出，socket 消失，之前启动参数为 `--duration 1800`；未读取到退出日志，因此“到时退出”是合理推测。25 秒订阅只收到重连状态，不能作为真实事件负载结果。

## 2026-09-23 运行中降级排查

用户提供的实际窗口截图显示连接、心跳和事件展示均在工作，但页面提示覆盖不完整。对正在运行的同一本地 relay 作独立、普通权限订阅，7 秒采样收到 222 条进程事件及 3 条采集心跳：`coverage=complete`、`coverage_epoch=0`、`overflow=0`、`log_dropped=0`、`log_errors=0`。另一次 5 秒采样收到 7 条确认后代和 123 条未知归属，确认后代的根 PID 为 4167，与正在运行的 Codex 后端进程一致。

上述是前一轮独立 CLI 的观察，不是本轮修复后的 GUI 验收。用户随后确认具体提示为桌面队列溢出。尚无证据判定那一次溢出究竟由后台节流、渲染阻塞还是突发输入触发。

## 队列瓶颈与本轮实测

已确认的结构性瓶颈：旧页面每次最多取 128 条，渲染后再等 250 毫秒，理想上限也只有 512 条/秒；原生缓冲仅 512 条。页面暂停读取时消费率为零，状态计算也停止。新实现取消这一排队依赖，原生线程持续维护状态；未扩大旧队列、未增加自动重连、未隐藏缺口。

| 场景 | 实测或复现结果 |
| --- | --- |
| 旧算法确定性复现，1000 条/秒 | 前 10 秒按 250ms 读取：接收 10000、消费 4776、峰值 512、溢出 10 次；再停读 20 秒：累计接收 30000、溢出 49 次。此项是算法复现，不是 GUI 或真实 ES 实测 |
| 新原生持续流，前 10.183 秒按 250ms 读快照 | 接收=处理=10200，约 1002 条/秒，40 次快照、状态过载 0 |
| 同一流继续约 19.824 秒完全不读快照 | 累计接收=处理=30000；停读阶段处理约 999 条/秒，状态过载 0，最终 PID version=30000 |
| 持续流内存 | 历史原文字节峰值 120400，保留 200 条；进程峰值 1；历史淘汰 29800 条，覆盖保持完整；无待页面消费的事件队列 |
| 资源占用（独立 debug 测试进程） | 30.03 秒墙钟，5.36 秒 user + 7.74 秒 sys，约占单核 43.6%；最大 RSS 11812864 字节（11.27 MiB）。包含事件生产、UnixStream 传输、聚合、快照序列化及测试框架，不代表生产 GUI 的 CPU/RSS |
| 10001 条连续突发、无页面读取 | 约 0.794 秒，接收/处理相等，状态过载 0，精确 uint64 身份保持；对应 EXIT 后移除 |
| 501 个并存身份 | 触发状态容量降级，旧状态清空；后续健康/完整心跳不能覆盖客户端缺口；显式 reset 清除旧观察 |

原生快照带 `received/applied/elapsed_ms/history_evicted/state_overflows/process_peak/history_bytes_peak/process_bytes/pending_records/snapshots/apply_us`。页面开发者工具可调用 `window.runtimeObservation.diagnostics()` 获取最近 120 次有界采样，包含页面可见性、读取间隔、采集覆盖与客户端缺口；只读统计，不包含原始事件。前后台验收应按计数差/时间差计算速率，并独立采样实际桌面进程 RSS/CPU，不能把本表的暂停快照读取称为真实后台测试。

本地证据：`evidence/desktop-queue-fix/rust-tests.log`、`sustained-resource.log`、`old-queue-controlled.json`。`baseline.json` 是服务离线时的重连记录；第一次资源采样未匹配到测试进程，不作为有效资源证据。未修改 relay 协议或管理员部署文件。待用户启动服务并提供可操作开发版窗口后补齐上述 GUI 项目。

## 异常停止的补充运行检查

用户授权操作当前开发版窗口后，再次确认桌面进程存在，但窗口工具用开发版标识返回 `Invalid app`。按该进程 PID 通过 System Events 获取窗口，被 macOS 拒绝：`osascript 不允许辅助访问 (-1728)`。未继续尝试绕过该权限限制。此时管理员 relay/observer 和 runtime.sock 均不存在；未启动或重启服务。

将仓库当前 `scanner/internal/runtimeobservation/output_darwin.go` 原样复制到临时独立 Go 测试包，运行其实际 `prepareOutputFile` / `writeOutputFile`：先填满管道，再释放 8192 字节，尝试写一条 60050 字节记录。结果写出 8192 字节残片，无尾部换行，随后返回 `EAGAIN`。测试输出保存在 `evidence/desktop-queue-fix/actual-go-partial-write.log`。PASS 表示成功复现现有故障行为，不表示修复通过；临时测试包已删除，产品代码未改动。

这证明真实 Go 写入函数可因背压留下半条记录，与 Rust 的无换行记录错误条件一致。仍无历史 stderr 将它与截图 17:52:51 的停止直接对应，也没有取得本轮真实 GUI 验收证据。后续需保留脱敏退出诊断并验证有界写入等待；GUI 复验需解除辅助访问限制并由管理员启动采集服务。

## 真实窗口实测：后台异常已复现

用户授予辅助访问并要求代为测试后，直接操作正在运行的开发版 PID 30590。System Events 曾间歇性无法枚举窗口，随后使用 macOS 原生 AX 接口成功读取控件；用户也确认窗口一直可见。此次依据真实窗口控件与进程状态，不使用模拟页面或截图替代。

### 环境和步骤

- 启动本次临时 relay PID 66446、observer PID 66475，持续上限 1200 秒，复用已部署二进制与受保护 socket；会话 `291E3BCC-6CE5-4BE2-9722-E2BC848CF803`。启动前没有运行中的采集服务。
- 在实际窗口点击“运行时归属”“开始观察”，产生桌面 watch PID 67224。
- 受控 `/bin/sleep 20` 的 PID 为 67834，EXEC 后 PID version 为 206184，start_time_us 为 1790165912116861；页面显示 ES 确认后代，归属根 `4167:7667:1790152111448552`，与独立订阅保存的 ES 原文完全对应。收到相同身份 EXIT 后，页面移除该身份。
- 长时采样 900 秒：前 600 秒为前台观察阶段，后 300 秒将应用隐藏到后台，然后恢复。前台阶段在第 336.92、367.78 秒的样本中焦点为 ChatGPT，因此不能宣称严格连续前台满 10 分钟。其余采样与用户确认表明窗口存在；早期部分 System Events 读失败不作为页面状态通过证据。

### 实际结果

- 后台约 1–2 分钟后真实页面出现无效/不完整记录错误；故障页面最后更新时间为 20:31:08，原生 AX 在 20:31:51 的采样确认该错误。期间没有对桌面进程执行 SIGSTOP，也没有注入畸形记录。
- 后台满 5 分钟返回前台，错误仍在、进程列表清空，watch PID 67224 已不存在。后台稳定性验收为失败。
- 同期独立旁路订阅持续接收 30516 条记录，其中进程事件 29609 条；其计数不等于桌面原生接收计数。最后采集心跳 `coverage=complete`、`epoch=0`、`overflow=0`、`log_dropped=0`、`log_errors=0`，received=processed=34952。
- 桌面进程 30 次采样的 RSS 范围为 44048–62048 KiB，`ps %CPU` 范围 0.3–22.1，包含辅助访问采样开销；该范围不是平均 CPU，也不代表性能目标已通过。
- 另起真实 Go CLI 连接同一 relay，暂停读取 stdout 8 秒：进程自行退出码 1，stderr 为 `runtime_observation_output_failure: resource temporarily unavailable`；stdout 为 65536 字节，最后一条仅 291 字节且没有换行。这个独立测试未暂停或修改桌面进程。
- 使用当前 Go 写入函数的独立测试，1294 字节的正常大小记录在管道仅有 512 字节空间时，写出 512 字节后返回 EAGAIN。两项结果确认非阻塞输出遇背压时会留下残片。桌面自身 stderr 尚未留存，不能把 EAGAIN 作为这次 GUI 停止的已直接记录退出原因；更不能据此还原此前 17:52:51 的故障。
- 故障证据保存后，手动开始观察产生 PID 83144，点击停止后该 PID 被回收；再次开始产生 PID 83544，切换“客户端概览”后该 PID 被回收，relay 和 observer 此时仍在运行。随后返回运行时页面，保持停止观察。
- 本次未关闭整个客户端窗口；完整窗口关闭/退出链路仍待实测。隐藏期间新增的短命 sleep 未被页面采样捕获，不将其算作通过。
- 测试结束仅对本次启动的服务发送中断，确认 relay/observer、测试 watch 均退出，socket 清理；客户端窗口恢复前台并保留打开。服务关闭过程中还看到 `writer.wait_closed()` 的 BrokenPipeError 未收敛日志，应另行修复断开连接清理；不据此认定它导致了桌面记录截断。

### 证据与后续

证据目录：`evidence/gui-live-check/`。主要文件为 `sleep-events.jsonl`、`ui-sleep.txt`、`ui-after-sleep.txt`、`long-run.jsonl`、`native-ui-samples.jsonl`、`actual-gui-failure.json`、`summary.json`、`real-cli-paused-reader.json` 和 `actual-go-realistic-frame.log`。

需要修复实际 Go→Rust 输出链路的有界背压处理，并保存有界脱敏错误类别、记录长度、换行状态及子进程退出原因；复验必须再次包含真实后台运行。这一轮只进行了诊断和验收记录更新，未修改产品代码，不能声称问题已经修复。


## 输出背压修复（2026-09-23）

根因代码：macOS Go 输出使用非阻塞 `syscall.Write`，此前把临时 `EAGAIN` 当作终止错误；已写入的半条 JSON 随进程退出留在 stdout，Rust 因缺少换行而报无效记录。前一轮真实 CLI 已复现该路径，GUI 的历史那次错误仍缺少逐条 stderr 关联证据。

本轮改动：

- 遇到 `EAGAIN` 等待管道可写，按已写字节推进，不重复或跳过字节；每至多 100 ms 检查取消，单条记录等待上限 30 秒，只保留当前记录，不扩大事件队列。
- 超时使用 `runtime_observation_output_backpressure_timeout`，其他终止输出错误保留 `runtime_observation_output_failure`。Watch 各输出路径保留原始错误类别。
- 原生桥接使用固定大小块及最多 128 字节尾部匹配已知 stderr 错误码，不保留或展示任意原始诊断内容。终止后保留具体码并使覆盖降级、清空当前归属。
- 新增两种错误的中英文提示。进程身份、大整数、状态容量、历史淘汰和 reset 契约保持原有实现。

已完成的针对性验证：

- Go 正常和 race 测试通过；新增部分写入后恢复、取消、超时、读端关闭回归。Linux 包交叉编译通过（不代表 Linux 采集支持）。
- Rust 11 项原生/桥接测试含 ignored 项全部通过，随后新增终止错误整链路回归并单独通过（合计 12 项）。30,000 条持续流测试在后 20 秒不取页面快照，received=applied=30,000、state_overflows=0、history_evicted=29,800、history_bytes_peak=120,400。这是原生受控测试，不代替 GUI 实测。
- 独立原生验收夹具复现子进程输出不完整记录并在 stderr 给出超时码，确认最终保留超时码、coverage=degraded、当前进程为空。
- 实际 CLI 接入真实 relay 后暂停读取 8 秒：进程存活并恢复读取，189 条可解析记录、无 JSON 解析失败；该测试连接出现 `helper_disconnected` / `new_transport_connection` reset，不宣称暂停期间无采集缺口。测试主动结束产生的 `context canceled` 单独识别。
- 实际 CLI 暂停读取 35 秒：读取恢复前已退出 1，stderr 明确为 `runtime_observation_output_failure: runtime_observation_output_backpressure_timeout`；尾部残片按无效处理。这是预期过载降级，不作为无损通过。
- 真实 `/bin/sleep`：PID 1297、pidversion 245082、start_time_us 1790167598000241，根身份 4167:7667:1790152111448552。GUI 和 ES EXEC 身份一致，显示 ES 确认后代；ES EXIT 后 GUI 移除。
- `cargo check --offline`、桌面开发构建、JavaScript 语法、既有 i18n 29/29 和 `git diff --check` 通过；无新增 UI 单元测试。

证据在忽略目录 `evidence/backpressure-fix/`；`exploratory/` 是重新计时之前的试跑，严格前台/后台记录在 `confirmed/`。长时结果与验收边界如下。


### 修复后真实 GUI 长时数据

- 区间：本地时间 20:47:54 至 21:02:56；前台 600 秒，隐藏后台 300 秒，再返回前台。31 次原生 AX 样本；前台样本焦点均为桌面 PID 96916，另有 NSWorkspace 焦点变更记录，隐藏期间均确认 hidden=true。
- 桌面 watch 始终为 PID 2354，未异常退出；所有 GUI 样本维持“当前订阅未发现缺口”，没有队列溢出、无效记录或终止输出错误。后台 sleep PID 13250、pidversion 258910、start_time_us 1790168337209715，根身份与前台测试相同；在 ui-0694.json 可见，EXIT 后及返回前台时已移除。
- 独立旁路收到 30,153 条输出，其中 continuous_attribution 29,242、observer_health 450；平均约 33.5 条输出/秒。旁路无 JSON 解析错误；有 5 条 client_status。本次未保存各条状态的具体 reason/reset 字段，不能仅凭数量断言重连次数，也不能归因于采集器、桌面或负载。后补的独立 120 秒状态探针没有重连。旁路数字不能当作桌面原生 received/applied 指标，也不能用传感器计数相减推算丢失量。
- 最后传感器 health：received=processed=41,855，overflow=log_dropped=log_errors=event_remaining=0，coverage=complete、snapshot_coverage=partial。这仅是传感器报告的覆盖，不能证明每条订阅都无缺口。
- 桌面主进程 RSS 样本 59,696–65,680 KiB（约 58.3–64.1 MiB），首尾 65,424 / 65,680 KiB；CPU 样本 0.4%–31.5%。包含 AX 查询开销，不包含 WebKit 辅助进程的总内存，不是全程峰值或平均 CPU。
- 没有直接导出这次 GUI 的原生 metrics，因此接收/应用一致性、状态容量和历史淘汰的精确计数使用前述受控原生测试单独证明。本轮通过的是指定负载下 GUI 稳定性和明确降级，不能扩大为全链路零丢失验收。

### 真实 GUI 持续背压注入

正常 15 分钟观察完成后，单独对开发桌面 PID 96916 发送 SIGSTOP，36 秒后通过 finally 恢复 SIGCONT；未暂停管理员 relay、observer 或受管后台服务。恢复后实际界面显示“客户端输出持续阻塞超过 30 秒，已停止观察，当前归属已清空。”，传输离线、覆盖不完整、当前进程 0，按钮回到“开始观察”。这是有意制造的终止降级，与正常后台运行样本分开保存于 `gui-overload.json`。


### 生命周期与剩余手验

- 实际 GUI：开始 watch 19947 → 停止回收；重新开始 19983 → 切到客户端概览回收；再开始 20038 → 关闭窗口回收。每一步均核对 relay 96996、observer 96997 仍在运行。
- 本轮临时管理员采集进程在生命周期验证之后单独清理；未安装常驻服务，未修改已部署 relay，未提交或推送代码。
- 已验证中文真实超时提示；英文资源与既有 i18n 检查通过。尝试在设置中切换英文未成功，因此英文真实窗口的告警布局仍列为手验 Todo，不宣称已完成双语视觉验收。
- UI Todo：英文模式下检查新增输出失败/30 秒背压超时长文案的换行与按钮布局；可按后续真实负载继续观察。泛化的全链路零丢失、真实 GUI received/applied 精确计数仍不在本次已通过的证据范围内。

清理时已确认本轮 relay/observer、各 watch PID 和临时 socket 均消失。已部署 relay 在客户端断连清理时仍会输出 `wait_closed()` 的 BrokenPipeError 回溯；本轮未修改该管理端清理路径，也不把该回溯当作 ES 丢事件证据。
