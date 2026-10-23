# 页面 API 三组交替复测（2026-10-18）

按用户认可的当前后台负载运行，保留 Codex 和网络代理；VS Code 与闲置开发后端已退出。
三组共六轮按“优化前→优化后、优化后→优化前、优化前→优化后”串行完成。
客户端列表、Agent 列表、智能体资产页和概览的 P95 在三组中均下降，支持这些查询优化
在本次条件下有效；不能把结果解释为无后台负载的容量验收或浏览器首屏性能。

## 条件与正确性

- 与 [10 月 17 日测试](2026-10-17-page-queries.md) 使用相同的优化前/后源码快照，
  逐文件 SHA-256 校验一致；测试脚本也未变，运行时业务代码没有新增修改。
- 每轮使用新建的临时 SQLite/WAL 数据库：100 客户端、100 Agent、1,000 个安装 Skill、
  50,000 客户端事件、50,000 日志、50,000 Hook、1,000 链路事件（每条合成原文字段 64 KiB）、
  100 个已完成扫描任务。每客户端有 50 个非空 Hook 会话。
- 每个接口预热 2 次、正式采样 30 次；9 个接口 × 6 轮，共 1,620 个计时请求和 108 个预热请求。
  全部返回 200，客户端数量/告警数、概览证据计数和会话分页断言通过。
- P95 为排序后 `floor((N-1)*0.95)` 项，下表取三轮 P95 的中位值，未合并样本计算总体 P95。
- 测量包含 TestClient 路由和响应序列化；认证依赖使用合成管理员，路由权限检查保留，
  Registry 概览使用空摘要。没有真实网络传输、浏览器渲染或采集/补传/审计/清理/网关并行流量。
- 源码未变，沿用该版本已通过的 145 项相关回归测试；本轮执行压测和返回值校验，未重复运行 pytest。

## P95 对比

单位：ms。“变化”为优化后相对优化前的变化。

| 页面/API | 优化前 | 优化后 | 变化 | SQL 次数/请求 |
|---|---:|---:|---:|---:|
| 客户端列表 | 212.64 | 159.68 | -24.9% | 801 → 8 |
| Agent 列表 | 33.38 | 4.47 | -86.6% | 201 → 4 |
| 智能体资产页 | 96.33 | 71.24 | -26.0% | 205 → 8 |
| 平台概览 | 151.42 | 99.10 | -34.6% | 15 → 14 |
| 运行链路列表 | 2.72 | 2.81 | +3.4% | 4 → 4 |
| 运行链路事件 | 9.95 | 9.85 | -1.0% | 4 → 4 |
| 扫描任务列表 | 6.62 | 6.75 | +1.9% | 6 → 6 |
| AIDR 状态（不含保留统计） | 16.14 | 16.33 | +1.1% | 9 → 9 |
| AIDR 会话列表 | 6.02 | 5.88 | -2.3% | 46 → 46 |

四个主要接口的逐组结果（优化前 → 优化后）：

| 页面/API | 第一组 | 第二组 | 第三组 |
|---|---:|---:|---:|
| 客户端列表 | 213.94 → 159.68 | 204.60 → 159.96 | 212.64 → 159.40 |
| Agent 列表 | 32.66 → 4.44 | 36.64 → 4.47 | 33.38 → 4.49 |
| 智能体资产页 | 98.91 → 71.27 | 95.59 → 71.24 | 96.33 → 69.79 |
| 平台概览 | 152.34 → 99.52 | 151.42 → 98.25 | 150.68 → 99.10 |

客户端列表优化后的三轮 P95 在 159.40–159.96 ms 之间，概览为 98.25–99.52 ms。
其余接口三轮中位值差异均小于 0.2 ms，不足以据此判断显著改善或回退。
例如会话列表优化前第三轮为 8.54 ms，另外两轮约 5.84/6.02 ms，不能把单次尾部偏高算作稳定收益。
链路事件页减少原文载入的实现仍有效，但本轮也没有测出明显的延迟提升。

与上一轮环境受限测试相比，主要优化方向一致，具体百分比发生变化：客户端列表从上次约 37%
变为本轮约 25%。不同环境/有限采样下的百分比不是固定产品收益，应用本轮成对结果评估本次运行。

## 环境记录与限制

开始前 CPU 实际为 **28.9%–31.1%**，不是始终固定在 28%–29%。完整子进程运行期间
（包含建库、数据准备和测量）的总 CPU 中位值为 **35.8%–36.4%**，峰值最高 44.8%，其中包含压测自身。
每 2 秒记录一次运行期间资源数据；可读取进程的外部 CPU 统计不包含无权限读取的进程，不能代替总 CPU。

| 运行 | 开始前 CPU | 运行期间总 CPU 中位值 | 最低可用内存 GiB | 换入 MiB | 换出 MiB |
|---|---:|---:|---:|---:|---:|
| 前 1 | 29.4% | 36.25% | 4.19 | 1.56 | 0 |
| 后 1 | 29.3% | 36.20% | 4.20 | 0.25 | 0 |
| 后 2 | 31.1% | 35.80% | 4.22 | 0.13 | 0 |
| 前 2 | 30.4% | 35.90% | 4.23 | 1.31 | 0 |
| 前 3 | 29.7% | 36.40% | 4.26 | 0.19 | 0 |
| 后 3 | 28.9% | 35.90% | 4.29 | 0 | 0 |

交换量来自 macOS `vm_stat` 的 Swapins/Swapouts × 页大小。六轮没有换出，单轮换入最多 1.56 MiB。
这些数据表明本轮未重现此前明显内存紧张，但系统服务、Codex 和代理仍在共享 CPU，
每接口每轮仅 30 个正式样本、共三组成对运行，不能推导长期 P95、生产规模或统计显著性。
本轮没有网关请求，因此不提供新的网关 P95 或网关无回退结论。

完整样本、逐组结果、源码摘要和环境数据：[结果 JSON](2026-10-18-page-queries-results.json)。
可复现驱动及原始日志：`outputs/performance/2026-10-18-page-queries-current/`；
被环境检查挡住的先前尝试没有计时样本，不计入本轮六次运行。

**English:** All three alternating pairs show lower P95 for Client lists, Agent lists/assets and the overview.
The same frozen code, fixture sizes and request counts were retained. Actual starting host CPU was 28.9–31.1%,
with Codex and the proxy running; these are background-loaded TestClient API results, not browser, network,
production-capacity or mixed gateway-load acceptance. Other endpoints show small median differences without
evidence of a meaningful latency improvement or regression.

## 页面优化的功能审查（2026-10-18）

审查基线为 `2026-10-17-page-queries/before-source`，范围为本次页面优化的五个业务文件：
`client_governance.py`、`routers/clients.py`、`routers/agents.py`、`routers/dashboard.py`、
`routers/runtime_traces.py`。没有把工作区内更早的 AIDR、保留清理和模型网关修改算作本次页面改动。

未发现本次页面优化引入的已确认功能回归。新增
[`test_page_query_contracts.py`](../../tests/test_page_query_contracts.py) 的 10 项契约测试，
补充原有查询成本、功能和并发测试。审查与验证重点如下：

| 方面 | 审查结论与覆盖 |
|---|---|
| 权限 | 批量关联查询使用已通过所有者筛选的客户端/Agent；真实 JWT、数据库角色授权及管理审计中间件覆盖权限撤回、账号禁用、会话替换、角色降级和所有者变更。无权查看的客户端详情继续返回 404。 |
| 策略实时读取 | 无跨请求缓存；保存后的下一次列表、详情及客户端策略请求读取新版本，过期预览仍返回 409。默认继承、单客户端覆盖、Hook 注册及模型路由受原有策略边界约束。配置在下一次服务端读取时生效，离线客户端重连后同步。 |
| 告警计数 | 旧协议按每个客户端、Agent 类型和 Skill 的最新事件判断；已启用的分类治理按有效签名及受影响路径统计；两者均叠加 JSON active=true/1 的 AIDR 告警，字符串 "true" 不计入。覆盖恢复事件、同名跨 Agent/客户端、失效签名、执行失败、仅记录动作、协议切换和告警解除。 |
| 概览统计 | 保留模块权限、所有者范围、24 小时边界、过期排除及日志/Hook 客户端去重；MCP/模型拦截计数逻辑未改变。只减少读取列和重复扫描。 |
| 响应及隐私 | Agent 跨 200 条分批边界保持关联正确，凭证删除和网关改名下一次读取可见；响应不含网关密钥。链路事件页只读取脱敏字段，原文接口继续单独鉴权，真实 JWT 撤回原文权限后立即拒绝。 |
| 写入与并发 | 注册、库存和状态写入仍提交后构造响应；审查范围未改变采集 ACK、幂等键、并发版本或租约逻辑。同步 Agent 列表在工作线程读取数据库，等待测试覆盖其不阻塞事件循环。 |

五个业务文件的 SHA-256 与本报告的优化后压测快照一致，本次审查仅补充测试和验证记录。
本节的功能验证不能替代高并发混合压测；仍以本文前述条件限定 P95 结论。

验证执行记录：第一组 207 项中 206 项通过，新增所有者隔离测试误把既有的 404 预期写成 403；
核对优化前实现后修正测试预期。第二组重新执行全部 10 项新测试，并加入 14 项外部网关和
3 项 Hook 注册测试，27 项全部通过。两组去重后 **224 项均已通过**，未修改业务代码来迁就测试。
`git diff --check` 和新增测试文件的 Python 编译检查通过。执行命令：

```bash
uv run pytest -q tests/test_page_query_contracts.py tests/test_page_query_cost.py \
  tests/test_agents_api.py tests/test_clients_api.py tests/test_client_governance.py \
  tests/test_client_prompt_policy.py tests/test_client_compression_policy.py \
  tests/test_runtime_governance.py tests/test_dashboard_overview.py tests/test_runtime_traces.py \
  tests/test_iam.py tests/test_aidr_audit_admission.py tests/test_aidr_skill_write_cost.py \
  tests/test_aidr_skill_transactions.py tests/test_performance_correctness.py tests/test_aidr_batch_sql.py \
  --disable-warnings --tb=short
uv run pytest -q tests/test_page_query_contracts.py tests/test_external_ai_gateway.py \
  tests/test_hook_enrollment.py --disable-warnings --tb=short
```

受影响 UI 的人工验证 Todo（本轮无前端代码修改、无 UI 单元测试）：

- [ ] 中文和英文客户端列表/详情：核对告警解除、策略保存后的刷新、库存及恢复记录。
- [ ] Agent 列表/资产页：核对搜索、筛选、抽屉关联信息和权限降级后的访问。
- [ ] 概览：切换不同权限账号，核对模块可见性、证据数量与待办计数。
- [ ] 运行链路：核对筛选分页、脱敏展示和原文权限撤回后的提示。

**English:** The review found no confirmed regression introduced by the five page-query changes.
Ten additional contract cases exercise real JWT/IAM checks, next-request policy freshness, alert transitions,
batch boundaries and raw-trace access revocation. Runtime sources still match the benchmark snapshot.
All 224 distinct selected tests passed after correcting one new test's expected ownership-denial status
to the existing 404 contract. Browser interaction and mixed-load performance remain separate verification scopes.
