# Local durable Agent log state / 本地持久化状态

P1-02 stores projected Agent log events, evidence identities, source generations,
coverage and read checkpoints in a dedicated SQLite database. It uses the
existing `modernc.org/sqlite` dependency. It does not install a service, start an
Agent, upload records or change the existing managed-client database.

## 使用 / Usage

```sh
agent-manager-client agent-log-collect \
  --state-dir /absolute/private/aidr-state \
  --agent claude --root /absolute/log/root --file /absolute/log/root/session.jsonl
agent-manager-client agent-log-state --state-dir /absolute/private/aidr-state
agent-manager-client agent-log-state --state-dir /absolute/private/aidr-state \
  --action events --limit 100 --after ''
agent-manager-client agent-log-state --state-dir /absolute/private/aidr-state --action prepare
agent-manager-client agent-log-state --state-dir /absolute/private/aidr-state --action prune
```

Use `--agent codex` for Codex JSONL. Discover source files with P1-01's
`agent-log-read`; collection intentionally selects an explicit source per call.
Each invocation performs one bounded read and atomic commit. Repeat to continue;
the cursor comes from SQLite, not a caller-supplied JSON checkpoint. An existing
source retains its original `--since` scope (default initial lookback 24 hours).
Read limits remain 4 MiB / 500 events / one second per invocation. A path must be
absolute with no symlink components; on macOS use `/private/tmp` instead of the
`/tmp` symlink for temporary work.

`--state-dir` 必须是专用目录；新建时权限为 0700，数据库和锁文件为 0600。
已有共享权限目录会被拒绝，不自动修改其他目录权限。一个数据库仅允许一个进程
持有写锁；进程退出或被强杀后由操作系统释放。Windows 目前只有编译验证，部署时
仍需独立验证 ACL，不能把 POSIX mode 检查视为 Windows 权限验收。

## 原子性、身份与恢复

- `Collect` 从持久化游标读取，`Commit` 在同一事务中写入逻辑事件、逐条证据、
  覆盖历史、来源代次/游标及 outbox；SQLite WAL 使用 `synchronous=FULL`。
- 乐观 revision 校验拒绝过期结果。失败或取消时整批回滚，读取游标不推进。
- 逻辑 ID 与证据 ID 分开唯一约束。重复记录只增加不同位置/代次的证据；逻辑
  事件只排队一次。相同 ID 的不同语义内容返回冲突，不能覆盖旧证据。
- 所有正文都是 P1-01 的投影，保留工具名、ID、时间、摘要与 `unknown` 进程关系；
保存白名单内按采集时平台策略处理的命令、工作目录、目标及结果依据；不保存完整 Prompt、文件正文或工具结果。内容摘要不等于加密或防字典猜测。
- 来源 offset、generation、revision 和上传 sequence 在 JSON 中使用十进制字符串。
- 非正常退出后状态保留 `aidr_store_unclean_shutdown`，表示可能存在未提交读取，
  不代表已提交数据已丢失。提交前数据需要源日志仍在才能重读；源轮转/截断由
  P1-01 标记实际覆盖缺口。重启不会自动清除已有缺口或恢复标记。

## 待上传批次 / Outbox

`Prepare` 生成最多 500 条 / 1 MiB 的本地批次正文，事务中保存完整字节、摘要、
批次 ID 和最高队列序号。一次只保留一个在途批次，重启和 ACK 丢失都返回相同
字节。缩小预算导致已有批次放不下时返回 `aidr_store_batch_limit`，不拆改该批次。

`Acknowledge` 是库接口：未来 P1-03 上传器必须先验证经过认证的服务端持久化回执，
然后传入匹配的 batch ID/digest，才能推进上传序号。读取游标不会随 ACK 改动。
重复确认最近一次已确认批次幂等；其他过期或不匹配回执拒绝。CLI 不提供伪造
服务端确认的操作。`prepare` 仅准备本地数据，没有实际发送；当前契约不代表完整
设备认证或平台 API 已实现。覆盖记录与事件一起排队，源不可读即使没有事件也可
留下证据。

## 容量与保留

默认数据库页配额 1 GiB（1024 MiB）、逻辑 ID 100,000、证据 ID 200,000、覆盖历史 200,000、
来源 4,096、outbox 204,096 条。批次输入最多 4,096 个事件；单个投影最多 16 KiB，
游标最多 512 KiB、覆盖最多 16 KiB。页面查询最多 500 条，批次按实际编码字节切分。
`--max-db-mib`、`--max-events`、`--max-evidence`、`--retention-days` 可调整对应策略；
同一状态目录的调用方应使用一致策略。数据库配额是 SQLite 页上限，不是包含 WAL
和 SHM 的整个目录字节上限；WAL 每 256 页自动 checkpoint，单批事务可临时产生
额外日志空间，关闭和清理时请求 truncate checkpoint。不能据此声明系统磁盘不会满。

上传器校验平台持久化 ACK 后，同一事务释放该批事件正文、关联证据正文和覆盖快照正文，
保留 ID、摘要、来源与观测时间、ACK 水位及解析游标。启动时自动释放旧库中已确认正文；
未确认记录及冻结批次原样保留。旧库升级时执行一次 VACUUM 合并释放正文后稀疏的页，
可能临时需要额外磁盘空间；后续启动及 ACK 后增量回收空闲页，采集可复用页内空间。
`events` 本地查询仅返回尚保留的正文，已上传历史在平台查看。

已确认逻辑身份、证据摘要及覆盖元数据默认保留 7 天；未确认记录和冻结批次不按时间
清理。`prune` 将 ACK 且过期事件的逻辑身份与关联元数据一起回收，事务中持久化
单调 `retired_through` 观测时间水位。仍在库内的身份继续严格比较原内容摘要，
ACK 不改身份。首次迁移已有无正文墓碑时，使用保留期截止时间作为保守水位。
水位不随重启、策略切换或增加保留期回退，单次推进最高为当前时间减保留期，
不因异常观测时间排除正常近期迟到事件。未知事件观测时间晚于本机时间 5 分钟
时，标记 `aidr_log_timestamp_future` 覆盖缺口并隔离；这依赖设备时钟，不能视为
可信事件时间证明。既有已 ACK 异常记录过期可回收，但不把水位推到近期或未来。

未知逻辑身份的观测时间不晚于水位时，原文 rewind/rotation 不会恢复历史正文或
重新上传；记录 `aidr_audit_history_retention` 覆盖缺口并增加 filtered 数量，读取
游标仍原子推进。仍待 ACK 的较早身份照常保留、去重、校验冲突。全局水位也会
排除迟到但从未采集的历史记录，不能将此范围宣称 complete。水位后的新记录可
继续使用回收的配额。状态返回水位和 80% 容量预警 `aidr_store_capacity_warning`。

本地精确去重范围是保留窗口，平台是永久身份权威：`client_id + logical_id`
唯一约束保留 ACK 身份和摘要，服务端保留策略仅清除正文。窗口外日志若被改写
时间而再次入队，平台比较身份摘要，不生成第二个逻辑事件、不恢复过期正文；
内容改变返回冲突。离线待上传不代表已得到平台全局判重确认；本地不能独立证明
不可信日志的时间或无限期保存任意身份。平台必须保留该权威身份契约。

无待发覆盖、无保留事件的来源检查点可以回收；持久全局单调 revision 分配器使
重新发现后的 coverage ID 不与平台旧记录碰撞。缺失且已退休的 discovery 文件
目录项回收；仍存在的文件目录项保留，因此 Sources 配额仍约束同时发现的文件
集合。SQLite 使用 incremental auto-vacuum 与可重用空闲页；旧数据库首次打开会
原地 VACUUM 启用该模式，可能临时需要额外磁盘空间。退休后增量释放空闲页并
truncate WAL；数据库和真实磁盘空间仍是有限资源，未 ACK 积压超限时暂停采集。

队列/身份/SQLite 页配额触顶时返回 `aidr_store_capacity`，批次回滚，原游标保留；
`intake_code` 尽力持久化失败原因。若介质已完全不可写，错误仍返回给调用方，但
不能承诺错误本身成功落盘。状态接口显示当前容量压力，不能只看源的历史 complete
就认定新数据已消费。暂停期间日志可能轮转，因此不能承诺尚未落库事件不丢。

## 稳定状态码 / Stable codes

| Code | 中文 | English |
| --- | --- | --- |
| aidr_store_capacity | 存储容量不足，游标未推进 | Capacity reached; checkpoint retained |
| aidr_store_checkpoint_conflict | 读取基于过期游标 | Stale read checkpoint |
| aidr_store_batch_conflict | 相同身份内容冲突或回执不匹配 | Content or receipt conflict |
| aidr_store_batch_limit | 预算无法容纳待发记录或已冻结批次 | Record or frozen batch exceeds budget |
| aidr_store_unclean_shutdown | 上次非正常退出，可能有未提交读取 | Unclean shutdown; uncommitted reads possible |
| aidr_store_write_failed | 本轮未能落库 | Intake could not be committed |
| aidr_store_busy | 状态目录已被其他写入进程占用 | Another writer owns the state directory |
| aidr_store_directory_not_private | 状态目录权限不私有 | State directory is not private |
| aidr_store_path_invalid | 状态路径或文件类型不符合要求 | Invalid state path or file type |
| aidr_store_schema_unsupported | 不支持此数据库版本 | Unsupported database version |
| aidr_store_corrupt | 持久化记录无法解析 | Stored record cannot be decoded |
| aidr_store_invalid | 输入或存储预算无效 | Invalid input or storage budget |
| aidr_store_options_invalid | 命令参数无效 | Invalid command options |
| aidr_store_action_invalid | 不支持此本地操作 | Unsupported local operation |

没有新增 UI，也没有 UI 单元测试。真实平台上传、断网补传调度和界面分别由
P1-03/P1-05/P1-04 承接。自动、强杀和实机测试见
[P1-02 验收记录](../../../../experiments/aidr-agentlog/STORE_ACCEPTANCE.md)。


### P1 补强：平台统一 AIDR 审计脱敏

入口：**系统管理 → 系统总览 → AIDR 审计脱敏**（英文 System Overview → AIDR audit redaction）。管理员且具有 `settings:update` 权限可修改，默认开启；修改人、时间、前后开关与版本进入管理审计，不记录命令内容。设备详情同时展示平台目标策略、客户端报告的版本/开关及最后刷新时间；没有支持报告的旧客户端显示未知/旧版本继续脱敏，不宣称已应用关闭状态。

`aidr-sync` 启动后先读取缓存并尝试认证获取策略，以后每 30 秒重试，下一轮有界采集生效。网络往返及当前采集轮次会增加延迟，这不是硬实时 SLA。离线/获取失败使用已持久化缓存，首次失败默认开启（版本 0）；状态码为 `aidr_policy_applied`、`aidr_policy_cached`、`aidr_policy_response_invalid`。本地 `agent-log-collect` 使用同一状态目录的缓存，无平台连接时不主动刷新。

关闭仅关闭允许字段的敏感值替换，命令里的真实凭证可能进入本地数据库及后台；白名单、UTF-8 字节上限、截断、控制字符处理和正文排除不变。完整 Prompt、独立文件正文、完整结果、未知参数不采集。明确的内联正文/脚本参数及 heredoc 仍省略，标记 `body_omitted`，不冒充凭证脱敏。普通 `git commit -m "fix scanner ownership across client credential rotation" && git status --short --branch` 在两种策略下均完整保留。明确 `--password`、秘密环境变量赋值、Authorization/Bearer、Cookie 和受支持令牌格式在开启时遮蔽其值，保持引号与操作符。

升级不删除或重建本地数据。平台新增策略下发记录表；本地 metadata 增加策略缓存及应用序列边界。事件 `behavior.policy` 保存 `version/enabled/receipt`，`redacted` 表示发生替换，`body_omitted` 单独说明正文排除。服务端以绑定设备/stream 的真实下发记录授权，开启策略再次检查敏感模式，未下发版本或错误设备/序列拒绝（`aidr.redaction_policy_invalid`）。客户端持久化应用新策略后，在下次刷新确认上报旧数据序列上界；只有确认后才关闭旧策略范围，响应丢失仍可重试。冻结批次不修改、不重算摘要；旧队列按采集策略补传，即使当前目标已开启，合法 OFF 积压仍可接收。离线采集时间无法由服务端独立证明，策略依赖认证客户端正确报告应用边界，不提供终端可信执行证明。

切换只影响后续新逻辑事件，不恢复、重采或清洗历史。版本 1/2 事件、既有内容哈希、覆盖游标及 ACK 契约保留；重读通过既有身份复用原始投影并保留新位置的来源证据；窗口内历史复用原始身份；窗口外原文按持久退休水位排除，平台保留身份判重和冲突校验。旧客户端继续固定脱敏，需升级才支持开关。版本 3 不支持向旧平台降级上报，部署顺序为先平台后采集端。
