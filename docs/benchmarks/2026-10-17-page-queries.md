# 页面 API 查询优化（2026-10-17）

后续已在用户认可的后台负载下完成相同条件三组交替复测，详见
[2026-10-18 页面 API 对照结果](2026-10-18-page-queries.md)。本页保留首轮测量和随后环境检查的历史记录。

本轮检查客户端、智能体资产、概览、运行链路、AIDR 状态/会话和扫描任务的页面数据路径，
在隔离数据库实测九个 API。确认并修复客户端/Agent 列表的逐对象关联查询、概览重复读取
证据集合，以及普通链路事件页读取不使用的加密原文。

三组前后对照中，客户端列表、Agent 列表、智能体资产页和概览的 P95 均下降。
**本机环境未达到此前混合压测的空闲门槛，本报告不作为生产性能或网关无回退验收。**
初始 CPU 观测为 35.5%–55.9%，可用内存 2.52–2.71 GiB；保留所有轮次，不筛选最好结果。
确定性证据是查询次数减少、响应语义回归通过、数据库等待不再占用 Agent 页面所在事件循环。

### 2026-10-18 空闲复测前置检查

用户确认可保持空闲后，核验当前运行时代码和测试脚本与上述冻结版本一致。随后三轮各 30 秒
前置检查均未达标：CPU 中位值依次为 35.3%、35.45%、39.5%，峰值 42.9%、41.1%、46.3%；
可用内存最低分别为 2.69、2.75、2.74 GiB。采用此前空闲门槛：CPU 中位值不超过 25%、
峰值不超过 35%、可用内存至少 3 GiB，并检查 Swapins/Swapouts。
该次尝试未启动任何计时压测，未产生新的前后对照；上文耗时仍保留环境受限标记，业务代码未改。
详见[前置检查原始记录](2026-10-18-page-queries-environment.json)。

同日经用户授权正常退出 VS Code 后，确认其开发后端 `backend.dev_server --port 8001`
及工作进程退出，Codex 和网络代理保留。随后九轮各 30 秒检查（累计 4.5 分钟）中，
可用内存最低恢复到 4.33–4.55 GiB，交换活动均满足门槛；CPU 中位值仍为 27.8%–31.85%，
后八轮为 27.8%–29.4%，均高于 25%。该次尝试未启动三组页面 API 对照，没有新增 P95 结果，
也未放宽条件。当前代码与测试脚本仍和原冻结版本一致。操作及九轮完整数据见
[退出开发工具后的环境记录](2026-10-18-page-queries-retest-environment.json)。

## 修改与功能边界

- 客户端列表：每组最多 200 个已通过归属筛选的客户端，批量读取策略、用户 Hook 登记、Agent、
  Skill、恢复记录、最新事件和活跃 AIDR 告警。按 `client_id + agent_type + skill_name` 找最新事件；
  保留有效签名对应的治理路径去重计数、失败动作及活跃 AIDR 告警计数。
- Agent 列表及资产页：分组读取部门、外部网关名称和每个 Agent 最新的运行凭证摘要。
  最新凭证仍按原来的 ID 顺序选择，展示逻辑不替代运行时凭证有效性校验。
  两个完全同步的读取端点改由 FastAPI 工作线程执行，数据库等待不会占住事件循环。
- 概览：每类证据按可见客户端分组计数，再合并上报客户端集合；保留 24 小时窗口、上限时间、
  过期排除、跨来源客户端去重和各模块权限。动态扫描摘要只加载展示字段。
- 链路事件列表：只查询关联 payload 的标识和脱敏 JSON。原文查看仍由原入口鉴权并记录审计。
  在测试的 100 条/页、每条 64 KiB 原文字段下，每次避免向 Python 载入约 6.25 MiB 原文字段；
  磁盘 I/O 变化尚未量化，也未测出稳定延迟改善。

关联数据在每次请求内读取，没有跨请求策略/认证缓存。分页参数、列表返回字段和排序契约保持。
本轮只修改五个运行时文件：`backend/client_governance.py`、`backend/routers/clients.py`、
`backend/routers/agents.py`、`backend/routers/dashboard.py`、`backend/routers/runtime_traces.py`。
其余既有性能/回归修复保持，模型网关、采集提交、后台审计准入和数据库结构未改。

## 可复现实验

脚本：`tests/performance/benchmark_page_queries.py`。每次新建临时 SQLite/WAL 数据库，使用
冻结源码和相同规模数据：100 客户端、100 Agent、每客户端 10 个安装 Skill、50,000 客户端事件、
50,000 日志、50,000 Hook、1,000 链路事件及每条 64 KiB 合成原文字段、100 个已完成扫描任务。
Hook 会话查询有非空数据；每客户端 50 个会话。普通日志使用简化正文，不等同于真实来源采集。

每轮每 API 预热 2 次，正式请求 30 次。顺序为 B1/A1、A2/B2、B3/A3；全部串行，测试与压测不同时运行。
共 1,620 个计时请求及 108 个预热请求。所有请求返回 200，并校验客户端数量/告警、概览计数和会话分页。
SQL 观察器在两个版本中相同；P95 使用排序后 `floor((N-1)*0.95)` 项，再取三轮 P95 的中位值。

这里使用 FastAPI TestClient，经真实路由和响应序列化，认证依赖替换为合成管理员；路由内权限检查保留。
Registry 概览使用空摘要。**未测浏览器首屏、静态资源、网络传输、真实登录成本，也未重跑采集/审计/
补传/清理/网关并行的 100 客户端压测。** 验证范围为上述九条查询路径；长历史与生产数据规模尚待验证。

[原始样本、源码摘要与环境记录](2026-10-17-page-queries-results.json)；原始执行日志保留在
`outputs/performance/2026-10-17-page-queries/`。早期 discovery/candidate/fixture-check 数据不混入下表。

## 结果

单位：ms；变化为优化后相对优化前的 P95 中位值。

| 页面/API | 优化前 | 优化后 | 变化 | SQL 次数/请求 |
|---|---:|---:|---:|---:|
| 客户端列表 | 267.07 | 167.07 | -37.4% | 801 → 8 |
| Agent 列表（也供客户端页下拉使用） | 34.73 | 4.52 | -87.0% | 201 → 4 |
| 智能体资产页 | 102.51 | 70.75 | -31.0% | 205 → 8 |
| 平台概览 | 173.46 | 116.78 | -32.7% | 15 → 14 |
| 运行链路列表 | 2.92 | 2.79 | -4.6% | 4 → 4 |
| 运行链路事件 | 10.47 | 11.52 | +10.0% | 4 → 4 |
| 扫描任务列表 | 7.40 | 7.08 | -4.3% | 6 → 6 |
| AIDR 状态（不含保留统计） | 19.29 | 22.67 | +17.6% | 9 → 9 |
| AIDR 会话列表 | 5.80 | 5.96 | +2.9% | 46 → 46 |

重点页面逐组 P95（B → A）：

| 页面 | 第一组 | 第二组 | 第三组 |
|---|---:|---:|---:|
| 客户端列表 | 230.95 → 164.83 | 267.07 → 167.07 | 294.27 → 175.02 |
| Agent 列表 | 33.59 → 4.15 | 36.85 → 4.53 | 34.73 → 4.52 |
| 智能体资产页 | 107.67 → 68.99 | 98.15 → 71.42 | 102.51 → 70.75 |
| 平台概览 | 171.00 → 117.55 | 178.65 → 116.78 | 173.46 → 110.58 |

运行链路事件的耗时没有稳定改善；AIDR 状态也有尾部升高，不能宣称所有页面都更快。
未修改的会话列表仍有逐会话元数据查询，扫描任务列表仍同步恢复过期任务；本次小数据量查询
不是主要耗时，不凭代码形态扩大修改范围。全局审计、Skill 详情大报告、扫描任务大证据等路径
以及现场浏览器体验需另行测量，不能从本表外推为“没有性能问题”。

## 回归与人工验收

最终相关回归 **145 项全部通过**（68.81 秒）；Python 编译检查和 `git diff --check` 通过。
执行日志为 `outputs/performance/2026-10-17-page-queries/regression-final.log`。

```bash
uv run pytest -q tests/test_page_query_cost.py tests/test_agents_api.py \
  tests/test_clients_api.py tests/test_client_governance.py \
  tests/test_client_prompt_policy.py tests/test_client_compression_policy.py \
  tests/test_dashboard_overview.py tests/test_runtime_traces.py \
  tests/test_aidr_audit_admission.py tests/test_aidr_skill_write_cost.py \
  tests/test_aidr_skill_transactions.py tests/test_performance_correctness.py \
  tests/test_aidr_batch_sql.py
```

回归覆盖：归属隔离、200 对象分组边界、最新事件分组、活跃告警、治理签名/路径计数、
策略和部门变更立即可见、最新运行凭证选择、链路脱敏与原文授权、概览去重及时间窗口。
通过阻塞数据库查询并同时发出异步探测请求，验证两个 Agent 读取端点不会堵塞事件循环。
相关已有采集幂等、写入失败回滚、落盘 ACK、并发刷新及取消后准入释放测试纳入最终回归。

前端源文件未修改，未增加 UI 单元测试。用户人工验收 Todo（简体中文和英文各一遍）：

- 客户端列表和详情：Agent/Skill/恢复记录完整；告警数量与详情一致；修改策略后刷新立即生效。
- 智能体资产：名称、部门、凭证、在线状态及客户端关联正确；筛选和详情入口正常。
- 总览：切换不同权限账号，统计和最近活动范围正确；未保留/已过期证据不增加计数。
- 运行链路：事件翻页和脱敏内容正常；有权账号原文查看/审计正常，无权账号仍被拒绝。

**English:** Bounded related-data reads substantially reduce Client/Agent query counts. Three paired synthetic
API runs show lower medians for Client lists, Agent assets and the overview, but host CPU/memory pressure
prevents a production acceptance claim. Trace raw-column reads are reduced without a proven latency gain.
Browser rendering and concurrent gateway/ingestion performance were not measured in this experiment.
