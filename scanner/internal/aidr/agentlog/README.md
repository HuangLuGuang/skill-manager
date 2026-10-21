# Agent log ingestion / Agent 日志增量读取

## Product adapters / 产品适配器

`adapters.go` registers product implementations in `adapter_*.go`. Each product owns parsing, metadata,
identity recovery, source selection and Skill evidence semantics. `read.go` and `projection.go` share
budgets, checkpoints and event projection; the local store owns deduplication and delivery.
TeleAgent selects its own read-only SQLite snapshot reader, revisiting mutable rows in bounded cycles.
Unchanged snapshots preserve event identities across cycles and restarts. Completed assistant text and
tool results use the same capture policy as existing products. Pending rows are revisited in later cycles.
User messages identify turns by native message ID; assistant records follow only a same-session user parent.
Each read batch may carry up to 128 `turn_links` beside unchanged events. The store atomically queues new
links with the checkpoint, including links to acknowledged event tombstones whose bodies were released.
The platform verifies identity/digest and enriches retained views without changing raw evidence. Hook
correlation uses the exact native tool call ID and identity scope; ambiguous or missing parents remain unlinked.
The native review bridge and deployment boundaries are documented in
[external integration](../../../../docs/external-agent-integration.md#aidr-产品适配器与-teleagent--product-adapters-and-teleagent).

各产品通过注册表提供原生格式与身份语义；公共层复用预算、检查点和事件投影。
TeleAgent 的 SQLite 记录会原地更新，使用有界周期复查和稳定身份去重，不能按 JSONL 字节追加读取。
用户消息 ID 标识轮次，助手记录只沿同会话内的用户父消息归属；每批最多补传 128 条轮次关联元数据。
关联与检查点、上传队列原子落盘；历史正文已收到 ACK 并释放后仍可补关联，不恢复正文或生成重复事件。
平台校验身份与摘要后补充保留记录的展示，Hook 按原生工具调用 ID 精确关联；缺失、冲突与过期记录不猜测归属。
现有 JSONL/快照产品的检查点与逻辑事件身份保留兼容。

P1-01 provides a read-only Go adapter and `agent-manager-client agent-log-read` CLI. It does not start or send messages to Agents. This is local log evidence; process association remains `unknown`.

P1-01 提供只读 Go 适配器和 CLI。P1 可读审计补强输出工具名、调用/会话/轮次、时间、来源证据及经过白名单、平台脱敏策略和长度限制的 `behavior`。命令、工作目录和明确的文件/URL 目标可读；Prompt、文件正文、完整结果和未知参数结构不复制。日志结果分别表示明确退出码、错误标记、取消或未知，不能作为系统成功或阻断证明。详见 [可读审计验收](../../../../experiments/aidr-agentlog/READABLE_ACCEPTANCE.md)。

## Usage / 使用

```sh
cd scanner
go build -o /tmp/agent-manager-client ./cmd/agent-manager-client
/tmp/agent-manager-client agent-log-read --agent claude
/tmp/agent-manager-client agent-log-read --agent codex
/tmp/agent-manager-client agent-log-read --agent codex \
  --root /absolute/allowed/log/root --file /absolute/allowed/log/root/rollout.jsonl
```

Default roots are `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`, and `$CODEX_HOME/sessions` or `~/.codex/sessions`. Explicit roots and files must be absolute and have no symlink components. Other users' homes are not searched. Archived Codex JSONL can be selected explicitly with `--root`; SQLite catalogs are not part of the current adapter.

默认回溯最近 24 小时；`--since RFC3339` 可指定范围。读取早期元数据以恢复会话上下文，但不输出范围外的工具事件。默认每次调用读取/发现预算 4 MiB / 500 个事件 / 5 秒，发现最多 64 个文件 / 10,000 个目录项、深度 32；先到上限就报告 partial。目录预算截断时未返回的文件尚未覆盖，可选择更具体的根或调整 `--max-files`。不是自动后台采集服务；stdout 消费者的等待不包含在读取预算中，CLI 保留系统默认信号终止行为。

每行默认上限 2 MiB（显式调整 `--max-line-bytes`，硬上限 4 MiB）。超限记录按至多 64 KiB 分块丢弃，游标保留正在丢弃的状态、记录起点；按轮次字节预算暂停并继续，后续正常记录仍可读取。始终报告 `aidr_log_record_too_large`、跳过字节数和范围，不显示 complete。范围最多保留 32 段，多余细节通过 `gap_details_truncated` 声明。合法 JSON 的未知记录可隔离跳过并继续：未知可选 event_msg 不含身份/工具字段时保留已有上下文；未知关键形态、顶层未知类型或含身份/工具字段的未知记录清空会话/轮次/调用绑定，只能由后续明确元数据恢复。无效 JSON、已知关键记录结构损坏仍停留坏记录起点，等待修复。超大行可能隐藏身份改变，因此跳过时清空关联。隔离记录范围及 SHA256 摘要随游标保留最多 32 段，超过后标记细节截断；持久缺口使覆盖保持 partial，重复轮询不再次消费记录或增加范围。

## Cursor and evidence contract / 游标与证据契约

- `ReadIncremental(ctx, source, cursor, budget, since)` returns events, coverage and a proposed cursor. A caller must commit events and cursor together; durable storage and crash recovery belong to P1-02.
- CLI `--file ... --cursor cursor.json` accepts a prior **cursor object**, not the whole batch. The CLI never overwrites it. Re-reading with the committed offset does not replay prior records. Keep checkpoints per source; never use an upload ACK as a file read offset.
- File identity is device/inode on Darwin/Linux, volume/file index on Windows. Rotation or observed truncation increments generation, clears parser context, rereads and marks a sticky gap. The preceding 256 committed bytes detect changed checkpoint content. This does not certify detection of arbitrary in-place edits outside the checkpoint region, or a truncate/regrow operation that reproduces that region between polls.
- Offsets, generation and source sequence use decimal JSON strings. Sequence = record byte offset + block index; `record_offset` is the exact record start. `event_id` identifies source/generation/position/content evidence. `logical_event_id` identifies source/agent/session/turn/call/kind/tool/outcome/content; repeated evidence can share the logical ID. `logical_call_id` links only native scoped call IDs. Cross-file/process/Agent inference is not made.
- Pending tool calls retain session/turn/tool bindings in the persisted cursor across read budgets and restarts. Completed calls retain a 64-entry replay/conflict cache and can be reclaimed; unfinished calls are never evicted to make room. The total bound is 512 entries. Capacity exhaustion reports sticky `aidr_log_call_capacity`; conflicting call IDs report `aidr_log_call_conflict`; results lacking a reliable binding report `aidr_log_call_unresolved`. These gaps keep coverage partial, including on subsequent reads. Legacy cursors without completion/digest fields remain accepted.
- 未完成工具调用的会话/轮次/工具关联随游标持久化，跨读取预算和重启保留。完成后保留最近 64 条用于重复/冲突检查，可回收；总容量 512 条，容量耗尽、call ID 冲突和无法关联结果分别报告上述持久 gap，覆盖保持 partial。旧游标缺少完成状态和摘要仍可读取。
- `received_at` is local reader receipt time, not server receipt time, and is excluded from origin/logical identity. No device or organization identity is accepted from a source log; P1-03 must add authenticated transport context.
- A half line retains its start offset. Appends finish it on the next read. Persistent gap codes survive later healthy reads; begin a new explicit collection scope to discard old coverage context. A missing or unreadable file leaves the prior cursor intact.
- `complete` means the bounded file snapshot was consumed within the declared time range and recognized types, not that all Agent activity was logged. Non-tool message/usage records are counted as ignored. Agent versions are metadata; supported record shapes are parsed across releases. Only actual format/read failures affect coverage. Valid unknown variants are quarantined with bounded persistent ranges and digests; malformed recognized critical records and invalid JSON retain their checkpoint. Unknown event metadata carrying no identity/tool fields preserves context; other unknown shapes invalidate bindings until explicit metadata restores context.

This is the P1-01 local subset of P0-02. Authenticated device/organization envelopes, capability transport and batch ACK are prerequisites for P1-03, not implemented by this package. No broader P0/P1 completion is claimed.

## Compatibility and verification / 兼容与验证

Codex `item_completed` metadata is capability-gated: completion schema 1 collects MCP/ImageView; schema 2 also collects CommandExecution as `Bash`, preserving native status and an optional signed 32-bit exit code. No command/output body is copied into completion evidence. Upgrades replay bounded history with versioned local checkpoints; stable MCP/image identities remain unchanged. Completion metadata is separate from ordinary results and never fabricates an end Hook.

Codex 原生完成元数据按协商版本采集：第一版支持 MCP/图片，第二版增加 CommandExecution（Hook 名称 `Bash`），保留宿主状态和可选 32 位整数退出码，不复制命令或输出正文。升级通过分版本本地检查点有界重读历史，MCP/图片身份不变。完成元数据与普通结果分开，不伪造结束 Hook。

按记录格式决定解析能力，版本号仅保留为来源元数据。陌生版本不会新增覆盖缺口；旧游标的 `aidr_log_version_unverified` 保留历史但不影响当前覆盖状态，真实格式错误继续报告。运行状态的解析支持来自读取结果，冻结批次及事件身份保持。

Validated on the current Mac against anonymized and original read-only logs:

| Agent | Log version | Evidence |
| --- | --- | --- |
| Claude Code | 2.1.220 | assistant tool_use and user tool_result, explicit is_error |
| Codex | 0.155.0-alpha.9.2 | response_item function/custom calls and outputs, session_meta, turn_context |
| Codex | 0.158.0-alpha.2.1 | Ten independent live custom exec calls and structured result blocks; explicit exit codes 0/7, body omission and unknown process relation verified |
| Codex | 0.160.0 | Two isolated live sessions, nine calls and nine results; automatic base-worker discovery, persistence, strict ACK and bilingual operation details verified. Log support does not certify plugin trust or managed Hook installation. |
| Codex | 0.160.1 | Native CLI session before and after the client update: user/context inputs, commentary, final reply, custom exec call and output. The post-update session has six log records with matching local/platform logical IDs and durable ACKs. An anonymized native fixture verifies bounded cursor resume and reply phases. |
| Codex | 0.163.0-alpha.10.2 | `additional_tools` metadata preserves session context. Bounded replay verifies quarantined source bytes and restores missing messages and tool identities; tests cover cursor persistence and unchanged original evidence. Earlier version fixtures remain covered. |

Cursor `call_turns[].tool` is an optional, bounded tool name retained for reliable call/result parsing. The server accepts it without rewriting existing frozen batches; absent values preserve legacy projections. A rejected frozen batch must be retried unchanged after the compatible server update, not regenerated. See the [client compatibility and recovery notes](../../../../docs/agent-manager-client.md) and [acceptance records](../../../../experiments/aidr-agentlog/ACCEPTANCE.md).

游标 `call_turns[].tool` 为可选、有界的工具名，服务端兼容接收；旧游标缺失该字段时投影保持。兼容升级后按原冻结字节重试，不重算摘要或重建队列。0.160.0 与 0.160.1 日志已通过真实自动读取及网页验收；插件信任、Hook 实际触发和受管安装分别验收。0.160.1 回归样本覆盖用户输入、过程/最终回复、工具调用/结果及有界读取续传；没有退出码的工具输出保留未知结果。

The table records real-version acceptance, not a parser allowlist. Compatible records from other versions are collected; this does not certify every new record shape. Linux/Windows compilation does not certify real log discovery on those systems. `testdata/provenance.json` documents replacements in local anonymous examples. No original private log is checked in.

```sh
go test -race ./internal/aidr/agentlog ./cmd/agent-manager-client ./internal/runtimeobservation
python3 ../experiments/aidr-agentlog/verify_contract.py
```

See `experiments/aidr-agentlog/ACCEPTANCE.md` for real-source measurements and UI scope.

## Stable reasons / 稳定原因码

| Code | 中文 | English |
| --- | --- | --- |
| aidr_log_source_missing | 日志源不存在 | Log source is missing |
| aidr_log_permission_denied | 无读取权限 | Read permission denied |
| aidr_log_schema_unsupported | 已知关键记录结构损坏，游标停留原记录 | Invalid recognized structure; cursor retained |
| aidr_log_optional_record_skipped | 未知可选记录已隔离跳过，覆盖不完整 | Unknown optional record quarantined; coverage partial |
| aidr_log_context_invalidated | 未知身份形态或超大记录使关联失效，等待明确元数据恢复 | Identity context invalidated; explicit metadata required for recovery |
| aidr_log_invalid_json | JSON 无效，游标停留原记录 | Invalid JSON; cursor retained |
| aidr_log_partial_line | 等待完整行 | Awaiting a complete line |
| aidr_log_record_too_large | 超限记录已跳过，覆盖不完整 | Oversized record skipped; coverage partial |
| aidr_log_read_budget / aidr_log_event_budget / aidr_log_discovery_budget | 读取、事件或发现预算不足 | Read, event or discovery budget reached |
| aidr_log_rotated / aidr_log_truncated / aidr_log_rewritten | 文件轮转、截断或检查点变化 | File rotated, truncated or checkpoint changed |
| aidr_log_version_unverified / aidr_log_session_unknown | 版本未验证或会话未知 | Unverified version or unknown session |
| aidr_log_canceled | 本轮已取消 | Collection canceled |
| aidr_log_symlink / aidr_log_source_outside_root | 符号链接或超出授权根 | Symlink or source outside allowed root |

The protocol carries codes, not localized business decisions. A future UI must translate codes with semantic i18n keys.


### P1 补强：平台统一 AIDR 审计脱敏

入口：**系统管理 → 系统总览 → AIDR 审计脱敏**（英文 System Overview → AIDR audit redaction）。管理员且具有 `settings:update` 权限可修改，默认开启；修改人、时间、前后开关与版本进入管理审计，不记录命令内容。设备详情同时展示平台目标策略、客户端报告的版本/开关及最后刷新时间；没有支持报告的旧客户端显示未知/旧版本继续脱敏，不宣称已应用关闭状态。

`aidr-sync` 启动后先读取缓存并尝试认证获取策略，以后每 30 秒重试，下一轮有界采集生效。网络往返及当前采集轮次会增加延迟，这不是硬实时 SLA。离线/获取失败使用已持久化缓存，首次失败默认开启（版本 0）；状态码为 `aidr_policy_applied`、`aidr_policy_cached`、`aidr_policy_response_invalid`。本地 `agent-log-collect` 使用同一状态目录的缓存，无平台连接时不主动刷新。

关闭仅关闭允许字段的敏感值替换，命令里的真实凭证可能进入本地数据库及后台；白名单、UTF-8 字节上限、截断、控制字符处理和正文排除不变。完整 Prompt、独立文件正文、完整结果、未知参数不采集。明确的内联正文/脚本参数及 heredoc 仍省略，标记 `body_omitted`，不冒充凭证脱敏。普通 `git commit -m "fix scanner ownership across client credential rotation" && git status --short --branch` 在两种策略下均完整保留。明确 `--password`、秘密环境变量赋值、Authorization/Bearer、Cookie 和受支持令牌格式在开启时遮蔽其值，保持引号与操作符。

升级不删除或重建本地数据。平台新增策略下发记录表；本地 metadata 增加策略缓存及应用序列边界。事件 `behavior.policy` 保存 `version/enabled/receipt`，`redacted` 表示发生替换，`body_omitted` 单独说明正文排除。服务端以绑定设备/stream 的真实下发记录授权，开启策略再次检查敏感模式，未下发版本或错误设备/序列拒绝（`aidr.redaction_policy_invalid`）。客户端持久化应用新策略后，在下次刷新确认上报旧数据序列上界；只有确认后才关闭旧策略范围，响应丢失仍可重试。冻结批次不修改、不重算摘要；旧队列按采集策略补传，即使当前目标已开启，合法 OFF 积压仍可接收。离线采集时间无法由服务端独立证明，策略依赖认证客户端正确报告应用边界，不提供终端可信执行证明。

切换只影响后续新逻辑事件，不恢复、重采或清洗历史。版本 1/2 事件、既有内容哈希、覆盖游标及 ACK 契约保留；重读通过既有身份复用原始投影并保留新位置的来源证据；已淘汰正文的墓碑保持淘汰，避免恢复历史或重复逻辑事件。旧客户端继续固定脱敏，需升级才支持开关。版本 3 不支持向旧平台降级上报，部署顺序为先平台后采集端。

## Hook result provenance / Hook 结果来源契约

Hook 结果和日志结果分别投影。Hook 的 `tool_response` 字符串是宿主正文，即使正文恰好包含 JSON、`Exit code 0` 或成功字样，也不能作为结构化状态；Hook 只解析直接对象中的已有白名单字段。日志适配器则按其已验证的 JSON 文本/文本块格式解析结果，两者不互相补写。`exitCode`、`success`、`is_error` 等未经当前来源契约验证的别名不被新增为结果依据。

Hook `tool_response` strings remain body text, including JSON-looking stdout. Only direct objects can supply the supported structured fields. Log adapters independently support their verified encoded-JSON/text-block shapes. Missing Hook outcomes stay unchanged when logs provide separate execution evidence.

| 原始来源 / Raw source | 归一化 / Projection | 证据级别 / Evidence level |
| --- | --- | --- |
| Codex 0.158.0-alpha.2.1 Bash PostToolUse: `"aidr-native-hook-check\n"` 或 `""` | `unknown`, no exit code, `host_result_not_provided` | 仓库原生验收记载；当前临时原始报告已不保留 / Recorded native acceptance; original temporary reports unavailable |
| Claude 2.1.220 Bash PostToolUse: 无明确退出码 / no explicit exit code | `unknown`, no exit code, `host_result_not_provided` | 仓库原生验收记载 / Recorded native acceptance |
| Claude Bash PostToolUseFailure: `error="Exit code 7\n…"` | `reported_error`, exit 7, `error_exit_header` | 已有原生验收及官方固定首行契约 / Recorded native acceptance and documented header |
| Claude PostToolUseFailure: `is_interrupt=true` | `reported_cancelled`, `interrupted`; no inferred exit code | 官方字段契约及合成回归，当前宿主实机待验 / Documented field and synthetic regression; current native shape pending |
| 直接对象 / direct object: `{"exit_code":0}` / `{"exit_code":7}` | `reported_success` / `reported_error`, exact exit code | 既有适配器契约及合成回归；不代表该宿主实际发送 / Existing adapter contract and synthetic regression; native emission unverified |
| 直接对象 / direct object: `{"interrupted":true}` / `{"cancelled":true}` | `reported_cancelled`, matching basis | 前者有 Claude 官方 Bash 字段契约；后者是已有适配器合成契约，当前原生来源未验证 / Claude documents the first; the second is existing synthetic adapter support, native emission unverified |
| Hook stdout string: `"{\"exit_code\":0}"` | `unknown`, `host_result_not_provided` | 防止正文冒充状态的合成回归 / Synthetic body-versus-status regression |
| 直接对象 / direct object: `{"exit_code":"0"}` / `{"exitCode":0}` | `unknown`, `result_format_unsupported` | 错误类型或未支持的来源字段 / Invalid type or unsupported source field |
| Failure `error="Exit code 0\n…"`；日志同一结果含 exit 0 与 exit 7 | `unknown`, no exit code, `result_fields_conflict` | 合成冲突回归 / Synthetic conflicting-evidence regression |

来源依据：[Claude Hook reference](https://code.claude.com/docs/en/hooks#posttoolusefailure)、[Codex Hook reference](https://developers.openai.com/codex/hooks#posttooluse)、[Codex PostToolUse input source](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/events/post_tool_use.rs)。官方文档描述的是当前上游契约，不替代指定安装版本的原始字段验收；仓库原生历史依据见 `experiments/aidr-agentlog/ACCEPTANCE.md` 的 Claude/Codex 原生审计补验。宿主 Hook 回执、Agent 整轮退出和工具操作系统成功分别核对。

结果未知时先在插件事件详情核对 `behavior.uncertainty`、依据、完整 session/turn/call 身份及来源摘要，再独立查看日志通道的工具结果与覆盖缺口。来源 call ID 不同、设备/用户/子代理身份不完整时，不能靠时间接近关联。当前平台展示来源证据，不把日志状态并入 Hook，不把接收器或 Agent 整轮退出码充当工具退出码。冻结上传及既有事件保持原样；新增结果原因适用于后续归一化。

Affected UI manual checks / 受影响 UI 手工检查：插件事件详情与关联插件证据，操作详情结果原因，采集诊断。中文和 English 下逐项核对成功/非零、取消、纯 stdout、未知格式、冲突原因；旧事件仍显示原投影；开启/关闭正文采集均不改变结果依据；英文长原因不溢出。UI 交互由人工验收，未新增 UI 单元测试。

## Product adapter boundaries

The generated `../catalog/products.json` comes from `backend/aidr_products.json`.
`workbuddy.go` handles desktop response-item JSONL; `qoder.go` accepts only explicit
CLI entry envelopes; `opencode.go` reads complete part snapshots and joins message
metadata by native IDs. Unknown formats remain visible coverage gaps. Snapshot
text is emitted only once the host marks the assistant message complete; native
`finish=stop` and `finish=tool-calls` distinguish final and intermediate replies.
WorkBuddy `completed` does not establish reply phase or shell exit status.
WorkBuddy result metadata is parsed separately from output text: logs use
`providerData.toolResult.rawResponse`; native Hooks provide the same structure
as `tool_response`. For Bash/PowerShell, numeric `exitCode` supplies the reported
exit status. Explicit `is_error`/`isError`, `interrupted`, and `sandboxDenied`
provide error, completion, cancellation, or sandbox-denial evidence. Missing
fields remain unknown; output text is never searched for an exit code. This
adapter is based on the installed WorkBuddy 5.6.2 implementation and real samples.
Log output and Hook-provided error text retain the existing capture/redaction
limits. A successful Bash Hook often contains metadata only; its output remains
available in the separate Agent-log timeline. Existing uploaded events are not
rewritten and collection cursors are not reset by this change.

WorkBuddy 结果独立解析宿主元数据：日志取 `providerData.toolResult.rawResponse`，
Hook 取 `tool_response`。Bash/PowerShell 的数值型 `exitCode` 表示宿主报告退出码；
显式错误、取消和沙箱拒绝标记用于对应状态。正文、`completed` 和模型自述不用于
推断退出码。日志输出及 Hook 错误正文继续按采集、脱敏和截断策略处理。
成功命令的 Hook 可能只有元数据，完整输出查看日志通道；历史入库事件保持不变。

`aidr-sync --source product-id=/absolute/root` can be repeated (1..64 roots).
Root discovery and file progress are independent; duplicate configured roots are
coalesced. Recoverable source errors do not terminate other products. Database
and queue-capacity failures keep their existing shared-store semantics. No source
payload is rewritten, and all emitted events use the existing redaction/policy,
logical identity and strict upload ACK path.

The opt-in `AIDR_LOCAL_PRODUCT_SAMPLES=1 go test ./internal/aidr/agentlog -run
TestLocalProductSamples -v` reads local samples and prints only aggregate counts;
it does not upload data or copy conversations into fixtures. This is parser
validation, not real end-to-end product acceptance.
