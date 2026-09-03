# 智能体安全下一版本验收证据包

本目录定义 P7-12 的银行验收矩阵、证据采集入口和交付格式。它把“仓库内部已验证”与
“银行验收环境已验证”分开记录，不能用本地 pytest、Mock、镜像自检或 Compose 配置渲染替代
客户环境部署和真实授权目标证据。

现场执行顺序、变更边界和逐项证据目录见[银行环境 P7-12 现场执行手册](bank-acceptance-runbook.md)；
对应的稳定机器映射见 `bank-acceptance-execution-plan.json`。

## 当前状态（2026-08-30）

- 当前工作树全量后端回归：`678 passed, 3 skipped`，共收集 681 项；同时产生 6243 条既有弃用告警，
  已作为升级兼容遗留风险记录，不能把“无失败”解释为“无技术债”。
- 前端帮助中心、i18n、功能开关、扫描/轨迹界面契约和生产构建：通过。
- Compose `agent-security` profile：配置渲染通过。
- 原项目 Compose 容器已停止 13 天且未作为运行验收证据；独立项目已完成 A7-03 本机韧性验收。
- 银行验收主机、安装包、管理员会话、Worker Secret、评估模型和授权目标：当前工作区未提供。
- A7-04 已完成本地双架构完整离线包验证：ARM64 原生执行、x86_64 模拟执行，详见
  `local-dual-architecture-offline-2026-08-30.md`。
- P7-12 和银行现场的双架构安装仍为“未验证”，不能用本地 A7-04 证据替代；A7-06 的逐项结果、
  证据和未满足原因已完备。

## 证据包结构

现场每次验收新建一个独立目录，不覆盖历史证据：

```text
agent-security-acceptance-<date>-<environment>/
  environment.txt
  git-state.txt
  compose-config.txt
  compose-ps.json
  backend-tests.log
  frontend-tests.log
  frontend-build.log
  worker-image-gate.log
  business-cases/
    agent-mock.json
    agent-authorized-target.redacted.json
    mcp-metadata.json
    runtime-trace.redacted.json
  resilience/
    interruption.md
    recovery.json
    upgrade.md
    rollback.md
  provenance/
    amd64/release-provenance.json
    arm64/release-provenance.json
  packages/
    package-inventory.json
  screenshots/
  remaining-issues.json
  acceptance-results.json
  manifest.sha256
```

文件名可以按现场规范调整，但必须保留环境、版本、时间、执行人、输入边界、实际结果和证据哈希。
原始 Prompt、响应、Tool 参数、目标凭据、Worker Token、模型 Key、管理员 JWT 和个人信息不得进入
普通证据包；确需原始内容时，使用平台的原始授权与审计流程单独保管。

## 正式验收工作区初始化

进场前先复制 `bank-readiness.example.json` 并填写非敏感的环境、人员、角色、授权单、真实主机、
正式包、目标登记号和证据存储引用。禁止在该文件中填写密码、Token、Key、Cookie 或密文凭据。
只读就绪检查器会校验前置输入和两份正式包的 provenance，但不会连接或改变目标环境：

```bash
python3 scripts/check-agent-security-bank-readiness.py \
  --config /absolute/path/bank-readiness.json
```

只有输出 `"ready": true` 才进入工作区初始化；这仅表示输入齐备，不表示任何 BANK 用例通过，
也不替代银行授权、真实主机架构确认和现场执行。

拿到正式 x86_64、ARM64 离线包后，先初始化受控证据目录。初始化器只读取两个包内的
`release-provenance.json` 并计算完整包哈希，不解包镜像，也不连接或改变目标环境：

```bash
python3 scripts/initialize-agent-security-bank-acceptance.py \
  --output-dir /absolute/empty/path/bank-acceptance \
  --environment bank-staging-a \
  --platform-version v7.12.0 \
  --git-commit <full-commit> \
  --operator <authorized-operator> \
  --reviewer <independent-reviewer> \
  --owner <acceptance-owner> \
  --amd64-package /absolute/path/agent-manager_v7.12.0_x86.tar.gz \
  --arm64-package /absolute/path/agent-manager_v7.12.0_arm.tar.gz
```

只有两个包同时满足版本、Commit、架构、归档布局、`source_mode=git_clone` 和
`worktree_dirty=false` 才会创建工作区。生成内容包括两份 provenance、完整包文件名/大小/SHA-256、
15 项 `unverified` 结果、逐项关闭条件和 `manifest.sha256`。初始化后可立即执行进行中校验：

```bash
python3 scripts/validate-agent-security-acceptance-evidence.py \
  --evidence-dir /absolute/empty/path/bank-acceptance
```

进行中状态允许 `completed_at=null` 和 `sensitive_data_reviewed=false`；这不表示通过。
最终 `--require-complete` 仍要求完成时间、独立复核、敏感信息复核、15 项全部通过及全部证据哈希一致。

逐项执行后不要手工维护汇总和哈希，使用状态管理工具。例如 BANK-03 通过并引用两份脱敏证据：

```bash
python3 scripts/manage-agent-security-bank-acceptance.py start \
  --evidence-dir /absolute/empty/path/bank-acceptance \
  --readiness-config /absolute/path/bank-readiness.json \
  --case-id BANK-03 \
  --operator <authorized-operator>

python3 scripts/manage-agent-security-bank-acceptance.py case \
  --evidence-dir /absolute/empty/path/bank-acceptance \
  --case-id BANK-03 \
  --status passed \
  --evidence business-cases/agent-mock.json \
  --evidence business-cases/agent-mock.sha256.txt
```

`start` 必须在用例动作之前执行。它会重新验证就绪配置和双架构包，核对环境、版本、Commit、
操作人及当前变更窗口，并按用例固定的行为类别选择对应授权引用；配置在校验期间发生变化会被拒绝。
生成的开工凭据只包含配置 SHA-256、授权/目标引用和时间，不复制配置或任何密文。重复开工、错误操作人、
窗口外执行都会失败。最终门禁要求 BANK-01～BANK-15 各有一份开工凭据，不能直接补写通过结果绕过授权。

失败或未验证状态必须同时提供 `--reason`、`--owner` 和 `--closure-condition`；`not_applicable`
必须提供 `--rationale`，但 P7-12 的最终门禁不接受任何必验项为不适用。每次成功更新都会自动重算
四类状态汇总和 `manifest.sha256`，再调用校验器；校验失败会恢复原结果和原哈希。

15 项全部有证据并标记通过后，结果只进入 `pending_review`。由初始化时记录的独立复核人完成脱敏检查后：

初始化器还会生成 `remaining-issues.json`。GAP-01～GAP-04 是现场完成性缺口，最终签署前必须以证据关闭，
不能通过风险接受绕过；GAP-05～GAP-07 等已知限制可以关闭，或由有权人员提供脱敏审批证据、责任人、
关闭条件和未来复核时间后限时接受。例如：

```bash
python3 scripts/manage-agent-security-bank-acceptance.py issue \
  --evidence-dir /absolute/empty/path/bank-acceptance \
  --issue-id GAP-01 \
  --status resolved \
  --resolution "BANK-12 and BANK-13 field evidence accepted." \
  --evidence deployment/dual-architecture-review.redacted.json

python3 scripts/manage-agent-security-bank-acceptance.py issue \
  --evidence-dir /absolute/empty/path/bank-acceptance \
  --issue-id GAP-05 \
  --status accepted \
  --reason "Socket-level pinning is not enabled in this release." \
  --owner <risk-owner> \
  --closure-condition "Deploy pinned transport or renew acceptance after review." \
  --risk-acceptance-reference <approved-reference> \
  --review-at <future-ISO-8601-with-timezone> \
  --evidence review/gap-05-risk-acceptance.redacted.json
```

现场发现的新问题也使用 `GAP-NN` 编号和 `--title` 加入同一文件。任何 `open` 项都会阻断最终签署；
`resolved` 和 `accepted` 都必须引用进入哈希清单的证据，不能只写自由文本。

确认遗留问题满足上述门禁后，再由独立复核人执行：

```bash
python3 scripts/manage-agent-security-bank-acceptance.py complete \
  --evidence-dir /absolute/empty/path/bank-acceptance \
  --reviewer <independent-reviewer> \
  --confirm-sensitive-data-reviewed \
  --signoff-reference <approved-signoff-reference> \
  --evidence-storage-reference <approved-storage-reference> \
  --signoff-evidence review/final-signoff.redacted.json
```

该命令设置完成时间、敏感信息复核和总体结论，并在写入后执行 `--require-complete`；任何校验失败都会回滚。
最终签署必须引用至少一份已纳入哈希的脱敏签署证据，以及银行批准的签署单号和证据存储引用；只输入
复核人姓名不能完成。签署后如果重新修改任一用例或遗留问题，工具会清除旧签署、完成时间和敏感信息
复核状态，重新回到 `pending_review` 或失败状态，必须再次独立复核。
机器总体结论只使用 `unverified`、`failed`、`pending_review`、`passed`，不能用自由文本绕过必验项。

## 自动采集入口

仓库提供只读优先的采集脚本：

```bash
./scripts/collect-agent-security-acceptance-evidence.sh \
  --output-dir /absolute/controlled/path/agent-security-acceptance-2026-08-30-bank \
  --repo-regression
```

在源码仓库或具备开发依赖的离线目录中，可以先运行 10 项内部总体验收回归；输出包含逐场景映射、
JUnit、执行日志和哈希清单，并固定标记为“不等同于银行环境”：

```bash
./scripts/run-agent-security-e2e-regression.sh \
  --output-dir /absolute/empty/path/agent-security-e2e
```

场景到测试的稳定映射保存在 `e2e-regression-cases.json`。只有脚本选中的所有测试通过后才会生成
`e2e-results.json`，因此失败或中断不会留下虚假的全通过汇总。

在已启动 Worker 的目标主机增加运行检查；脚本不会启动、停止、升级或恢复服务：

```bash
./scripts/collect-agent-security-acceptance-evidence.sh \
  --output-dir /absolute/controlled/path/agent-security-runtime-2026-08-30-bank \
  --runtime-check \
  --compose-project agent-manager \
  --worker-image agent-manager-security-worker:<tag> \
  --worker-arch <amd64-or-arm64>
```

采集脚本拒绝相对目录和非空输出目录，避免覆盖既有证据。配置检查使用空插值文件和
`--no-env-resolution`，运行状态只读取 Docker Compose 项目/服务标签；它不读取 `.env`，不导出容器环境变量，
也不接收任何 Token。启用 `--repo-regression` 时，源码仓库执行 Git 差异检查；不含 `.git` 的正式离线包
改为校验 `release-provenance.json` 必须来自干净的 `git_clone`，不会因缺失 Git 元数据误失败。该选项仍要求
现场具备仓库测试所需的 Python、Node.js 和依赖环境，不属于普通离线安装的必需步骤。业务任务、中断恢复、
升级回滚和双架构完整安装仍需按照
[验收矩阵](bank-acceptance-matrix.md)由授权人员执行并补充证据。

未使用初始化器时，现场可参考 `acceptance-results.example.json` 生成 `acceptance-results.json`。每个通过项必须引用
至少一个已进入 `manifest.sha256` 的相对路径证据；失败或未验证项必须写明原因、责任人和关闭条件。
业务证据、结果文件和敏感信息复核完成后，重新生成最终哈希清单，再执行机器校验：

```bash
./scripts/finalize-agent-security-acceptance-evidence.sh \
  --evidence-dir /absolute/controlled/path/agent-security-acceptance-2026-08-30-bank

python3 scripts/validate-agent-security-acceptance-evidence.py \
  --evidence-dir /absolute/controlled/path/agent-security-acceptance-2026-08-30-bank \
  --require-complete
```

最终封包脚本拒绝相对目录、缺失结果文件和符号链接，并把结果文件本身纳入哈希。`--require-complete`
会拒绝缺失的 15 项、重复项、缺失开工凭据、任何非通过项、未关闭遗留问题、缺失签署证据、空证据、路径逃逸、缺失文件、哈希不一致、占位字段、
无时区或倒序时间、执行人与复核人相同、未完成敏感信息复核，以及在存在未完成项时填写的“通过”
总体结论。它还会核对 x86_64 与 ARM64 两份 `release-provenance.json` 的版本、Commit 和架构；正式
完成时，两份产物必须来自干净的 `git_clone` 构建。P7-12 的 15 项都是必验项，`不适用` 可以用于
中间记录，但不能通过最终完成校验。最终校验器自身也会遍历并拒绝证据根目录、文件或父目录中的
符号链接，不依赖封包脚本先执行，避免手工 manifest 通过链接读取验收目录之外的内容。校验器还会
比对 manifest 与验收目录中的完整普通文件集合，并复算每一个条目的 SHA-256；因此未列入 manifest 的
额外文件、manifest 中不存在的文件，以及没有被任何 BANK 用例直接引用但已经被篡改的附件都会失败。
对于 JSON、日志、文本、Markdown、YAML、CSV、HTML 和 XML 等 UTF-8 文本附件，校验器还会拒绝
明显的私钥头、Bearer Authorization、Cookie、JWT、带账号口令的 URL，以及非脱敏密码、Secret、Token
或 API Key 字段；错误只报告文件和类别，不回显命中内容。单个文本附件超过 64 MiB 时要求先拆分后复核，
避免以超大文件绕过扫描。该强特征检查不解析 PDF、图片等二进制附件，也不能识别所有业务秘密，不能替代
独立复核人的人工敏感信息检查。

## 完成判定

只有以下条件同时满足，才可勾选 P7-12：

1. 银行验收环境的目标版本和架构已确认，核心 Compose 服务与 Worker 健康。
2. Agent Mock、至少一个授权真实 Agent、MCP 元数据扫描和统一轨迹场景均有脱敏证据。
3. Worker 中断、租约恢复、升级和明确回滚演练有任务级状态证据。
4. x86_64 与 ARM64 正式完整离线包分别在目标架构主机安装并回归；Worker 单镜像验证不替代它。
5. 后端、前端、文档/API 一致性通过，所有未满足项写明原因、责任人和关闭条件。
6. GAP-01～GAP-04 已用现场证据关闭；其他遗留项已关闭或具有脱敏、限时、可复核的风险接受记录。
7. 证据清单哈希已生成，复核人确认没有明文敏感信息，并提供脱敏签署证据、签署引用和批准存储引用。
8. 上述校验器使用 `--require-complete` 返回成功，且汇总与 15 项逐项结果一致；签署后没有再次修改结果或遗留项。
