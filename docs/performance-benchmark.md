# 性能基准与容量边界

本文记录 `2026-08-13` 在隔离测试环境中完成的单节点 Docker 性能基准。数据用于部署选型和参数起步，不是脱离硬件、数据规模和上游服务的产品硬上限。

## 概览投影与多个写入者的等待（2026-10-18）

将概览正文解析和投影准备移到取得写权限之前，发布时重新检查水位与到期状态；概览和 AIDR 有界清理加入采集、审计已有的两个异步名额。模型网关、数据库结构及提交耐久性保持不变。完成低、高负载各三组合格交替配对，另保留一组环境不合格配对，并运行两轮独立诊断。高负载吞吐中位值提高 2.3%，补传积压减少 10.5%，从未审计记录数 P95 下降 52.7%；模型网关低/高负载 P95 分别下降 32.5% / 15.8%。诊断中概览持锁 P95 从 177ms 降至 112ms。

改动保留，93 项定向测试通过，但性能验收仍部分达成：高负载 Dashboard 两对变慢约 11–19ms，低负载 Skill 列表中位值升高 3.6%，AIDR 清理全量完成时间增加约 30%。诊断未确认页面波动的因果来源，不能将其直接视为误差或宣称全面无回退。完整环境、逐对数据、并发边界和剩余热点见[概览投影与写入等待复测](benchmarks/2026-10-18-overview-writers.md)。

**English:** Overview preparation now precedes writer acquisition; publication rechecks progress and raw-record expiry. Projection and bounded AIDR retention share the existing two collection/audit admission slots. Three qualified alternating pairs per load show 2.3% higher high-load throughput and 10.5% less replay backlog; model-gateway P95 improves by 32.5% at low load and 15.8% at high load. Separate instrumentation measures projection hold P95 dropping from 177ms to 112ms. The change is retained with 93 passing tests, but performance acceptance is partial: some page pairs worsen and high-load AIDR cleanup completes about 30% later. Page non-regression and production capacity are not established. The report retains the excluded environmental pair and all qualified unfavorable results.

## AIDR 到期 UPDATE 成本拆解（2026-10-18）

隔离实验确认表达式索引维护和页缓存压力贡献了到期 UPDATE 成本。保持 500 条事务的临时页缓存候选完成十二轮交替混合压测与两轮独立诊断：高负载清理耗时中位值下降 6.3%，吞吐提高 0.8%，积压减少 5.2%；但模型网关 P95 上升 14.5%，周期审计待复核数 P95 上升 28.9%。候选未通过整体性能验收，已撤回；最终应用与本轮起始快照一致，保留真实后台清理并发上传的回归覆盖。详见[完整成本拆解、逐轮结果与候选处置](benchmarks/2026-10-18-aidr-retention-cache.md)。

**English:** Isolated UPDATE experiments identify expression-index maintenance and page-cache pressure as contributors. Twelve alternating mixed-load runs and two separate diagnostic runs show faster retention but worse high-load model-gateway and periodic-audit tails. The candidate was withdrawn; the application matches the starting snapshot. Regression coverage for concurrent late-result upload through background retention remains.

## 当前版本的混合负载写锁定位（2026-10-18）

以包含最新页面优化的工作区为基线，完成低、高负载各三轮，并对概览查询构造候选分别复测三轮。高负载基线唯一 ACK 吞吐中位值为 471.65 条/秒、补传窗口末积压 3,710 条。独立诊断确认 AIDR 清理与概览投影存在长持锁段，Skill 审计和列表主要等待获取写锁；线程排队不是主要等待来源。

候选高负载吞吐为 466.66 条/秒、积压 4,010 条，Skill 列表 P95 从 296.35ms 升至 352.69ms；虽然高负载模型 P95 下降，但不足以通过整体验收。本轮未保留运行时代码调整，原有修复保留；新增诊断分类与证据一致性回归覆盖。完整逐轮指标、候选处置和环境边界见[写锁热点复测报告](benchmarks/2026-10-18-aidr-write-hotspots.md)。

**English:** Three runs per load level establish a fresh baseline including the page-query improvements. A separately measured overview-query candidate does not improve collection backlog or Skill-list tail latency sufficiently to retain. Final application code matches the starting snapshot; improved diagnostic attribution and evidence-consistency regression coverage remain. Instrumented lock timings are reported separately from the formal performance matrix.

## 页面 API 三组交替复测（2026-10-18）

保留 Codex 和网络代理，在用户认可的当前后台负载下，用相同源码和脚本完成三组交替对照。
客户端列表、Agent 列表、智能体资产页和概览三组 P95 均下降，中位值分别降低 24.9%、86.6%、
26.0%、34.6%。实际开始前 CPU 为 28.9%–31.1%，最低可用内存约 4.2 GiB，没有换出。
全部 1,728 个含预热请求成功；这是有后台负载的 API 测量，未覆盖浏览器和网关并行流量。
详见[完整逐组结果及环境限制](benchmarks/2026-10-18-page-queries.md)。

**English:** Three alternating pairs with unchanged sources and fixtures confirm lower P95 for the main
list/overview APIs under the accepted background load. Starting CPU was 28.9–31.1%; browser and concurrent
gateway performance remain outside this experiment.

## 页面 API 查询优化（2026-10-17）

本轮覆盖九类页面 API：客户端列表关联查询从 801 条降到 8 条，Agent 列表从 201 条降到 4 条，
智能体资产页从 205 条降到 8 条；概览合并证据统计，链路普通事件页只读取脱敏 payload。
三组成对隔离测试中，客户端、资产页和概览 P95 中位值分别下降约 37%、31%、33%。
本机 CPU/内存压力超出此前空闲门槛，这些耗时仅为参考，不代表浏览器首屏或网关混合负载验收。
完整逐轮结果、未改善的路径和人工测试清单见[页面查询报告](benchmarks/2026-10-17-page-queries.md)。

**English:** Batched page metadata reads reduce Client/Agent SQL counts and avoid loading raw trace content
on ordinary event pages. Three paired API runs show improvements for major list/overview paths, with host
resource pressure explicitly limiting timing conclusions. Browser and mixed-load acceptance remain separate.

## 审计持锁与共享准入复测（2026-10-17）

减少审计/列表持写锁期间的逐条重读，将审计与采集统一到两个异步准入名额，并修复名额唤醒交接时的超额占用。最终低、高负载各三组成对正式测试，加一组成对诊断，均通过环境检查。高负载 ACK 吞吐中位值提高 2.2%，窗口末积压减少 13.6%，Skill 列表 P95 下降 23.3%；审计最老超期仍约 1 秒，最终首次未核对为零。低负载模型 P95 三组都下降，但低负载页面略慢，高负载有网关尾延迟升高的轮次，不能宣布全面无回退。83 项定向回归通过，详见 [源码边界、逐轮数据与等待诊断](benchmarks/2026-10-17-aidr-shared-admission.md)。

**English:** Shorter audit write phases, shared asynchronous admission and a fixed slot-handoff race improve high-load collection and Skill-list medians while retaining audit catch-up. All 83 targeted regressions pass. Low-load page latency and some high-load gateway tails remain unresolved; see the linked report for the final matched matrix and separate diagnostics.

## AIDR 证据查询与审计追赶混合复测（2026-10-17）

沿用含 Skill 审计和后台查询的 100 客户端工作负载，低、高负载各三组成对复跑，12 轮均通过环境门槛。审计待复核数 P95 中位值分别下降 59.3% 和 81.9%，高负载优化版最终首次未核对数三轮均为零；但高负载采集吞吐中位值下降 1.5%，窗口末积压增加 13.7%，页面尾延迟没有稳定改善。模型 P95 中位值下降，但两种负载各有一组升高，低负载波动扩大，尚不能确认网关不受影响。60 项定向回归通过，完整条件、逐轮结果及正确性边界见 [混合复测报告](benchmarks/2026-10-17-aidr-evidence-catchup.md)。

**English:** Twelve eligible matched runs show better audit catch-up, but do not establish overall performance acceptance: high-load acknowledged throughput is slightly lower, collection backlog is higher, and page/gateway tail behavior remains mixed. All 60 targeted correctness regressions pass. See the linked report for paired results and measurement limits.

## 100 客户端采集、补传与清理混合压测（2026-10-14）

新增本机隔离 HTTP 压测：100 个客户端身份持续生成日志与 Hook，暂停上传 20 秒后补传，并同时执行 AIDR、Pipeline Trace、Runtime Trace 清理及模型/MCP 网关调用。
400 条记录/秒、每个网关 5 次/秒时复现了事件循环同步等待数据库连接池，导致上传、网关和清理相互影响。
100 条记录/秒、每个网关 1 次/秒、模拟器最多 4 路上传时，13,020 条记录全部持久化，恢复时积压约 14 秒补完，历史清理约 12–25 秒完成；模型/MCP P95 在重叠窗口仍分别上升至约 970 ms/1.45 秒。
上传并发限制属于实验条件，尚不是生产策略；以上不是生产容量承诺。详见 [测试口径、三档结果和阻塞栈分析](benchmarks/2026-10-14-aidr-100-clients.md)。

### 网关连接池修复后的同条件复跑（2026-10-15）

同步数据库阶段改在线程中执行，并在等待请求体、上游调用和流式输出前归还连接。最终三档 100 客户端复跑均完成预置历史清理，未再捕获此前约 89 秒的事件循环停顿。高负载两档 ACK 从 700/1,630 条增加至 49,900/45,140 条，但仍有 2,160/6,940 条未确认积压和少量上游连接失败。
低负载 13,020 条全部入库；补传与清理期间模型/MCP P95 却从约 0.97/1.45 秒升至 3.95/3.77 秒。因此本次验证了阻塞机制修复，尚未达到网关尾延迟和持续容量目标。数据库继续使用 SQLite，完整口径、旧源码复核及 231 项通过的定向回归见 [修复对比报告](benchmarks/2026-10-15-gateway-pool-fix.md)。

### 网关尾延迟与连接复用复测（2026-10-15）

进一步将概览清理改为批量统计扣减，清理在表间让出执行机会，MCP 一次调用的三个协议步骤复用 HTTP 客户端。保持 SQLite、连接池、清理批量和负载参数不变，低负载模型/MCP P95 从上一轮 3.95/3.77 秒降至 3.23/3.18 秒，13,020 条全部确认，但仍未恢复最初低负载水平。

高负载 4 路/100 路分别确认 42,180/46,380 条，剩余 9,860/5,660 条；模型/MCP P95 分别为 5.84/5.41 秒和 18.84/19.81 秒。历史清理全部完成，100 路时 AIDR 清理耗时约 141 秒，比上一轮更慢。三档没有记录上游连接失败，但 4 路场景有 2 次压测端读取网关响应的 `ReadError`，不能算作成功。

由于共享主机波动，追加旧版同机 4 路完整对照：旧版确认 32,590 条，模型/MCP P95 为 6.40/6.81 秒，并出现 6 次模型、18 次 MCP 连接失败。当前版本在该对照下有所改善，但历史高负载结果并非全面提升，不能据此宣称持续 400 条/秒容量达标。详见 [完整结果、错误边界与源码摘要](benchmarks/2026-10-15-gateway-contention-fix.md)。

### 网关事务减量与采集批内 SQL（2026-10-15）

在 `RENA-1470` rebase `dev` 后建立即时基线，合并 MCP 两级租约事务及释放/审计提交，将过期租约清理移至后台，并对日志、Hook 的查重、凭据读取、证据与操作投影写入做批量化。保留单批提交后 durable ACK、冲突整批回滚及数据库原子并发限制。

正式 100 客户端对照中，高负载 4 路/100 路的补传窗口有效 ACK 吞吐从 139.47/201.83 提高到 278.16/364.49 条/秒，固定排空策略下最终未确认记录从 11,580/8,310 降到零；模型/MCP P95 分别从 5.57/5.83 降到 4.50/4.08 秒，以及从 18.90/19.98 降到 11.57/10.37 秒。100 路 AIDR 清理从 151.11 缩短到 86.42 秒。

低负载正式轮 P95 升高，追加反向对照则降低；同一优化版模型 P95 两次为 3.93 和 0.92 秒，不能宣称稳定改善。高负载停止生成前仍有积压，尚未验证持续 400 条/秒能力。378 项定向回归通过，5 项因缺少可选 MCP SDK 跳过。源码摘要、全部 8 组结果及语义验证见[完整对照报告](benchmarks/2026-10-15-gateway-transaction-fix.md)。

### 清理窗口写锁与低负载多轮复测（2026-10-15）

继续定位发现长等待主要在 SQLite 写锁获取；进一步合并模型网关完成事务、将采集写入入口限制为每事件循环两个并发，并批量化统计投影。普通非流式 AccessToken 模型调用写提交从 6 次降到 4 次，250 个独立 Hook 调用的统计投影 SQL 驱动调用从 1,512 次降到 38 次。数据库、落盘后 ACK、幂等、并发校验及清理批量保持。

三组新鲜低负载对照中，补传清理窗口模型 P95 从 1,588/1,140/2,133 ms 降至 903/800/912 ms，三轮中位数降低约 43.1%，极差从 993 ms 缩至 112 ms。MCP 三轮中位数从 1,129 降至 862 ms，但第二组略有回退。每轮每网关窗口仅 60 个请求，优化后仍有秒级单请求尾延迟；长期稳定性尚待验证。完整负载、积压、清理、错误和验证边界见[清理窗口与尾延迟复测](benchmarks/2026-10-15-gateway-tail-stability.md)。

### 采集 CPU 开销与积压复测（2026-10-16）

复用正文控制字符扫描及固定采集 SQL 的构造/编译结果，保持 SQLite、两路采集准入、批次独立提交、并发校验及落盘后 ACK。三组低负载与 4 路/100 路上传各两组前后对照，共 14 轮。低负载模型网关 P95 三组均下降，中位数 406.56→254.68 ms；高负载补传 ACK 吞吐分别从 471–503 提高到约 533 条/s，四组补传窗口末未确认量从 1,840–3,720 降至 10–20 条。

收益存在边界：4 路高负载模型/MCP P95 两组均回退，100 路一组改善、一组回退；低负载 MCP 波动范围扩大。AIDR 清理约 13–16 秒，没有一致加速。14 轮最终全部确认且清理完成，1 次采集 `ReadError` 经重试恢复；324 项回归通过。磁盘耗尽的中断轮及其配对结果已排除，两对 100 路在恢复空间后完整重跑。详见[积压、尾延迟、环境限制与完整性报告](benchmarks/2026-10-16-gateway-backlog-fix.md)。

### 三处正确性回归修复复测（2026-10-16）

修复清理误覆盖已 ACK 的迟到结果、可选 Runtime Trace 失败回滚会话完成状态、MCP 扫描早期拒绝后的脱离 Session 异常。最终受影响测试 85 项通过，保留 SQLite、并发租约、幂等及落盘后 ACK；正常模型网关路径仍合并提交。

与上一轮优化版本同参数完成 14 轮对照。修复版低负载模型 P95 三轮为 258–271 ms；4 路高负载 ACK 中位数从 491.4 降至 429.6 条/s，补传窗口末未确认量从 2,290–2,760 增至 5,510–7,000。100 路两轮结果混合。最终全部落盘和清理完成，无请求错误，但主机 CPU/页面调入活动波动，历史采样未记录独立的 Swapins，不能确认整体性能不回退。完整逐轮结果、环境记录及较大测试集的三个既有失败见[正确性修复与性能验收报告](benchmarks/2026-10-16-gateway-regression-fixes.md)。

### 4 路高负载环境对照（2026-10-16）

保持上述三处修复及应用源码不变，退出授权的闲置应用，分别记录 macOS Pageins 与 Swapins，并设置逐轮空闲/运行期资源检查后，串行完成三组成对复测。两版本的 ACK 中位数均约 533.3 条/s；保留修复版窗口末未确认量为 10–20 条，上轮同一源码为 5,510–7,000 条。采集吞吐下降没有复现，当前不为此继续修改应用代码。

六轮资源和完整性检查均通过，压测后 8 项直接回归通过。模型 P95 中位数仍为 678 → 829 ms，两组成对升高、一组下降，因此只确认此次负载下的采集追赶能力，不能确认整体尾延迟不回退。监控口径更正、环境限制及全部结果见[4 路高负载复测报告](benchmarks/2026-10-16-high4-environment.md)。

## Skill 导入与 API 隔离回归（2026-10-14）

当前代码检查与本机隔离测试确认了以下路径，并完成对应优化：

| 路径 | 优化前 | 当前行为 |
| --- | --- | --- |
| ZIP / Scanner 导入 | `async def` 中同步解压、复制、计算摘要和准备版本，阻塞事件循环 | 整个准备流程在线程执行，并使用独立导入额度 |
| URL / ClawHub / 远程候选准备 | 异步下载后在事件循环同步处理文件 | 网络请求保持异步，文件写入、解压和准备在线程执行 |
| 上传解析、流式进度、本地目录、远程选中导入 | 使用普通同步 API 的线程额度 | 共用独立导入额度，默认并发 2 |
| Registry 查询 | 读写共用进程锁；扫描写入等待会挡住读取 | 只读连接读取已提交 WAL 快照，退出即关闭；写入继续串行 |
| 运行验签和客户端扫描状态 | 读取报告后丢弃，或只使用状态/签名 | 查询元数据，省去完整报告读取和解析；详情报告仍可查询 |

`tests/test_scan_api_isolation.py` 使用临时 SQLite、合成 ZIP、ASGI HTTP 请求及受控等待，覆盖：

- 解压等待时，ZIP、Scanner、URL、ClawHub、远程候选和普通/流式上传准备不阻塞列表请求。
- 导入额度与普通线程额度均设为 1 时，第二个导入排队，普通同步工作仍可完成。
- 持有扫描写事务时，Registry 查询可读取此前已提交数据；同一读取快照保持一致，下一次查询看到提交后的状态。
- 2 MB 合成报告不进入验签 SQL，成功验签仍记录审计；详情可读取完整报告，撤销后的新请求被拒绝。
- 流式连接断开后等待正在执行的准备清理；同一进程并发提交相同内容复用一个版本与待检测任务。

导入查重、版本准备和待检测任务登记使用独立准入锁，避免并行导入同时创建相同内容；该锁不参与普通查询和验签。
持久化上传导入队列保留原有单线程准备方式。跨进程并发准入未在本次回归中验证。

优化前的受控 2 秒解压可复现 ZIP 和 Scanner 入口阻塞事件循环；持有扫描写锁时，读取也无法在 0.5 秒测试门槛内完成。
优化后的对应检查通过。这些等待和门槛用于确定性回归，不是生产 P95、端到端吞吐或容量承诺。

可复跑：

```bash
uv run pytest tests/test_scan_api_isolation.py tests/test_submission_background.py tests/test_registry.py tests/test_runtime.py tests/test_scanner_api.py tests/test_manager.py tests/test_clients_api.py tests/test_client_runtime_integration.py tests/test_review_queue_api.py tests/test_folder_upload_limits.py tests/test_upload_jobs.py tests/test_vetting.py -q
# 真实 Scanner 使用独立依赖环境，补充默认环境跳过的检测链路：
uv run --with cisco-ai-skill-scanner==2.0.6 python -m pytest tests/test_client_runtime_integration.py::test_real_scan_rejection_is_polled_and_quarantined_without_desktop -q
```

本次主回归为 222 项通过、1 项因默认环境缺少 Scanner 跳过；随后使用上面的独立解释器命令补跑真实
Scanner / Go 客户端 HTTP 链路，1 项通过。最后补充连接断开与相同内容并发提交检查后，导入隔离、后台提交和
Scanner API 的 41 项检查全部通过。两轮统计有重叠，不应相加作为独立用例数。

共享边界仍包括 CPU/GIL、磁盘、内存和 SQLite 单写者。验签审计、客户端上报等写入仍可能等待扫描写事务。
正式验收应在目标主机持续批量检测，同时访问页面 API、验签、心跳、任务和状态轮询，记录空闲与检测中的
P50/P95/P99、错误率、事件循环延迟、CPU、磁盘延迟和数据库写等待。当前未执行生产部署或现场混合负载压测。

**English:** Local contention regressions verify event-loop responsiveness, separate bounded import capacity,
committed WAL snapshots and metadata-only verification/status polling. Authorization, fresh state reads and durable
audit remain required. Shared CPU/GIL, disk and SQLite writers still require deployed mixed-load measurement.

## 测试环境

| 项目 | 本次环境 |
| --- | --- |
| 服务器 | VMware 虚拟机，共享测试宿主机 |
| CPU | `8 vCPU`，Intel Xeon E5-2678 v3 @ 2.50 GHz |
| 内存 | `31 GiB`，另有 `8 GiB` Swap |
| 磁盘 | `195 GiB` ext4，测试时可用约 `49 GiB`，Docker `overlay2` |
| 操作系统 | Ubuntu 24.04.4 LTS，Linux `6.8.0-137-generic`，x86_64 |
| Docker | Client `28.5.2`，Server `29.1.3`，Compose `v5.0.1`，cgroup v2 |
| 被测版本 | Backend `dev-d6ec8a5b`，linux/amd64 |
| Backend | 单容器、单 Uvicorn 进程、SQLite WAL |
| 扫描并发 | Scan Worker `2`、分析器 Worker `8`、深度扫描并发 `2` |
| Sandbox | 独立测试容器，`1 CPU / 512 MiB`，nsjail |

测试节点同时运行其他业务容器，本结果包含共享宿主机的资源抖动。压测使用独立 Backend、SQLite、Registry、Sandbox 和 Docker 网络，没有向现有平台写入 Skill、审计或凭证。

## 测试口径

- 网关采用固定处理延迟 `50 ms` 的本地模拟上游，排除公网和供应商排队；表中仍包含 HTTP 往返。模型直连上游在并发 `10` 时实测 P95 为 `98.60 ms`。
- 每个网关阶梯发送 `20–80` 次请求，记录成功数、吞吐与客户端观测的 P95。
- Skill 检测使用小型确定性样例。规则扫描、深度扫描和 Sandbox 分开执行；没有调用外部 LLM，所以不能把深度扫描结果当作 LLM 分析耗时。
- 客户端使用与被测 Backend 同一提交 `d6ec8a5b` 的 Go 客户端，在测试节点本地生成合成 Skill 目录并执行完整 Inventory，共运行 `10` 轮。
- “稳定”表示本轮没有错误或超时。长时间 Soak、故障注入及多实例测试尚未执行。

## 智能体安全 P7-04 自动负载回归

`2026-08-30` 新增的 P7-04 测试运行在本机隔离 SQLite 和 FastAPI TestClient 中，用于防止扫描/轨迹关键路径出现明显退化：

- 24 路并发领取 24 个待扫描任务，Worker 上限为 8；验收结果必须恰好形成 8 个不重复租约，其余 16 个保持排队。
- 长会话扫描结果包含 120 个用例、120 个 Finding、1200 轮计数、2 MiB 加密原始产物和 120 个完整追溯事件。
- 轨迹单批写入 1000 个事件，覆盖 100 个 Turn；随后写入 4 MiB 原始 Payload，验证加密存储、脱敏投影和游标序列。

本机单次测试调用约为 `0.7 s` 量级，每项使用 `30 s` 宽松门槛检测明显退化或死锁。该门槛不是生产 SLA。轨迹凭证默认请求体上限为
`1024 KiB`；4 MiB 用例只在显式设为 `10240 KiB` 的隔离测试凭证下执行。测试不包含真实 AI-Infra-Guard Provider 网络、多实例、长时间 Soak 或银行硬件资源指标，
因此不能推导客户容量、P95 或资源规格。

## 生产环境参数基线

本节给出单节点新部署的推荐初始参数，用于建立可观测、可逐级调优的生产配置基线。部署后应使用真实业务负载验证延迟、错误率和资源利用率，再依据监控结果逐级调整，不应直接将并发上限设置为 `100`。

先区分三个容易混淆的概念：

- **最大并发**：同一时刻允许多少个尚未完成的请求。例如最大并发为 `5`，表示第 6 个同时到达的请求会被限流；它不表示每秒只能处理 5 个请求。
- **吞吐量（req/s）**：系统每秒实际完成多少个请求，取决于单次请求耗时、上游服务和平台处理开销。提高最大并发不一定提高吞吐。
- **P95 延迟**：95% 的请求在该时间以内完成。P95 比平均值更能反映大多数用户遇到的慢请求。

### 实际需要配置的项目

| 设置项 | 控制范围 | 推荐初始值 | 配置位置 | 达到上限时的表现 |
| --- | --- | ---: | --- | --- |
| 模型网关凭证“最大并发请求数” | 使用同一模型 API Key、尚未完成的模型请求，允许范围 `1–100` | `5` | 模型网关的 API Key 新建或编辑页面 | 新请求返回并发限制错误；已经开始的请求继续执行 |
| MCP 接入凭证“最大并发请求数” | 使用同一接入凭证的 MCP 请求，允许范围 `1–100` | `5` | 凭证管理的新建或编辑页面 | 新请求返回 `429`；它是凭证级第一层限制 |
| 单个 MCP Tool“最大并发” | 指定 Tool 同时执行的调用，允许范围 `1–100` | `5` | MCP 网关的 Tool 安全策略 | 超出的调用返回 JSON-RPC 并发限制错误，不会继续调用上游 Tool |
| Scan Worker | 同时处理的后台 Skill 检测任务数 | `2` | Docker `.env` 中的 `AGENT_MANAGER_SCAN_WORKERS` | 提交仍可被接受，超出的任务在后台队列等待 |
| 导入准备并发 | 解压、目录发现、摘要及版本准备 | `2` | Docker `.env` 中的 `AGENT_MANAGER_IMPORT_WORKERS` | 请求异步等待独立额度，不占用普通 API 线程额度；按 API 进程/事件循环计算 |
| 分析器 Worker | 静态规则、结构分析等分析任务共用的线程池大小 | `8` | Docker `.env` 中的 `AGENT_MANAGER_ANALYZER_WORKERS` | 数量过小会延长检测；盲目增大可能造成 CPU 争用，不能理解为可同时完成 8 个 Skill |
| 深度扫描并发 | 同时执行的深度扫描数量 | `2` | Docker `.env` 中的深度扫描并发项 | 超出的深度扫描等待可用槽位，因此批量任务的完成时间会增加 |

MCP Tool 调用同时受“接入凭证最大并发”和“单个 Tool 最大并发”两层限制。例如凭证上限为 `5`、Tool 上限为 `10`，这个凭证调用该 Tool 时最多仍只有 `5` 个请求同时执行；反过来，凭证为 `10`、Tool 为 `5` 时，该 Tool 最多同时执行 `5` 个。真实可用并发还会受到上游 MCP Server 超时和性能的约束。

模型网关的并发值按凭证限制。创建多个凭证并不会让单节点容量成倍增加，因为这些请求仍共享 Backend、SQLite 审计写入、CPU、网络和同一个模型供应商。实测中并发从 `5` 提高到 `10` 后，模型网关吞吐没有继续增长，P95 从 `391.31 ms` 上升到 `758.27 ms`，因此将 `5` 设为推荐初始值，是为了在吞吐、延迟和突发余量之间取得平衡，并不表示系统最多只能处理 5 个请求。

扫描相关的三个值作用不同：Scan Worker 决定同时处理多少个 Skill；分析器 Worker 决定这些检测任务内部可使用多少条分析线程；深度扫描并发单独限制资源开销更大的深度分析。三者不能按乘法直接换算为吞吐。推荐初始组合为 `2 / 8 / 2`，用于降低批量提交造成 CPU、SQLite 写入和临时空间同时出现资源尖峰的风险。

### 如何逐步调整

1. 先使用上述初始值，用真实模型、真实 MCP Tool 和接近生产大小的 Skill 连续运行 `30–60` 分钟。
2. 记录 P95、错误率、`429`/JSON-RPC 限流、上游超时、CPU、内存、SQLite 锁等待、磁盘 IOPS 和临时目录使用量。
3. 一次只调整一个参数。网关并发可按 `5 → 8 → 10` 逐级提高；扫描并发每次只增加 `1`，然后重新测试。
4. 如果吞吐没有提高，但 P95、超时或资源占用明显上升，应退回上一档；这说明瓶颈不在并发上限。
5. 如果业务确实需要稳定并发 `20+`，应先验证外部数据库或存储、多进程/多实例、审计写入路径和长时间稳定性，而不是只把页面参数改成 `100`。

运行时 Skill 验签的“调用端并发不超过 `10`”是调用建议，不是管理台配置项；`50,000` 个 Skill 是本次容量验证规模，也不是可以填写的系统参数。它们分别在后文“Skill 检测与运行验证”和“Skill 数量与客户端性能”中解释。

## 网关实测

### 模型网关

| 并发 | 成功/请求 | 吞吐 | P95 |
| ---: | ---: | ---: | ---: |
| 1 | 40/40 | 8.05 req/s | 138.72 ms |
| 2 | 40/40 | 13.84 req/s | 172.89 ms |
| 5 | 40/40 | 16.28 req/s | 391.31 ms |
| 10 | 40/40 | 15.23 req/s | 758.27 ms |
| 20 | 0/40 | 0 | 30 秒超时 |
| 40 | 0/80 | 0 | 30 秒超时 |

模型供应商的排队、首 Token 和生成时间需要叠加到这些数据上。生产容量应以目标模型、真实 Prompt 大小、隐私检测、Prompt Guard、Token 压缩和流式响应配置重新测试。

### MCP 网关

| 操作 | 并发 | 成功/请求 | 吞吐 | P95 |
| --- | ---: | ---: | ---: | ---: |
| initialize | 10 | 20/20 | 103.76 req/s | 115.07 ms |
| tools/list | 10 | 20/20 | 75.01 req/s | 156.18 ms |
| tools/call | 5 | 20/20 | 7.66 req/s | 699.39 ms |
| tools/call | 10 | 20/20 | 7.96 req/s | 1,324.51 ms |
| tools/list | 20 | 20/40 | 0.66 req/s | 30 秒超时占半数 |
| tools/call | 20 | 0/40 | 0 | 30 秒超时 |

真实 Tool 性能还取决于上游 MCP 服务。这里的模拟 Tool 只等待 `50 ms`，因此表中的额外延迟主要来自网关鉴权、两级并发租约、JSON Schema 校验和审计写入。

## Skill 检测与运行验证

| 场景 | 并行提交 | 接口接受 P95 | 检测完成 P95 | 扫描器报告 P95 |
| --- | ---: | ---: | ---: | ---: |
| 规则扫描（热态） | 1 | 129.44 ms | 293.40 ms | 22.66 ms |
| 规则扫描（热态） | 4 | 554.28 ms | 797.83 ms | 21.98 ms |
| 深度扫描 | 1 | 5.76 s | 11.99 s | 6.08 s |
| 深度扫描 | 4 | 381.44 ms | 12.81 s | 6.22 s |
| Sandbox，小型 Python 入口 | 1 | 71.13 ms | 411.49 ms | 186.58 ms |

深度扫描并行 `4` 时，单次分析约 `6.1 s`，但完成 P95 约 `12.8 s`，与深度扫描并发上限 `2` 的两批排队一致。Sandbox 样例只执行一次很短的 Python probe；依赖安装、复杂入口、超时和远程 Sandbox 网络都会明显改变结果。LLM 分析由选定模型决定，本轮没有用模拟结果冒充真实模型性能。

运行时验签在并发 `1/2/5/10/20/40` 均无错误，吞吐在约 `31–36 req/s` 饱和；对应 P95 为 `39.83/74.13/192.18/376.35/881.90/1,446.71 ms`。调用端如果希望 P95 低于 `400 ms`，本环境建议并发不超过 `10`。

## Skill 数量与客户端性能

隔离 Registry 加载 `50,000` 个合成 Skill 家族后，SQLite 文件约 `59.97 MiB`。每项查询执行 `50` 轮：首屏列表 P95 `75.82 ms`、中间页 P95 `111.01 ms`、名称搜索 P95 `89.03 ms`、仪表盘分组 P95 `145.34 ms`。合成数据不含真实包体、多版本、扫描报告和审计，因此只能证明 5 万级元数据查询可用，不能据此估算生产磁盘占用。

| 客户端本地 Skill | Inventory P50 | Inventory P95 | 最大耗时 | Inventory JSON | 进程峰值 RSS（5 轮） |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 86.87 ms | 94.74 ms | 131.26 ms | 21.40 KiB | 15.0–15.8 MiB |
| 500 | 239.86 ms | 245.01 ms | 317.36 ms | 104.99 KiB | 15.9–16.5 MiB |
| 1,000 | 414.51 ms | 439.15 ms | 524.31 ms | 210.46 KiB | 16.7–17.1 MiB |

客户端 Inventory 会在本机遍历 Agent Skill 目录、读取元数据、生成清单并写入本地 SQLite，所以这部分 CPU、磁盘读取和内存主要消耗在客户端。平台侧承担客户端注册、Inventory 上报、策略与任务下发，以及选中 Skill 的服务端检测；服务器资源仍会随在线客户端数量、上报频率和待检测任务增加。

## 本地客户端运行治理查询（2026-10-14）

针对约 29,928 条 Hook 事件的客户端，在本地实际 SQLite 数据库上只读执行 `runtime_governance.view`：修复前首次测量为 1,834.8 ms；新增产品到达索引、流回执索引并改为逐产品最新记录查找后，一次新进程测量为 93.1 ms。随后另一进程连续五次为 103.15、9.26、9.44、8.94、10.11 ms。结果包含接口主体查询和响应对象组装，不含 HTTP、鉴权及网络；首轮和后续存在缓存差异，不作为生产延迟承诺或严格冷缓存对比。回归测试用 5,000 条合成事件验证查询使用索引定位、无历史全扫描或临时排序，并验证过期过滤与客户端隔离。

**English:** Read-only measurements of the runtime-governance view against a local client with about 29,928 Hook events were 1,834.8 ms before the fix and 93.1 ms in a fresh process after the fix. Five subsequent calls in another process took 103.15, 9.26, 9.44, 8.94 and 10.11 ms. These measure query and response assembly only, excluding HTTP, authentication and networking. Cache effects differ between runs; these are neither production latency guarantees nor a controlled cold-cache comparison.

## 客户端发现的智能体详情首屏（2026-10-14）

本地真实浏览器从智能体列表点击在线 Codex 的“详情”，经 `localhost:5173` 代理请求实际后端和 SQLite。开始点为详情点击处理函数；结束点为首屏五个请求成功完成、页面加载状态结束后的两次 `requestAnimationFrame`，作为完成渲染的近似测量。基础内容同样在工作区响应应用后等待两帧计时。它不包括尚未打开的行为审计、策略等标签页请求，也不是浏览器底层绘制追踪。

本次基线已包含上一节的运行治理修复。进一步优化最近会话：在三个来源内先筛选产品，Hook 和消息按会话预聚合，再合并统计；聚合读取索引中的身份与时间字段，问题正文只读取当前页所需记录。增加操作分页快照、产品会话和有效 Hook 记录索引，由启动迁移创建。Qoder 产品/入口映射、分页快照、过期过滤、内容权限和查看审计保持原有语义。

| 实际 HTTP 请求 / Request | 优化前中位数（3 次） | 优化后中位数（3 次） |
| --- | ---: | ---: |
| `agent-workspace?local_agent_id=codex` | 80.5 ms | 58.0 ms |
| `runtime-governance` | 106.4 ms | 85.4 ms |
| `aidr/status?include_retention=false` | 79.7 ms | 82.8 ms |
| `aidr/sessions?agent=codex&limit=5&include_questions=true` | 235.9 ms | 165.0 ms |
| `aidr/hook-policy` | 79.2 ms | 98.9 ms |
| 点击至基础内容渲染 / Click to base content | 116.9 ms | 85.2 ms |
| 点击至完整首屏渲染 / Click to complete overview | 262.9 ms | 187.9 ms |

完整首屏原始三次值：优化前 262.9、210.3、743.8 ms；最终方案 187.9、324.1、158.5 ms。请求时间包含实际 HTTP、鉴权和响应解析；各接口并发，不能相加作为页面耗时。其余四个首屏接口未发现需要本次修改的同类历史扫描问题，数值变化包含环境波动。数据库持续接收客户端上报，没有清缓存；三次样本不能推导 P95、并发承载能力或生产 SLA。

开发服务自动重启期间另有一次点击耗时 15,677.5 ms：点击时间为 11:05:38，后端新进程启动时间为 11:05:39；五个请求均等待约 15 秒。该记录保留在完整测量文件中，单列为开发服务重启等待，不纳入运行就绪后的三次样本。本地原始测量、查询计划及中间方案记录位于 `outputs/agent-detail-performance-20261014/`，不作为发布文件。

**English:** This measures an actual click from the Agent list into the discovered Codex overview against the local HTTP service. Completion means all five initial requests succeeded, loading ended and two animation frames elapsed; this approximates rendering, rather than recording the browser paint pipeline. The baseline already includes the runtime-governance fix. The new session query filters products before aggregation, combines indexed per-source session summaries and fetches only page-specific prompt bodies. Startup migrations add the required indexes. Snapshot pagination, Qoder aliases, expiry, content authorization and access auditing remain intact. Three completed overview samples changed from 262.9/210.3/743.8 ms to 187.9/324.1/158.5 ms. A separate 15,677.5 ms click coincided with the development server restarting and remains in the raw record. Other tabs, cold-cache behavior and production concurrency were not measured. No production latency guarantee is implied.

## 概览“查看记录”的关联查询（2026-10-14）

复查客户端概览两条 Codex Bash 记录（本地记录 30185、30193）时，执行前后 Hook 关联查询只使用客户端和过期状态索引，未按原生调用标识缩小范围。首次只读执行 `detail_entry` 为 2,464.03 ms，其中关联 SQL 为 2,444.21 ms；其余五次为 177.81–192.39 ms。新增按客户端、上报流、原生调用标识和记录 ID 排列的有效事件索引，查询直接匹配该索引表达式；其余用户、产品、会话、轮次、工具与子 Agent 条件继续校验。两条记录各三次只读复测为 14.66、1.54、2.47 ms 和 1.27、1.12、1.30 ms。以上不包含 HTTP 和鉴权，且未控制冷缓存。

浏览器通过实际“查看记录”入口打开截图中的两条记录，HTTP 请求为 44.0、46.5 ms；从点击处理函数开始到响应应用后的两帧为 69.6、67.4 ms。该指标近似记录卡片渲染完成，不包含再次展开审计正文的请求。另一次记录点击曾等待 21.73 秒，并伴随后端整体无响应；随后事件循环采样抓到安全扫描 Worker 心跳在主线程执行数据库提交、等待写锁，最长采样延迟约 28 秒。心跳改为同步路由，由 FastAPI 在线程池执行；并发回归用阻塞的心跳提交验证其他 HTTP 请求仍可响应，不改变心跳写入与鉴权语义。

**English:** Overview record pairing previously scanned a client's active Hook history. A read-only first call took 2,464.03 ms, of which 2,444.21 ms was the related-event query; subsequent calls took 177.81–192.39 ms. An active-event index on client, stream, native call and record ID reduced the measured handler calls to 1.12–14.66 ms while preserving all remaining identity checks. These exclude HTTP/authentication and are not controlled cold-cache benchmarks. Actual browser clicks for the two supplied records took 69.6 and 67.4 ms through two post-response animation frames, with HTTP durations of 44.0 and 46.5 ms; expanding protected content is a separate request. A separate 21.73-second stall prompted event-loop sampling, which identified synchronous database commits in the async security-worker heartbeat. The heartbeat now runs in FastAPI's worker thread pool. A concurrency regression verifies unrelated HTTP responsiveness while the heartbeat commit is blocked. Local measurements and diagnostic samples are in `outputs/record-entry-performance-20261014/`.

心跳修复后的最终浏览器复测，单条记录 HTTP 为 50.2 ms，点击至两帧后为 70.1 ms。继续采样约一分半未再捕获到超过 0.8 秒的事件循环延迟；这是本地短时观察，不能替代部署环境的持续负载验证。

**English:** The final browser check after the heartbeat fix measured 50.2 ms for HTTP and 70.1 ms from click through two animation frames. About 90 seconds of subsequent sampling captured no event-loop delay above 0.8 seconds. This is a short local observation, not sustained deployed-load validation.

## 生产使用建议

1. 以 Docker 部署文档中的 `16 vCPU / 32 GiB / 500 GiB SSD/NVMe` 作为生产初始基线；本次 8 vCPU 共享机数据用于定位测试环境中的瓶颈。
2. 单实例先把模型凭证并发、MCP 凭证并发和 Tool 并发设为 `5`；通过真实流量观察 P95、错误率、SQLite 锁等待和审计增长后再逐级调整。
3. 保持扫描 Worker `2` 和深度扫描并发 `2` 起步。增加并发前同时评估 CPU、内存、Sandbox 容量和磁盘临时空间。
4. 客户端默认采用增量监听和周期巡检；避免大量客户端在同一时刻执行全量扫描或上报。
5. 上线前用真实 Skill 大小、真实模型、真实 MCP Tool 和目标客户端系统做 30–60 分钟稳态测试。macOS/Windows 客户端的文件系统与安全软件开销不能用本次 Linux 数据替代。

原始结果保存在 `docs/benchmarks/2026-08-13-*.json`；可复现实验组件位于 `tests/performance/`。原始阶梯保留了超载后的连接错误，解读稳定区间时应以前一档完成后的成功率和延迟为准，不把服务已经过载后的后续连接失败当成有效吞吐。
