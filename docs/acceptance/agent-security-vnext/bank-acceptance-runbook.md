# 银行环境 P7-12 现场执行手册

本手册把 BANK-01～BANK-15 转换为可执行顺序。它不构成变更授权；真实 Agent、MCP、Worker
中断、镜像升级和平台安装必须在银行批准的目标、账号、网络区和变更窗口内执行。

## 执行原则

1. 先填写不含敏感信息的 `bank-readiness.example.json` 副本并执行
   `check-agent-security-bank-readiness.py`；就绪检查通过后，再用两份正式干净离线包初始化独立证据工作区。
2. 不把登录口令、JWT、Worker Token、模型 Key、目标凭据、原始 Prompt/响应或个人信息写入普通证据。
3. 每一步先记录开始时间、执行人、目标和授权单号，再执行；失败也保留脱敏事实，不重复点击制造新任务。
4. `read_only` 可在预检窗口执行；`creates_records` 会创建策略、任务、审批、轨迹或导出记录；
   `authorized_target_calls` 会调用授权目标；`service_change` 和 `platform_install` 只能在变更窗口执行。
5. 每项操作前执行状态管理工具的 `start` 命令，确认操作人、授权类别和当前变更窗口并生成开工凭据；
   完成后立即用 `case` 命令关联相对证据路径。15 项通过只代表待复核，不能由执行人自行最终签署。

## 建议顺序

| 阶段 | 验收项 | 行为边界 |
|---|---|---|
| 0. 正式包预检 | BANK-01 | 只读；核对版本、Commit、双架构 provenance、包/镜像/SBOM 哈希 |
| 1. 双架构安装 | BANK-12、BANK-13 | 平台安装；分别在真实 amd64、arm64 主机执行安装、迁移、健康和基础回归 |
| 2. 权限和基线 | BANK-02、BANK-06、BANK-14 | 先只读核对角色和语义，再创建四环境治理样例 |
| 3. 功能链路 | BANK-03、BANK-05、BANK-08、BANK-09 | 创建 Mock/MCP/轨迹/导出记录；MCP 元数据扫描禁止真实 `tools/call` |
| 4. 授权目标 | BANK-04、BANK-07 | 取得目标所有者授权后调用真实 Agent，并演练 Kill Switch/只读阻断 |
| 5. Worker 韧性 | BANK-10、BANK-11 | 变更窗口内只操作 Worker，执行中断恢复、升级和明确回滚 |
| 6. 总回归 | BANK-15 | 对部署 Commit 执行仓库门禁、页面/API 抽样和文档一致性检查 |
| 7. 独立复核 | 全部 | 复核哈希和脱敏，执行最终 complete 命令和 `--require-complete` |

## 逐项操作与证据

### BANK-01 版本与供应链

- 核对初始化器生成的 `packages/package-inventory.json` 和两份 provenance。
- 记录平台版本页、`GET /api/v1/system/info`、`GET /api/v1/system/capabilities`、运行镜像 ID 与架构。
- 从 Worker 镜像读取 LICENSE、NOTICE、SBOM，并与 `deploy/agent-security/upstreams.lock.json` 对照。
- 证据目录：`supply-chain/`。任何版本、Commit、架构或哈希不一致都标记失败，不继续安装。

### BANK-12、BANK-13 双架构完整安装

- BANK-12 只在真实 amd64 主机使用正式 x86 包；BANK-13 只在真实 arm64 主机使用正式 ARM 包。
- 保存安装器输出、镜像加载输出、迁移/备份记录、`docker compose ps`、健康检查和首页/API 抽样。
- 证据目录分别为 `deployment/amd64/`、`deployment/arm64/`。模拟执行不能填写通过。

### BANK-02 默认启用与权限

- 在中英文界面确认“智能体安全”的扫描、基线与调用轨迹页面默认可见，不依赖页面 `.env` 开关。
- 分别使用管理员、安全审计和普通账号验证列表、详情、原始内容及导出权限；保存 200/403 和安全审计。
- 证据目录：`access-control/`。不得把会话 Cookie、Authorization Header 或响应中的原始敏感内容入包。

### BANK-03 Agent Mock 扫描

- 在隔离测试环境启动 `demo/agent-security-mock-target/` 固定样本。
- 在扫描工作台创建 Mock 目标和策略，先预览，再提交一次任务；等待终态后导出脱敏报告。
- 核对用例、Finding、引擎版本、停止原因、产物和 Finding→Trace/Event 关联。
- 证据目录：`business-cases/agent-mock/`。

### BANK-04 授权真实 Agent

- 归档授权单号、目标所有者、允许 Endpoint、TLS/出站边界、最大轮次/Token/费用/响应大小和评估模型。
- 使用密文凭据创建目标，先预览再执行一个最小任务；无权限、TLS 或评估模型失败必须 fail-closed。
- 证据目录：`business-cases/authorized-agent/`。只保存脱敏摘要、计量和错误码。

### BANK-05 MCP 元数据扫描

- 对已登记的银行 MCP Gateway 冻结 `tools/list` 元数据快照，执行 `mcp_metadata` 扫描。
- 核对描述注入、危险参数、风险操作和 Schema 漂移结果。
- 从 MCP 上游审计证明验收窗口内 `tools/call` 增量为 0；否则本项失败。
- 证据目录：`business-cases/mcp-metadata/`。

### BANK-06 环境与治理

- 分别创建 Sandbox、Test、Staging、Production 样例并保存任务预览。
- 验证 Production `active-full` 被服务端拒绝；`active-safe` 没有绑定的一次性审批时被拒绝，审批使用后不能重放。
- 证据目录：`governance/environments/`，包含稳定错误码、审批和安全审计。

### BANK-07 Kill Switch 与只读阻断

- 在授权隔离目标上启动可观察调用计数的长任务，管理员执行
  `POST /api/v1/agent-security/tasks/{task_id}/kill-switch`。
- 核对 Kill Switch 后没有新目标请求，任务停止原因和轨迹治理事件一致。
- 在只读 MCP Gateway 调用一个明确写 Tool，核对服务端阻断、上游零调用及 `mcp.error` 风险码。
- 证据目录：`governance/kill-switch-read-only/`。

### BANK-08 统一调用轨迹

- 按 `demo/agent-security-full-integration/` 运行完整 SDK/模型/MCP/知识检索链路。
- 按 `demo/agent-security-gateway-only/` 运行 combined 模式。
- 导出脱敏 JSON，核对完整链路的 Turn/Step/Call/Result 与 gateway-only 的 `gateway_partial`；后者不得出现伪造 Turn/Step。
- 证据目录：`runtime-traces/completeness/`。

### BANK-09 隐私与导出

- 普通角色验证列表、搜索、详情和导出只能看到脱敏投影，原始 Payload 接口返回 403。
- 管理员重新认证取得 5 分钟单次授权，完成一次原始 JSON 导出；同一授权重放必须失败。
- 导出脱敏 PDF，确认不含测试敏感值；保存导出哈希及授权/下载审计，不保存原始文件到普通证据包。
- 证据目录：`runtime-traces/privacy-exports/`。

### BANK-10 Worker 中断与恢复

- 先创建一个可重复的 Mock 任务并确认 Worker 已领取，然后只停止 Worker 服务。
- 等待租约到期，由管理员调用 `POST /api/v1/agent-security/workers/recover`，再启动 Worker。
- 核对 attempt、`lease_expired_retry`、恢复计数和最终终态；不得出现永久 running 或虚假 succeeded。
- 证据目录：`resilience/interruption-recovery/`。

### BANK-11 Worker 升级与回滚

- 记录明确的新旧镜像 ID，先运行 `verify-agent-security-worker-image.sh`。
- 仅重建 Worker，升级后运行一个固定任务；随后回到明确旧镜像并再次运行同一任务。
- 保存变更单、镜像 ID、Compose 状态和两个任务终态。证据目录：`resilience/upgrade-rollback/`。

### BANK-14 结果语义与 TC260

- 由普通角色和安全审计角色分别抽查中英文报告。
- 确认 `succeeded`/零 Finding 不显示为“安全”，缺证据控制项显示“未验证”，历史缺项不倒填。
- 确认 TC260 页面只展示已验证/部分覆盖/未覆盖及证据，不宣称认证或覆盖率。
- 证据目录：`review/report-semantics/`。

### BANK-15 回归与文档一致性

- 在与部署 Commit 相同的源码/依赖环境运行 `collect-agent-security-acceptance-evidence.sh --repo-regression`。
- 抽样核对页面、API、帮助中心和部署文档；保留后端、前端、构建、文档链接和依赖审计日志。
- 证据目录：`regression/`。测试通过不替代前述业务、双架构和韧性场景。

## 每项关闭和最终签署

每项先用 `manage-agent-security-bank-acceptance.py start` 和就绪配置生成不可重复的开工凭据；证据进入
对应目录后，再用 `manage-agent-security-bank-acceptance.py case` 更新结果。15 项全部通过后，
用 `issue` 命令维护 `remaining-issues.json`：GAP-01～GAP-04 必须以现场证据关闭；其他限制只能关闭，
或附脱敏风险审批证据、责任人、关闭条件和未来复核时间后限时接受。现场新增问题使用新的 `GAP-NN`
编号和 `--title` 登记，不能留在会议纪要或自由文本中。存在任何 open 项时最终门禁失败。

由独立复核人检查 `manifest.sha256`、原始敏感数据隔离和结构化遗留问题，准备脱敏签署证据、签署单号
和批准证据存储引用，再执行 `complete`。只填写复核人姓名不能完成；签署后修改用例或遗留项会自动撤销
旧签署并回到待复核。最后再次运行：

```bash
python3 scripts/validate-agent-security-acceptance-evidence.py \
  --evidence-dir /absolute/path/bank-acceptance \
  --require-complete
```

只有该命令成功、签署信息完整且证据包已进入银行批准的存储位置，才可勾选 P7-12。
